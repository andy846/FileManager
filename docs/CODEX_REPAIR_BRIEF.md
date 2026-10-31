# FileManager v2.1.1 — Codex repair & review brief

**Target:** `andy846/FileManager`; branch `fix/v2.1.1-data-safety-review`.
**Base:** `main` at `26246e69fe78e59c344c6cef190d5d251691d948`.
**Policy:** Never merge automatically. Do not modify `main` directly. Protect existing user files and keep changes small and testable.

## Phase 1 — implemented for review

- [x] `app/core/workers.py`: replace spinning pause wait with a separate resume event. Cancel wakes paused workers.
- [x] `app/core/transfer.py`: unique per-transfer sibling temp files and final cancellation checkpoint. Preserve atomic replacement.
- [x] `app/modules/copier/worker.py`: stop overwrite if the user-requested Recycle Bin backup fails.
- [x] `app/modules/remover/deleter.py`: bound concurrent delete dispatch to worker count; do not submit after cancel; reconcile completed operations.
- [x] `app/modules/duplicates/worker.py`: reuse bounded deletion engine for duplicate cleanup.
- [x] `app/core/compare.py`: reject overlapping/junction-aliased synchronization roots; block mirror plans if scan errors occurred.
- [x] `app/modules/compare/page.py`: expose rejected plans safely in preview and selection actions.
- [x] `app/core/archive.py`: atomic per-member extraction, realpath checks for existing symlinks/junctions and atomic ZIP creation; preserve prior ZIP when any item fails or operation is cancelled.
- [x] `app/modules/archive/page.py`: show when failed/cancelled ZIP output was not committed.
- [x] `app/ui/main_window.py`: reject closing while detectable page-owned QThreads are still running.
- [x] New `tests/test_data_safety_regressions.py` and Windows workflow `.github/workflows/ci.yml`.

## Phase 2 — Codex must inspect and harden before merge

1. **Destination race & conflict policies:** `skip`, `rename`, `overwrite` must be revalidated at commit time, including concurrent workers and external writers. Detect duplicate target paths, case-insensitive path aliases and TOCTOU races. Never overwrite an existing destination in skip mode.
2. **Move semantics:** verify cross-volume copy-verify-remove, same-volume atomic rename, cancellation immediately before final commit and robust cleanup after an error. Prove that a failed move never destroys the only valid copy.
3. **Destructive operation audit:** make cancellation return a reliable, explicit cancelled flag and ensure completed/deleted/failed/cancelled counts reconcile to the original work list. Stop disabling file safety checks when a scanner encountered unreadable directories.
4. **Archive hardening:** verify zip/tar size limits per member and for total output; reject Windows reserved filenames and alternate data streams; reject symlink/junction traversal even with malicious archive paths or existing output nodes. Treat any extraction error as a failed operation; keep old destination files intact.
5. **Qt shutdown:** check nested dialogs and unparented workers, not only page-owned threads; prevent QThread destruction before completion. Avoid blocking the UI indefinitely.
6. **Sync guard:** when mirror is requested, rescan or validate the source immediately before deletion; if source or target becomes unreadable, abort deletion. Confirm that destructive sync actions cannot target the source tree.
7. **Reporting:** completed task status must be `failed` when any file failed; `cancelled` when cancellation occurred; exported audit must list every operation with its final outcome.

## Phase 2 — implemented (this follow-up)

- [x] Commit-time conflict revalidation in `app/core/transfer.py`
      (`_commit_file`): skip never overwrites, rename reserves a unique name
      under lock, overwrite backups under the same lock; `os.rename`
      no-clobber closes the external-writer race.
- [x] Move semantics: cancellation checkpoints around cross-volume
      copy-then-remove; failed/interrupted moves keep at least one copy.
- [x] Destructive audit: `delete_files` returns cancelled paths, remover
      logs all three outcomes (TXT/CSV/XLSX), task status reflects
      cancellation, and counts reconcile with the original work list.
- [x] Remover scanner surfaces unreadable-directory errors instead of
      silently skipping them.
- [x] Archive hardening: Windows reserved names / trailing dot-space
      rejection, per-member stream size enforcement, per-member error
      containment, and preservation of prior ZIP on failure/cancel.
- [x] Sync guard: mirror deletes re-validate source/target accessibility
      and realpath containment immediately before execution.
- [x] Shutdown discovery: `MainWindow._running_threads()` also scans every
      widget (dialogs included), not only page-owned QThreads.
- [x] Copier cancellation accounting: all futures drain to completion,
      cancelled tasks are classified separately, and done+skipped+failed+
      cancelled reconcile to the total.

## Acceptance criteria

- Run `python -m pytest -q` and `python -m ruff check app` on Windows 11 (Python 3.11, `QT_QPA_PLATFORM=offscreen`).
- Run isolated tests on a temporary directory only. **Never test destructive operations against real user, shared, production, or network data.**
- Regression scenarios: cancel at 0%, midway and just before rename; missing/locked files; partial network read/write; same-name simultaneous transfers; mirror of nested roots; unreadable source subfolder; ZIP cancellation/corruption/symlink escape; app close during active transfer.
- Existing file contents must remain unchanged when a replacement is cancelled, verification fails or required backup fails.
- New tests must fail against v2.1.0 when they exercise the defect and pass after repair.
- Do not claim production-ready without a successful Windows CI run and manual smoke test of copy/move/delete/ZIP/mirror workflows.
- Prepare a summary with file:line references, test command, result and remaining risks; leave the PR as draft until reviewed.

## Suggested Codex task

> Review `fix/v2.1.1-data-safety-review` against `main`. Validate the initial safety fixes, perform Phase 2 hardening with minimal targeted changes, add deterministic regression tests and run Windows CI. Prioritize data integrity over performance and UI polish. Do not alter main, use a separate follow-up branch/PR, and do not merge automatically.
