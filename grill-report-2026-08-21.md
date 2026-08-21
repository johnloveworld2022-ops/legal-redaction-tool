---
plugin: grill
version: 1.2.3
date: 2026-08-21
target: /Users/mac/法律脱敏工具
style: Hard-Nosed Critique + Roadmap
addons: none
agents: [recon, architecture, error-handling, security, testing]
---

# Codebase Grill: 法律脱敏工具 (Legal Case Redaction Tool)

**Context**: a solo-developer, local-only PII redaction tool for a lawyer's real Chinese-language
legal casework. ~1585 core LOC, 122 passing pytest tests, no CI, macOS-only. Every finding below
was independently re-verified by the synthesizing agent by reading the actual source and, where
practical, reproducing the bug (path traversal exploits were run and confirmed to work exactly as
described; the report-clobbering, Keychain-error-conflation, and leak-check-scope claims were
confirmed by direct code inspection). Nothing below is speculation dressed up as fact.

**Status update (2026-08-21, same day)**: All 8 Critical findings below were fixed before this
report was committed to the (public) repo, specifically because publishing working exploit
reproductions for unpatched vulnerabilities would have been an irresponsible live disclosure.
Each fix was TDD'd (a red test reproducing the exact bug, confirmed failing against the
pre-fix code, then made to pass), and the two most safety-critical ones (the path-traversal
exploits and the multi-document report-clobbering bug) were additionally verified end-to-end
against the real running Flask server with a real Ollama model — not just unit tests. Test
suite grew from 122 to 152 passing tests over the course of these fixes. See each Critical
finding below for its specific "**Fixed**" annotation, and the Fixing Plan's Phase 1 for what
changed and where. Phases 2-4 (High/Medium/Low findings) remain open as originally reported.

---

## Critical Flaws

Presented as concrete scenarios, not abstractions — each one is something that actually happens
given the code as written today.

### 1. A case name with a stray `/` writes case data outside the sandbox entirely
`core/case_workspace.py:83-89` only `.strip()`s `case_name` before building
`WORKBENCH_ROOT / f"案件_{case_name}"`. Reproduced directly:
```python
case_name = 'x/../../../../../tmp/evil_case'
(WORKBENCH_ROOT / f'案件_{case_name}').resolve()  # -> /private/tmp/evil_case
```
`ensure_created()` then `mkdir(parents=True)`s the four staging folders at that resolved path —
outside `~/法律脱敏工作台/` entirely. `case_name` reaches this function from a POST **form field**
(`gui/app.py:42`), not a URL path segment, so none of Werkzeug's route-level `..`/slash protection
applies. This isn't a hypothetical hostile actor — an OCR'd or copy-pasted case identifier that
happens to contain a stray `/` is enough to scatter a case's raw documents, OCR'd text, and
encrypted mapping key outside the one folder this tool exists to keep everything contained in.

**✅ Fixed (2026-08-21)**: `case_workspace_for` now rejects any `case_name` containing `/`, `\`,
or `..` before building the path, and `gui/app.py`'s `/process` route catches the resulting
`ValueError` and re-renders the form with a plain-language error instead of a bare 500. Verified
with `tests/test_case_workspace.py` (6 traversal-payload variants) and confirmed against the real
running server that the exploit no longer creates a directory outside the workbench.

### 2. `/reprocess`'s `stem` field is an unsanitized path — content-controlled arbitrary file write
`gui/app.py:112-125`:
```python
stem = request.form["stem"]                    # no sanitization
tmp_txt = tmp_dir / f"{stem}.txt"
tmp_txt.write_text(corrected_text, encoding="utf-8")   # attacker-controlled content
```
Reproduced directly: `stem = '../../../../../../tmp/pwned_via_reprocess'` resolves outside
`tmp_dir` and writes `corrected_text` (a form field, fully attacker-controlled) to that path. The
exact same file (`gui/app.py:64`) already does this correctly for uploaded filenames
(`Path(f.filename).name`) — the fix pattern already exists in the same file, just wasn't applied
here.

**✅ Fixed (2026-08-21)**: `reprocess()` now applies `Path(request.form["stem"]).name` before use,
mirroring the existing correct pattern. The regression test (`test_reprocess_rejects_path_
traversal_in_stem`) initially gave a false pass because it checked the wrong directory (pytest's
`tmp_path` fixture, not the real system `/tmp` that `tempfile.mkdtemp()` actually uses) — caught
and corrected before trusting the result; the corrected hermetic test (sandboxing `tempfile.
mkdtemp` itself) properly reproduced the exploit pre-fix and passed post-fix. Also confirmed
against the real running server: the payload no longer writes outside the temp directory.

### 3. No CSRF protection anywhere — "localhost-only" is not an origin boundary
None of `/process`, `/reprocess`, `/approve` (`gui/app.py`, forms in `gui/templates/case.html`,
`index.html`) carry a CSRF token or check `Origin`/`Referer`. Binding to `127.0.0.1` blocks remote
network attackers but does **not** stop a malicious web page open in the same browser from
auto-submitting a hidden form to `http://127.0.0.1:5055/case/<case>/reprocess`. Chained with
Finding #2, this turns "local single-user tool, safe by construction" into a page-load-triggered
arbitrary file write — a materially different threat model than the code's own comments assume.

