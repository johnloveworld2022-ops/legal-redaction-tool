import io
import tempfile

import pytest

import core.case_workspace as case_workspace
import gui.app as gui_app


@pytest.fixture(autouse=True)
def isolated_workbench(tmp_path, monkeypatch):
    monkeypatch.setattr(case_workspace, "WORKBENCH_ROOT", tmp_path / "工作台")
    # gui.app imported case_workspace_for/list_case_names by reference at
    # module load time, so they still read the *current* module-level
    # WORKBENCH_ROOT correctly (case_workspace_for reads
    # case_workspace.WORKBENCH_ROOT at call time, not import time) --
    # verified by test_normal_case_process below actually landing in
    # tmp_path.
    yield


@pytest.fixture
def client():
    gui_app.app.config["TESTING"] = True
    with gui_app.app.test_client() as c:
        yield c


def _csrf_token(client):
    # Visiting any page renders a template, which (via the app's context
    # processor) establishes a per-session CSRF token -- read it back the
    # same way a real form would carry it, via the session.
    client.get("/")
    with client.session_transaction() as sess:
        return sess["csrf_token"]


def test_path_traversal_case_name_rejected_with_friendly_message_not_500(client):
    token = _csrf_token(client)
    resp = client.post(
        "/process",
        data={
            "case_name": "x/../../../../../tmp/evil_case",
            "files": (io.BytesIO("正文".encode("utf-8")), "doc.txt"),
            "csrf_token": token,
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200  # re-rendered index.html with an error, not a crash
    assert "案件名称" in resp.get_data(as_text=True)


def test_path_traversal_case_name_does_not_create_directory_outside_workbench(client, tmp_path):
    token = _csrf_token(client)
    outside_marker = tmp_path / "tmp" / "evil_case"
    client.post(
        "/process",
        data={
            "case_name": "x/../../../../../tmp/evil_case",
            "files": (io.BytesIO("正文".encode("utf-8")), "doc.txt"),
            "csrf_token": token,
        },
        content_type="multipart/form-data",
    )
    assert not outside_marker.exists()


def test_reprocess_rejects_path_traversal_in_stem(client, tmp_path, monkeypatch):
    from core.case_workspace import case_workspace_for

    case_workspace_for("测试案G")
    token = _csrf_token(client)

    # gui.app's reprocess() calls tempfile.mkdtemp() directly (not
    # controlled by pytest's tmp_path fixture) -- pin it to a
    # sandboxed, known location so the traversal target is checkable
    # without ever touching the real system /tmp during a test run.
    sandbox_parent = tmp_path / "沙盒"
    sandbox_parent.mkdir()
    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(
        tempfile, "mkdtemp",
        lambda prefix=None: real_mkdtemp(prefix=prefix, dir=str(sandbox_parent)),
    )

    # traversal target: three levels above whatever mkdtemp creates
    # inside sandbox_parent -- i.e. escaping sandbox_parent's own parent
    escape_target = tmp_path.parent / "pwned_via_reprocess.txt"

    resp = client.post(
        "/case/测试案G/reprocess",
        data={
            "stem": "../../../pwned_via_reprocess",
            "text": "攻击者控制的内容",
            "csrf_token": token,
        },
    )
    assert not escape_target.exists(), (
        "stem path traversal escaped the sandboxed temp directory -- "
        f"found unexpected file at {escape_target}"
    )
    assert resp.status_code in (200, 302, 400)


def test_post_without_csrf_token_is_rejected(client):
    # No token fetched/submitted at all -- simulates a cross-site form
    # submission from a malicious page the lawyer's browser has open,
    # which cannot read this session's token (same-origin policy) and so
    # cannot include a valid one.
    resp = client.post(
        "/process",
        data={
            "case_name": "合法案件名",
            "files": (io.BytesIO("正文".encode("utf-8")), "doc.txt"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 403


def test_post_with_wrong_csrf_token_is_rejected(client):
    _csrf_token(client)  # establishes a real token in the session
    resp = client.post(
        "/process",
        data={
            "case_name": "合法案件名",
            "files": (io.BytesIO("正文".encode("utf-8")), "doc.txt"),
            "csrf_token": "这不是真的令牌",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 403


def test_process_surfaces_skipped_files_via_flash(client, tmp_path):
    token = _csrf_token(client)
    resp = client.post(
        "/process",
        data={
            "case_name": "测试案跳过",
            "files": (io.BytesIO(b"whatever"), "unsupported.xyz"),
            "csrf_token": token,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "unsupported.xyz" in resp.get_data(as_text=True)


def test_post_with_correct_csrf_token_succeeds(client):
    token = _csrf_token(client)
    resp = client.post(
        "/process",
        data={
            "case_name": "合法案件名",
            "files": (io.BytesIO("正文".encode("utf-8")), "doc.txt"),
            "csrf_token": token,
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302  # redirected to view_case, not rejected
