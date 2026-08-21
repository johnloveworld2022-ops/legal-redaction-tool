#!/usr/bin/env python3
"""Local-only web GUI for importing, reviewing, and approving case files.

Runs a Flask dev server bound to 127.0.0.1 only (never exposed to the
network) and opens the default browser to it. This replaces the earlier
AppleScript drag-and-drop droplet with something that can show a flagged
OCR page's saved image right next to an editable text box for correction,
which a modal dialog box cannot do.
"""
import secrets
import shutil
import socket
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import (
    Flask, abort, flash, redirect, render_template, request, send_from_directory,
    session, url_for,
)

from core.case_workspace import case_workspace_for, list_case_names
from core.orchestrator import approve_case_export, process_case_files

PORT = 5055

app = Flask(__name__)
# Random per-process key, only used to sign the flash-message/session
# cookie for this local single-user session -- no cross-restart
# persistence needed.
app.secret_key = secrets.token_hex(16)


def _ensure_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(16)
        session["csrf_token"] = token
    return token


@app.context_processor
def _inject_csrf_token():
    return {"csrf_token": _ensure_csrf_token()}


@app.before_request
def _enforce_csrf_on_post():
    # Binding to 127.0.0.1 only stops remote network attackers -- it does
    # NOT stop a malicious web page open in the same browser from
    # auto-submitting a cross-origin form POST here (browsers allow
    # simple cross-origin form submissions with no preflight). Without
    # this check, that combined with any file-write bug becomes remotely
    # triggerable just by having the GUI open. Found via external
    # security review; see grill-report-2026-08-21.md.
    if request.method != "POST":
        return
    submitted = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    # compare_digest requires bytes/ASCII-only str; a malicious or
    # malformed submission could easily contain non-ASCII characters, and
    # that must be a clean 403, not a 500.
    if not expected or not secrets.compare_digest(
        submitted.encode("utf-8"), expected.encode("utf-8")
    ):
        abort(403)


@app.route("/")
def index():
    return render_template("index.html", existing_cases=list_case_names())


@app.route("/process", methods=["POST"])
def process_files():
    case_name = request.form.get("case_name", "").strip()
    uploaded = [f for f in request.files.getlist("files") if f.filename]

    if not case_name:
        return render_template(
            "index.html", existing_cases=list_case_names(), error="请填写案件名称。"
        )
    if not uploaded:
        return render_template(
            "index.html", existing_cases=list_case_names(),
            error="请选择至少一个文件。", last_case_name=case_name,
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="脱敏上传_"))
    try:
        saved_paths = []
        for f in uploaded:
            # Path(...).name strips any path components but preserves the
            # original filename (including Chinese characters), which
            # matters to her -- this is a local single-user tool, not a
            # multi-tenant web service, so we don't need to ASCII-mangle
            # filenames for safety.
            dest = tmp_dir / Path(f.filename).name
            f.save(dest)
            saved_paths.append(dest)
        try:
            summary = process_case_files(case_name, saved_paths)
        except ValueError as e:
            # case_workspace_for rejects case names containing path
            # separators -- surface this as a plain-language form error,
            # not a bare 500 page.
            return render_template(
                "index.html", existing_cases=list_case_names(),
                error=str(e), last_case_name=case_name,
            )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if summary.skipped:
        skipped_desc = "、".join(f"{name}({reason})" for name, reason in summary.skipped)
        flash(f"⚠️ 以下文件未能处理:{skipped_desc}", "skipped")

    return redirect(url_for("view_case", case_name=case_name))


@app.route("/case/<case_name>")
def view_case(case_name):
    ws = case_workspace_for(case_name)
    candidate_files = sorted(ws.candidate_dir.glob("*_候选脱敏.txt"))
    approved_names = {p.name for p in ws.approved_dir.glob("*_候选脱敏.txt")}

    report_path = ws.candidate_dir / "审核报告.md"
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else None

    documents = []
    for cand in candidate_files:
        stem = cand.name[: -len("_候选脱敏.txt")]
        raw_text_path = ws.text_dir / f"{stem}.txt"
        images = sorted(p.name for p in ws.text_dir.glob(f"{stem}_*_原图.png"))
        documents.append({
            "stem": stem,
            "raw_text": raw_text_path.read_text(encoding="utf-8") if raw_text_path.exists() else "",
            "candidate_text": cand.read_text(encoding="utf-8"),
            "images": images,
            "exported": cand.name in approved_names,
        })

    return render_template(
        "case.html",
        case_name=case_name,
        documents=documents,
        report_text=report_text,
        has_any=bool(documents),
        has_pending=any(not d["exported"] for d in documents),
    )


@app.route("/case/<case_name>/image/<path:filename>")
def case_image(case_name, filename):
    ws = case_workspace_for(case_name)
    return send_from_directory(ws.text_dir, filename)


@app.route("/case/<case_name>/reprocess", methods=["POST"])
def reprocess(case_name):
    # stem is a raw form field, not a URL path segment -- Path(...).name
    # strips any path components so a traversal payload (e.g.
    # "../../../etc/foo") can't escape tmp_dir, mirroring the pattern
    # already used correctly for uploaded filenames in process_files().
    stem = Path(request.form["stem"]).name
    corrected_text = request.form["text"]

    tmp_dir = Path(tempfile.mkdtemp(prefix="脱敏修正_"))
    summary = None
    try:
        tmp_txt = tmp_dir / f"{stem}.txt"
        tmp_txt.write_text(corrected_text, encoding="utf-8")
        summary = process_case_files(case_name, [tmp_txt])
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if summary and summary.skipped:
        skipped_desc = "、".join(f"{name}({reason})" for name, reason in summary.skipped)
        flash(f"⚠️ 重新处理未能成功:{skipped_desc}", "skipped")

    return redirect(url_for("view_case", case_name=case_name))


@app.route("/case/<case_name>/approve", methods=["POST"])
def approve(case_name):
    summary = approve_case_export(case_name)
    if summary.blocked_by_leak:
        names = "、".join(name for name, _leaks in summary.blocked_by_leak)
        flash(
            f"🚨 以下文件在导出前的独立复查中发现可能残留的敏感信息,未导出:{names}。"
            "详情见下方审核报告。",
            "leak",
        )
    return redirect(url_for("view_case", case_name=case_name))


def _open_browser_when_ready():
    time.sleep(1.2)
    webbrowser.open(f"http://127.0.0.1:{PORT}")


def _server_already_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


if __name__ == "__main__":
    if _server_already_running():
        # A previous launch is still up (e.g. she double-clicked the app
        # again) -- just open a tab to it instead of crashing on a
        # port-already-in-use error.
        webbrowser.open(f"http://127.0.0.1:{PORT}")
    else:
        threading.Thread(target=_open_browser_when_ready, daemon=True).start()
        app.run(host="127.0.0.1", port=PORT, debug=False)