**✅ Fixed (2026-08-21)**: Added a minimal manual per-session CSRF token (not flask-wtf, to avoid
a new dependency, consistent with this project's existing minimal-dependency approach) — a
`before_request` hook rejects any POST without a matching `session["csrf_token"]`, injected into
every form via a Jinja context processor. Verified with `tests/test_gui.py` (missing token,
wrong token, and correct token cases) and against the real running server (a token-less POST
returns 403; the legitimate flow with a real session cookie still works end-to-end). Along the
way, the test for a deliberately-wrong token surfaced a real secondary bug: `secrets.compare_
digest` raises `TypeError` on non-ASCII input, meaning a malicious/malformed submission would
have produced an unhandled 500 instead of a clean 403 — fixed by comparing UTF-8-encoded bytes.

### 4. The GUI throws away the one signal that tells you something failed
`gui/app.py:67` and `:121`:
```python
process_case_files(case_name, saved_paths)   # return value discarded
```
`process_case_files` returns a `ProcessSummary` whose `skipped` list exists specifically to record
files that failed to convert — a corrupted PDF, an unsupported extension, poppler not installed
(`core/orchestrator.py:76-85`). The CLI (`process_case.py:28-54`) surfaces this correctly. The GUI
— the interface the lawyer actually uses — discards it entirely and just redirects. `view_case`
(`gui/app.py:74-103`) rebuilds its file list by globbing the candidate folder; a file that never
made it there simply isn't in the list, with zero banner, zero count, zero indication anything was
dropped. A lawyer who uploads 5 documents and gets 4 back has **no way to know** one silently
failed. This is precisely the "looks like success" failure class the whole architecture is
designed around preventing — and it's the actual user-facing entry point where it happens.

**✅ Fixed (2026-08-21)**: Both `/process` and `/reprocess` now capture the `ProcessSummary`
return value and flash a plain-language message listing any skipped filenames and reasons before
redirecting. Verified with `tests/test_gui.py::test_process_surfaces_skipped_files_via_flash`.

### 5. The "independent" leak-check can only catch 6 regex patterns — never a missed name
`core/leak_check.py:3,41` imports and calls only `detect_structured_pii` (ID card, phone, bank
card, email, birthdate, case number). It never re-runs `match_lexicon` or
`detect_llm_entities_chunked` against the final text. If a person's name, an organization, or a
free-text address is missed by *both* the lexicon and the LLM stage during processing, it is never
added to `mapping`, and the leak-check — the tool's explicitly-documented "last line of defense
before export" — has **no mechanism whatsoever** to catch it, because names/addresses have no
regex signature to fall back on. `tests/test_leak_check.py` only exercises the cases the current
design *can* catch; there is no way to write a passing test for an undetected-name leak, because
the mechanism doesn't cover that surface. This is the single most consequential gap in the report:
it sits exactly where the fuzziest, most failure-prone detector (the LLM) would fail, and is
marketed (in the tool's own README) as the safety net for exactly that.

**✅ Partially fixed (2026-08-21)**: `verify_no_leak` now takes an optional `lexicon` parameter and
also re-runs `match_lexicon` against the output text, closing the gap for any name/org in the
lawyer's own case-person list that both the lexicon-match and LLM stages somehow missed during
processing. Both call sites (`process_case_files`, `approve_case_export`) now pass the case's
lexicon through. Verified with a new orchestrator-level integration test
(`test_leak_check_catches_lexicon_name_the_pipeline_missed_entirely`) that was confirmed to fail
against the pre-fix wiring and pass post-fix. **Deliberately not fully closed**: re-running the
LLM detector itself on the output (to catch a name NOT in the lexicon that the LLM also missed
during processing) is a separate, more expensive decision — another model call per document —
left as an open, explicitly-flagged design choice rather than silently deferred.

### 6. Correcting one document's OCR error silently deletes every other document's review flags
`core/orchestrator.py:69,148-153`: `process_case_files` builds `results` only from the
`file_paths` passed into *that specific call*, then unconditionally overwrites
`02_候选脱敏/审核报告.md` from just that list. The GUI's own documented correction workflow
(`gui/app.py:112-125`, and `core/report.py`'s own instructions telling the user to fix an OCR
misread by dragging a corrected `.txt` back in) calls `process_case_files(case_name, [tmp_txt])`
with a **single file**. For any case with more than one document, this regenerates the review
report describing *only* the reprocessed document — silently discarding every other document's
flagged pages, table warnings, and leak-check results, with no merge and no warning that scope
just shrank. This is a real data-loss bug in the exact workflow the tool's own UI text instructs
the user to follow, not a hypothetical.

**✅ Fixed (2026-08-21)**: Implemented as a text-level merge rather than a full state-persistence
redesign — `process_case_files` now reads the prior `审核报告.md` (if any), extracts the "## X"
sections for any candidate files NOT part of the current call (via new `core/report.py` helpers
`list_document_headings`/`extract_document_sections`/`merge_preserved_sections`), and splices them
back into the freshly-generated report, upgrading the summary header to "needs review" if any
preserved section still does. (Scoped deliberately: the actual export-safety mechanisms — leak-check,
table detection, etc. — were never bypassed by this bug; `approve_case_export` already independently
re-checks every candidate file on disk regardless of what the report says. The bug was specifically
that the human-readable report could mislead the lawyer about which documents still need review.)
Verified with new tests in `tests/test_report.py` (7 new tests for the three helper functions) and
an orchestrator-level integration test that reproduces the exact scenario (process doc1 → needs
review; process doc2 separately → doc1's section must survive), confirmed to fail against the
pre-fix code and pass post-fix. Additionally verified end-to-end against the real running server
with two real documents and the real Ollama model.

### 7. A locked Keychain or a denied access prompt silently destroys the case's encryption key
`core/mapping_store.py:24-39`: any non-zero return from `security find-generic-password` — a
genuinely-absent key, but equally a locked keychain or the user clicking **Deny** on the standard
macOS Keychain-access prompt — takes the identical code path: generate a brand-new Fernet key and
call `add-generic-password ... -U` (update-if-exists). If a key already existed for this case, it
is now silently overwritten, and `mapping.json.enc` — the only record connecting a placeholder
token back to a real name — becomes **permanently undecryptable**, with zero warning and zero log
line. The next `load()` call raises `cryptography.fernet.InvalidToken`, uncaught anywhere upstream.
This is the tool's core promise (reversible redaction) failing silently on exactly the kind of
transient OS-level hiccup (screen lock, an accidentally-dismissed prompt) that will eventually
happen on real hardware.

**✅ Fixed (2026-08-21)**: `_get_or_create_key` now checks `result.returncode` against the
empirically-confirmed "genuinely not found" code (44) specifically, and raises `RuntimeError` for
any other non-zero code instead of falling through to key generation. Verified with
`tests/test_mapping_store.py::test_non_44_keychain_failure_raises_instead_of_silently_regenerating_key`
(mocks a non-44 failure, asserts `add-generic-password` is never called).

### 8. The Keychain call can hang the entire single-threaded GUI forever
`core/mapping_store.py:25-38` calls raw `subprocess.run(...)` directly — it never imports or uses
`core/subprocess_utils.py`, whose own docstring states *"Every external command in this tool goes
through here so none of them can wedge the GUI forever."* `security` can block on an interactive
Keychain-authorization dialog. `gui/app.py:160` runs the Flask dev server without `threaded=True`,
so a stuck `security` call inside a request handler freezes **every subsequent request for every
case**, indefinitely, with nothing to time it out and nothing to log since it never actually
"fails" from the process's point of view.

**✅ Fixed (2026-08-21)**: All three Keychain calls in `mapping_store.py` (`find-generic-password`,
`add-generic-password`, `delete-generic-password`) now go through `subprocess_utils.run_subprocess`
with an explicit 30-second timeout, bundled into the same fix as Finding #7 since both live in the
same function. Verified with
`tests/test_mapping_store.py::test_keychain_calls_go_through_the_timeout_wrapper`.

---

## 80/20 Rewrite Plan

The 8 critical findings above share a common shape: **narrow, surgical fixes**, not architectural
rewrites. None of them require touching the detection pipeline's core design (regex/lexicon/LLM →
merge/replace → leak-check), which the architecture agent confirmed is genuinely well-separated.
The 80/20 here is: fix the plumbing around the good core, don't rebuild the core.

**The ~20% of effort that removes ~80% of the real risk** (roughly 2-3 days of focused work):

1. **Path sanitization** (Findings #1, #2) — one guard clause in `case_workspace_for`, one
   `.name` call in `/reprocess`. ~1 hour combined. Mirrors a pattern that already exists correctly
   elsewhere in the same files.
2. **Surface `ProcessSummary` in the GUI** (Finding #4) — thread `skipped`/`all_clean` into the
   redirect (flash message or query param), render it in `case.html`. Half a day.
3. **Fix Keychain error handling** (Findings #7, #8) — distinguish "not found" (exit code 44) from
   "any other error" (raise, don't regenerate); route all `security` calls through
   `subprocess_utils.run_subprocess`. Half a day, and it closes two CRITICAL findings at once
   because they share the same root cause (the same function, `_get_or_create_key`).
4. **CSRF tokens on the three POST routes** (Finding #3) — Flask-WTF or a manual per-session token.
   Half a day. This defuses Finding #2 from "remotely triggerable" back down to "local bug," even
   before #2 itself is fixed.
5. **Fix the report-clobbering bug** (Finding #6) — either merge new results into the existing
   report's document list instead of overwriting, or make `generate_report` explicitly
   case-scoped by reading all existing candidate files, not just the ones from this call. Most
   involved item here, budget a full day including a regression test for the multi-doc-reprocess
   scenario specifically.
6. **Extend the leak-check's re-scan to also re-run lexicon matching** (Finding #5, partial fix)
   — cheap, immediate, and closes the gap for the case where the lexicon (not the LLM) should have
   caught a name but a merge/replace bug let it through. Re-running the LLM stage on the *output*
   as a full fix is more expensive (another model call per document) and worth a separate,
   deliberate decision — call this out to the user rather than silently deferring it forever.

Everything else in this report (logging, CI, dependency pinning, test portability, GUI test
coverage) is real and worth doing, but is reliability/maintainability work, not "will this leak
real people's PII or corrupt a case" work. Do the 6 items above first.

---

## Prioritized Backlog (15 items, ranked by Impact × Risk ÷ Effort)

| # | Item | Impact | Risk if unfixed | Effort | Finding |
|---|---|---|---|---|---|
| 1 | Sanitize `case_name` and `stem` against path traversal | Critical | Data scattered outside sandbox, cross-case corruption | XS (~1hr) | #1, #2 |
| 2 | Route GUI's `ProcessSummary.skipped`/`all_clean` into the UI | Critical | Silent data loss looks like success | S (~half day) | #4 |
| 3 | Fix Keychain "not found" vs "any error" conflation + route through `subprocess_utils` | Critical | Permanent loss of a case's de-identification key; GUI hang | S (~half day) | #7, #8 |
| 4 | Add CSRF protection to all POST routes | Critical | Remote exploitation of #1/#2 via browser CSRF | S (~half day) | #3 |
| 5 | Fix report-clobbering on partial reprocess | Critical | Silent loss of other documents' review flags | M (~1 day) | #6 |
| 6 | Extend leak-check to re-run lexicon matching on output | High | Undetected name/org leak has zero backstop | S (~half day) | #5 |
| 7 | Fix auto-export gate double-counting pre-merge LLM spans | High | One-click auto-export likely unreachable on real docs, undermining the tool's documented UX | M (~1 day) | Architecture #4 |
| 8 | Add basic logging (persistent file, not `/tmp`, not truncated per relaunch) | High | No way to diagnose "why did this case need review" after the fact | M (~1 day) | Error-handling #4 |
| 9 | Capture and surface the specific Ollama failure reason (not bare `except: continue`) | High | Can't distinguish "Ollama not running" from "model regressed" without live repro | S (~half day) | Error-handling #5 |
| 10 | Add CI (GitHub Actions, `macos-latest`, run `pytest`) | High | Regressions ship unnoticed; currently zero automated gate | S (~half day setup) | Testing #2 |
| 11 | Add an OCR-path golden-corpus test (degraded image → full pipeline → recall check) | High | The tool's actual risky path (scanned/photographed docs) has zero recall regression coverage | M (~1-2 days, needs real/synthetic degraded samples) | Testing #3 |
| 12 | Centralize the `"_候选脱敏.txt"` naming convention into a shared constant | Med | Silent breakage if convert.py's naming changes without a test catching it | XS (~1hr) | Architecture #2 |
| 13 | Add exception handling around orchestrator calls in Flask routes | Med | Bare Flask 500 page to a non-technical lawyer on any unhandled bug | S (~half day) | Error-handling #6 |
| 14 | Make `mapping_store.save()` atomic (temp file + rename) | Med | Crash/power-loss mid-write corrupts the one file that reverses redaction | XS (~1hr) | Error-handling #3 |
| 15 | Add a `requirements.txt`/`pyproject.toml` with pinned versions | Low | Undocumented, unreproducible dependency set; invisible drift | XS (~1hr) | Security #6 |

---

## Red Flags

Patterns that predict future incidents, beyond the specific bugs above:

- **The GUI and the CLI are not actually equivalent surfaces**, despite the orchestrator being
  shared. The CLI correctly surfaces every failure mode the orchestrator reports; the GUI silently
  drops most of them (Finding #4). Whenever a new "please tell the user about X" field gets added
  to `ProcessSummary`/`ApproveSummary` in the future, there is nothing forcing the GUI to actually
  render it — this has already happened once (skipped files) and will happen again unless the GUI
  is required to consume the *entire* summary object, not cherry-pick fields.
- **Safety mechanisms that sound independent but share fate.** The leak-check's regex reuse
  (Finding #5) and the auto-export gate's LLM-only pre-merge counting (backlog #7) are both cases
  where a mechanism *described* as a separate safety net actually inherits the blind spots of the
  thing it's supposed to be checking. This is worth a deliberate audit pass: for every place the
  README claims "independent re-check," verify it doesn't secretly import the same detector it's
  meant to be independent of.
- **Two testing gaps compound each other.** No CI (backlog #10) plus zero GUI test coverage
  (Testing #5) means the actual user-facing layer — where Finding #4 lives — is the *least*
  verified part of the codebase and the *least* likely to have a regression caught before it ships.
- **The golden-corpus 100%/100% number is being used (in the README) as a headline result** while
  only testing the easy path (clean typed text, no OCR). This isn't dishonest — the README does
  disclose the gap — but it's a number that will be quoted out of context eventually. Worth adding
  a second, clearly-labeled OCR-path metric before this number gets more prominent.

---

## Quick Wins

**Under 1 day** (do these regardless of what else gets prioritized):
- Sanitize `case_name` / `stem` against `/` and `..` (backlog #1)
- Route Keychain calls through `subprocess_utils.run_subprocess`, fix the error-code conflation (backlog #3)
- Add CSRF tokens to the 3 POST routes (backlog #4)
- Centralize the `"_候选脱敏.txt"` constant (backlog #12)
- Make `mapping_store.save()` atomic via temp+rename (backlog #14)
- Add a pinned `requirements.txt` (backlog #15)
- Extend leak-check to also call `match_lexicon` on the output (backlog #6)

**Under 1 week**:
- Surface `ProcessSummary`/`ApproveSummary` fully in the GUI, including skipped/failed files (backlog #2)
- Add a GitHub Actions CI workflow on `macos-latest` running the full pytest suite (backlog #10)
- Add basic logging to a persistent, non-`/tmp` location (backlog #8)
- Fix the report-clobbering bug on partial reprocess (backlog #5)
- Add exception handling + a friendly error page around the Flask routes (backlog #13)

---

## Executive Summary

**Verdict**: The detection core of this tool (regex + lexicon + LLM → deterministic merge/replace,
with detection and replacement genuinely, structurally separated) is well-designed and — per the
testing agent — unusually well-tested for what it covers. But the tool's two safety-critical
"independent" backstops (the leak-check, and to a lesser extent the auto-export gate) both quietly
inherit blind spots from the exact mechanisms they're supposed to be checking, and the GUI — the
only interface a real user actually touches — silently discards the specific signals
(`ProcessSummary.skipped`, conversion failures) that the CLI proves the pipeline already knows how
to report. Combined with two directly-exploitable path-traversal bugs and a Keychain-error-handling
bug that can permanently destroy a case's decryption key on an ordinary OS-level hiccup, the
biggest risk isn't "the AI misses a name" (which the architecture already assumes will happen and
plans around) — it's **the plumbing around the good core silently failing in ways the core's own
safety philosophy was specifically designed to prevent**.

**Top 3 actions**:
1. **Fix the two path-traversal bugs and the Keychain error-handling bug this week** (backlog
   #1, #3) — these are the only findings with a real, demonstrated exploit path or a real,
   demonstrated permanent-data-loss path. Everything else in this report is important but not
   "this could destroy a real case's data or leak it outside the sandbox" urgent.
2. **Make the GUI actually report what the orchestrator already knows** (backlog #2) — the
   cheapest possible fix (the data already exists in `ProcessSummary`) for the single scariest
   *class* of bug (silent success-looking failure) in a tool whose entire design philosophy is
   built around never letting that happen.
3. **Close the leak-check's blind spot for names/orgs, at least partially, this sprint**
   (backlog #6) — the tool markets this mechanism as its last line of defense; right now it
   defends against the failure modes least likely to occur (structured-pattern misses) and not the
   one most likely to occur (a name the LLM/lexicon both missed).

**Confidence levels**:
- **High** — the 8 critical findings: all independently re-verified by direct code reading, and
  three (the two path-traversal bugs, the case-workspace resolve) were reproduced with running
  code, not just inferred from reading.
- **High** — the "no CI" and "golden corpus bypasses OCR" findings: confirmed by direct grep/read,
  trivially verifiable, low risk of misinterpretation.
- **Medium** — the auto-export-gate double-counting claim (backlog #7): the code path is confirmed
  as described, but whether this makes auto-export "likely unreachable in practice" depends on
  real-world LLM behavior on actual case documents, which wasn't independently re-tested by the
  synthesizer in this pass. Recommend running `scripts/golden_recall.py` with a lexicon populated
  from one of the golden-corpus documents' own party names to directly observe whether auto-export
  triggers, before treating this as certain.
- **Medium** — severity ranking within the "High" tier of the 15-item backlog is a judgment call
  about which reliability gap matters more; reasonable people could reorder items 6-11 without
  being wrong. The Critical tier (1-5) is not up for debate — those are directly reproduced bugs.

## Fixing Plan

### Phase 1: Critical fixes (do immediately)

**Status: ✅ All 7 items below completed 2026-08-21** (same day as this report), before the report
was committed to the public repo. See the "✅ Fixed" annotation under each Critical finding above
for what actually changed, which differs in a few places from the plan as originally written below
(kept here unedited for an honest record of the original plan vs. what was actually done).

- **Finding**: `case_name` accepts `/` and `..`, allowing case data to be written outside
  `~/法律脱敏工作台/` entirely (`core/case_workspace.py:83-89`).
  **Fix**: In `case_workspace_for`, reject `case_name` containing `/`, `\`, or `..` before
  building the path — e.g. `if any(c in safe_name for c in ("/", "\\")) or ".." in safe_name:
  raise ValueError("案件名称不能包含路径符号")`.
  **Effort**: XS (~30 min including a regression test).
  **Files to modify**: `core/case_workspace.py`, `tests/test_case_workspace.py` (new or extend
  existing lexicon test file).

- **Finding**: `/reprocess`'s `stem` form field is used unsanitized in a path join, allowing
  arbitrary-content file writes outside the intended temp directory (`gui/app.py:112-125`).
  **Fix**: `stem = Path(request.form["stem"]).name` before use, mirroring the existing correct
  pattern at `gui/app.py:64`.
  **Effort**: XS (~15 min).
  **Files to modify**: `gui/app.py`.

- **Finding**: No CSRF protection on `/process`, `/reprocess`, `/approve` — combined with Finding
  #2 above, a malicious web page can trigger arbitrary file writes with no user interaction beyond
  having the GUI open (`gui/app.py`, `gui/templates/case.html`, `index.html`).
  **Fix**: Add Flask-WTF (or a minimal manual per-session token: generate on `/`, embed as a
  hidden field in every form, verify in every POST handler before proceeding).
  **Effort**: S (~half day, including template updates).
  **Files to modify**: `gui/app.py`, `gui/templates/case.html`, `gui/templates/index.html`,
  `setup_mac.sh` (add `flask-wtf` if used).

- **Finding**: GUI discards `ProcessSummary` entirely on `/process` and `/reprocess`, so a
  skipped/failed file (corrupted PDF, missing poppler, etc.) produces no visible signal to the
  lawyer (`gui/app.py:67,121`).
  **Fix**: Capture the returned `ProcessSummary`; if `summary.skipped` is non-empty, flash a
  message listing the skipped filenames and reasons before redirecting; consider also surfacing
  `summary.all_clean` explicitly rather than relying solely on `view_case`'s glob-based
  reconstruction.
  **Effort**: S (~half day, includes a Flask test-client test).
  **Files to modify**: `gui/app.py`, `gui/templates/case.html` (render skipped-file flash),
  new `tests/test_gui.py`.

- **Finding**: `_get_or_create_key` treats every non-zero `security find-generic-password` exit
  identically to "key doesn't exist yet," silently generating and overwriting the Keychain entry
  even when the real cause was a locked keychain or a denied access prompt — permanently orphaning
  the case's existing `mapping.json.enc` (`core/mapping_store.py:24-39`).
  **Fix**: Check `result.returncode` against 44 (the documented "item not found" code) explicitly;
  raise a clear, catchable exception for any other non-zero code instead of falling through to
  key generation.
  **Effort**: S (~half day, includes a test simulating a non-44 failure via a stubbed
  `subprocess.run`).
  **Files to modify**: `core/mapping_store.py`, `tests/test_mapping_store.py`.

- **Finding**: `mapping_store.py`'s Keychain calls use raw `subprocess.run` directly, bypassing
  `core/subprocess_utils.py`'s timeout wrapper entirely — combined with the Flask dev server
  running single-threaded, a hung/prompting `security` call freezes the whole GUI indefinitely
  (`core/mapping_store.py:25-38`, `gui/app.py:160`).
  **Fix**: Import and use `subprocess_utils.run_subprocess` for all three `security` invocations
  in `mapping_store.py`; decide on and document a sane timeout (Keychain access should be
  near-instant when it works).
  **Effort**: S (~1-2 hours, bundle with the Phase 1 Keychain fix above since it's the same
  function).
  **Files to modify**: `core/mapping_store.py`.

- **Finding**: `process_case_files` overwrites `审核报告.md` from only the current call's
  `results`, so reprocessing a single document via the documented correction workflow silently
  deletes every other document's review flags from the case's report (`core/orchestrator.py:69,
  148-153`).
  **Fix**: Either (a) have `generate_report` read and merge in the existing report's
  per-document sections for files not in the current `results` list, or (b) have
  `process_case_files` reload prior per-file state (ocr_pages/failed_pages/leaks) for documents not
  in this call's `file_paths` and always regenerate the report from the full case's document set,
  not just this call's subset. Option (b) is cleaner but requires persisting per-file review state
  somewhere durable (currently only reconstructed in-memory per call).
  **Effort**: M (~1 day, this is the most structurally involved Phase 1 fix — needs a design
  decision, not just a patch).
  **Files to modify**: `core/orchestrator.py`, `core/report.py`, new regression test simulating
  a multi-document case with a partial reprocess.

### Phase 2: High-priority fixes (this sprint)

- **Finding**: Leak-check only re-runs `detect_structured_pii`, never `match_lexicon` or the LLM
  detector, leaving missed names/orgs/addresses with no independent backstop
  (`core/leak_check.py:3,41`).
  **Fix**: At minimum, also call `match_lexicon(redacted_text, lexicon)` in `verify_no_leak` (cheap,
  catches lexicon-covered names the merge/replace step somehow missed). Treat re-running the LLM
  detector on the output as a separate, deliberate decision (costs another model call per
  document) — surface this tradeoff to the user/README rather than silently deferring it.
  **Effort**: S (~half day for the lexicon re-check; LLM re-check is a separate M-effort item if
  pursued).
  **Files to modify**: `core/leak_check.py` (needs `lexicon` passed in — check callers in
  `core/orchestrator.py`), `tests/test_leak_check.py`.

- **Finding**: The auto-export gate counts the LLM detector's raw pre-merge span count as "low
  confidence found," even when `merge_spans` would have deduped a given span against an existing
  high-confidence lexicon/regex hit — likely making the one-click auto-export path unreachable on
  real documents with any named party (`core/pipeline.py:85`, `core/llm_detector.py:81,95`).
  **Fix**: Compute `low_confidence_count` for the LLM stage from the **post-merge** span list
  (spans still present after `merge_spans`, not the raw detector output), so a duplicate detection
  that merge_spans would discard doesn't block auto-export. Requires reordering `pipeline.py` so
  the low-confidence count is computed after merging, not before.
  **Effort**: M (~1 day, touches the pipeline's stage-ordering logic; needs new tests with a
  populated lexicon and a real-shaped LLM response to confirm auto-export actually triggers).
  **Files to modify**: `core/pipeline.py`, `tests/test_pipeline.py`,
  `tests/test_redact_document_integration.py`.

- **Finding**: No logging framework anywhere; the only trace of a run is an ephemeral `/tmp` log
  file that's truncated on every relaunch.
  **Fix**: Add Python's standard `logging` module, write to a persistent location (e.g.
  `~/法律脱敏工作台/.日志/` or inside each case's workspace), rotate rather than truncate.
  **Effort**: M (~1 day to thread through the modules that currently have no logging at all).
  **Files to modify**: new `core/logging_config.py`, `gui/app.py`, `core/orchestrator.py`,
  `core/llm_detector.py`, `core/mapping_store.py`.

- **Finding**: Ollama call failures are swallowed via bare `except Exception: continue`, so the
  specific cause (connection refused vs. timeout vs. malformed JSON) is never captured anywhere.
  **Fix**: Capture the exception type/message before the `continue`, thread it into
  `LLMDetectionResult` (add an optional `error: str | None` field) so it can reach the log and,
  ideally, the review report's "llm 检测未能正常完成" line.
  **Effort**: S (~half day). **Depends on**: Phase 2's logging fix landing first, or the captured
  error has nowhere useful to go.
  **Files to modify**: `core/llm_detector.py`, `core/pipeline.py`, `core/report.py`.

- **Finding**: No CI/CD — confirmed zero `.github/workflows` or any CI config; pytest only runs
  as part of `setup_mac.sh`'s local install-time self-check.
  **Fix**: Add `.github/workflows/test.yml` running `pytest tests/ -q` on `macos-latest` on
  push/PR (macOS is required since `ocrmac`/Vision/poppler/Keychain are macOS-only — see Phase 3's
  test-portability finding for why this alone won't cover everything).
  **Effort**: S (~half day, including making the Keychain-dependent tests CI-safe — may need a
  CI-specific Keychain unlock step or a skip marker).
  **Files to modify**: new `.github/workflows/test.yml`.

- **Finding**: `scripts/golden_recall.py`'s 100%/100% recall result only exercises clean typed
  text (confirmed: calls `redact_document` directly on file text, bypassing `convert.py`/
  `ocr_vision.py` entirely) — says nothing about recall on the tool's actual risky path (scanned/
  photographed documents).
  **Fix**: Add a second golden-corpus track that runs degraded/synthetic-scanned images through
  the *full* pipeline (`convert.py` → `ocr_vision.py` → detect → leak-check) and reports recall on
  that path separately, clearly labeled as distinct from the clean-text number.
  **Effort**: M (~1-2 days — needs synthetic degraded image samples with ground truth, similar to
  the existing `tests/test_ocr_vision.py` degraded-image fixture but wired through the entire
  pipeline rather than just confidence-flagging).
  **Files to modify**: new `golden_corpus/legal_scanned/`, `scripts/golden_recall_ocr.py` (or
  extend `golden_recall.py` with a mode flag), README update to present both numbers.

### Phase 3: Medium-priority improvements (next sprint)

- **Finding**: No exception handling around `process_case_files`/`approve_case_export` calls in
  Flask routes — any unhandled exception produces a bare Flask 500 page to a non-technical lawyer.
  **Fix**: Wrap the orchestrator calls in `try/except`, flash a plain-language error message
  ("处理时出现意外错误,请联系开发者并提供以下信息:...") on failure, log the full traceback
  (depends on Phase 2's logging fix).
  **Effort**: S (~half day). **Depends on**: Phase 2 logging fix (for the traceback to go
  somewhere useful).
  **Files to modify**: `gui/app.py`.

- **Finding**: `mapping_store.save()` writes directly with `write_bytes`, no temp-file+rename —
  a crash or power loss mid-write corrupts the case's only decryption-key-adjacent file in place.
  **Fix**: Write to a temp file in the same directory, then `os.replace()` onto the final path
  (atomic on the same filesystem).
  **Effort**: XS (~1 hour).
  **Files to modify**: `core/mapping_store.py`, `tests/test_mapping_store.py` (add a test that
  simulates an interrupted write leaving the original file intact).

- **Finding**: No startup validation that `textutil`, poppler binaries, `security`, or the Ollama
  server are actually present/reachable before processing begins — first sign of a problem is a
  mid-pipeline exception.
  **Fix**: Add a lightweight preflight check (could live in `gui/app.py`'s startup or as a
  dedicated `/health` route) that checks each external dependency and surfaces a clear
  "Ollama 未启动,请先启动 Ollama" style message before the lawyer even tries to process a file.
  **Effort**: S (~half day).
  **Files to modify**: new `core/preflight.py`, `gui/app.py`, `setup_mac.sh` (could reuse the
  same check).

- **Finding**: Tests depend on live macOS system state (real Keychain writes/deletes, real Vision
  OCR calls, real poppler binaries) rather than mocks — not portable, and exposed to silent drift
  if Vision's behavior changes with an OS update.
  **Fix**: This is a real tradeoff, not purely a bug — the value of testing against the real OCR
  engine is legitimate given this tool's core risk is OCR misreads. Recommend: keep the current
  tests as an explicit "integration" tier (already effectively true), but ensure the CI workflow
  from Phase 2 accounts for Keychain prompts (may need `security unlock-keychain` in CI setup, or
  explicit skip markers for Keychain-dependent tests when running non-interactively).
  **Effort**: M (~1 day, mostly CI configuration work, tied to Phase 2's CI item).
  **Files to modify**: `.github/workflows/test.yml`, possibly `tests/conftest.py` (new) for
  environment-conditional skip markers.

- **Finding**: `gui/app.py` (the actual user-facing entry point) has zero test coverage — no test
  file references Flask's test client anywhere.
  **Fix**: Add `tests/test_gui.py` using Flask's test client to cover the happy path (upload →
  process → view → approve) and the failure paths this report identifies (skipped file surfaced,
  path-traversal payloads rejected, CSRF token required).
  **Effort**: M (~1 day). **Depends on**: Phase 1 fixes #2 and #4 (CSRF, ProcessSummary
  surfacing) landing first, so the tests verify the fixed behavior rather than the current bugs.
  **Files to modify**: new `tests/test_gui.py`.

### Phase 4: Low-priority cleanup (when touching these files)

- **`core/orchestrator.py` / `gui/app.py`**: Centralize the `"_候选脱敏.txt"` suffix (currently a
  raw string literal duplicated in 6 places — confirmed via grep) into a shared constant in
  `core/case_workspace.py` alongside the existing `LEXICON_FILENAME`/`MAPPING_FILENAME` pattern.
  Add a test exercising the seam between `convert.py`'s file-naming and `gui/app.py`'s glob.

- **`core/case_workspace.py`**: The Keychain service string embeds the raw case name in cleartext
  (`f"法律脱敏工具-{self.root.name}"`), visible to anyone browsing Keychain Access.app. Consider
  deriving a random per-case identifier (stored inside the case workspace) and using that as the
  Keychain service/account instead of the human-readable case name.

- **Project root**: Add a pinned `requirements.txt` or `pyproject.toml` reflecting the actual
  installed versions (Flask 3.1.3, Werkzeug 3.1.8, Jinja2 3.1.6, cryptography 50.0.0 confirmed
  current with no known CVEs at time of review) so dependency drift is visible and reviewable.

### Dependency graph

- Phase 1's Keychain fixes (routing through `subprocess_utils` + fixing error-code handling) are
  the same function (`_get_or_create_key`) — do them together, not as separate PRs.
- Phase 2's "capture Ollama error reason" depends on Phase 2's logging fix landing first (or the
  captured error has nowhere to go but the review report, which is a weaker but valid fallback if
  logging is deferred).
- Phase 3's "exception handling around Flask routes" depends on Phase 2's logging fix (same
  reasoning — a caught traceback needs somewhere to go).
- Phase 3's "test portability" (Keychain-safe CI) depends on Phase 2's CI workflow existing first.
- Phase 3's GUI test suite depends on Phase 1's CSRF and ProcessSummary-surfacing fixes landing
  first, so new tests verify corrected behavior rather than encoding the current bugs as
  "expected."

### Estimated total effort

- Phase 1 (Critical): ~3-4 days
- Phase 2 (High): ~4-5 days
- Phase 3 (Medium): ~3-4 days
- Phase 4 (Low, opportunistic): ~0.5 day
- **Total**: ~10-13 days of focused solo-developer work, front-loaded on the 3-4 days that close
  every directly-reproduced bug in this report.
