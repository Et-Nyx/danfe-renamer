---
name: land
description: >-
  Land this thread's changes in the danfe-renamer repository: commit them and
  push to main on GitHub (Et-Nyx/danfe-renamer). Invoke only when the user has
  explicitly requested landing - for example through Delta's Land Changes
  button or an equivalent request to land or merge the changes - never for
  review, preparation, running checks, or installing skills.
disable-model-invocation: true
metadata:
  delta-action: land
---

# Land changes in danfe-renamer

An invocation of this skill is the user's explicit request to land the current
changes. Proceed with the workflow below; do not ask whether the user really
wants to merge. Stop only for the genuine blockers listed here.

This project lands directly on `main` on GitHub: linear history, no pull
requests, no merge commits, no CI. Publishing releases (tags, GitHub
releases) is a separate manual action and is never part of landing.

## Environment rules

- Every python, pip, pytest and pyinstaller command must run with `PYTHONPATH`
  cleared (`PYTHONPATH= <command>`): a user-level `PYTHONPATH` on this machine
  points at an old ClickOnce Python and breaks the interpreter
  (README.md, "Development", including its note).
- If `.venv/` is missing, create it the way the README does:
  `PYTHONPATH= /c/ProgramData/anaconda3/python.exe -m venv .venv` followed by
  `PYTHONPATH= .venv/Scripts/python.exe -m pip install -r requirements-dev.txt`
  (README.md, "Development").

## Workflow

1. Work from the repository root. Summarise the current state with
   `git status --short` and `git diff --stat` so the landing report can name
   what is being landed.
2. Stage everything (`git add -A`; .gitignore keeps `.venv/`, `build/`,
   `dist/` and `.scratch/` out) and commit. Write the message in the
   repository's existing style: one imperative sentence that states the
   change, no generated-by footers (see `git log --oneline`).
3. Sync with the destination before testing: `git fetch origin` then
   `git rebase origin/main` so the branch stays a linear continuation of it.
   - If the rebase conflicts: stop, report the conflicted files, and ask the
     user how to proceed. This project's conflict policy is to pause and ask;
     never resolve conflicts unilaterally and never force-push.
4. Verify the exact tree that will be pushed:
   `PYTHONPATH= .venv/Scripts/python.exe -m pytest` (README.md,
   "Development"). Every test must pass. If the diff touches `packaging/`,
   `pyproject.toml` or `run_danfe_renamer.py`, also build with
   `PYTHONPATH= .venv/Scripts/pyinstaller.exe --noconfirm --clean packaging/danfe_renamer.spec`
   (README.md, "Building the .exe") and require "Build complete!" in the
   output.
5. Publish with `git push origin main`. If the push is rejected as
   non-fast-forward, fetch and rebase again, re-run the verification, and
   retry once; if it is still rejected, stop and report. Do not force-push.
6. Confirm the landing: `git ls-remote origin refs/heads/main` must show the
   pushed commit. The landing is successful only once the destination branch
   contains the commit.

## Outcome reporting

- When running in a Delta subthread where `report_subthread_status` is
  available, report the landing result to the parent with it; otherwise report
  in the current conversation.
- Use `status: "success"` only after step 6 verified the commit on
  `origin/main`; use `status: "failure"` for a failed attempt or a genuine
  blocker (tests failed, conflicts waiting on the user, push denied). Keep
  `title` to a few sentence-case words ("Landed on main", "Blocked by tests")
  and `description` to one short line linking the commit
  (`https://github.com/Et-Nyx/danfe-renamer/commit/<sha>`).
- Questions - conflicts, unclear scope - belong in the conversation, not in
  the status event.
