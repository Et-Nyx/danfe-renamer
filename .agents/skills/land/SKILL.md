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
requests, no merge commits, no CI. A landing also leaves the repository's
**release page in step with `main`** (steps 7-8): that page is where the person
using the program downloads it from, so a version that exists only as a commit
is not a finished landing. Publishing is part of the landing when it is
available and possible; when it is not, the landing report names the one step
left to run.

Ask `git remote -v` which remote is GitHub: it is `origin` in the primary
checkout, and in a Delta worktree it is `origin` or `github` depending on how
the clone was made. Read `<remote>` below as that one. A worktree usually also
has `local`, the user's own checkout: push the landed commit there too, so it
does not lag behind.

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
3. Sync with the destination before testing: `git fetch <remote>` then
   `git rebase <remote>/main` so the branch stays a linear continuation of it.
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
5. Publish with `git push <remote> main`. If the push is rejected as
   non-fast-forward, fetch and rebase again, re-run the verification, and
   retry once; if it is still rejected, stop and report. Do not force-push.
6. Confirm the landing: `git ls-remote <remote> refs/heads/main` must show the
   pushed commit. The landing is successful only once the destination branch
   contains the commit.
7. Put the release page in step with `main`, which is the point of the landing
   for the person who runs the `.exe`:
   - the version is what the code declares:
     `PYTHONPATH= .venv/Scripts/python.exe -c "import app; print(app.__version__)"`.
   - ask the repository:
     `gh release view "v<version>" --repo Et-Nyx/danfe-renamer`.
   - **already published**: it must not be a draft, must carry the asset
     `DANFE_Renamer_v<version>.exe`, and must be the latest release
     (`gh api repos/Et-Nyx/danfe-renamer/releases/latest --jq .tag_name`). If an
     asset or the notes are missing, re-run the workflow that builds them
     (`gh run list --repo Et-Nyx/danfe-renamer --workflow release`, then
     `gh run rerun <id>`) - a re-run uploads with `--clobber`. Do not tag again,
     and never move or delete a published tag.
   - **not published yet**: the landing must carry
     `packaging/release-notes/v<version>.md` (Portuguese first, English summary,
     `{sha256}` where the workflow substitutes the hash, shaped like the earlier
     files). Then `git tag -a v<version> -m "DANFE Renamer <version>"`, push the
     tag to the GitHub remote, and let `.github/workflows/release.yml` do the
     rest: it refuses a tag that disagrees with `app.__version__`, runs the
     suite, builds the `.exe`, asks it to open its window, and attaches it to
     the release. Watch it with
     `gh run watch <id> --repo Et-Nyx/danfe-renamer --exit-status`.
   - `gh` must be authenticated with write access for this. When publishing is
     not possible from here - no `gh`, no permission, Actions unavailable, or
     the user is landing work that is deliberately unreleased - do not fake it:
     say so in the landing report, with the exact command left to run.
   - A landing that changes nothing the released `.exe` does - tests, docs,
     this skill - needs neither a new version nor a rebuilt asset: leave the
     published release alone, and say in the report that the commits after the
     tag are of that kind.
8. Confirm the release page: `gh release view "v<version>" --repo
   Et-Nyx/danfe-renamer` shows the asset and the notes, and
   `gh api repos/Et-Nyx/danfe-renamer/releases/latest --jq .tag_name` is
   `v<version>`. Report that release URL.

## Outcome reporting

- When running in a Delta subthread where `report_subthread_status` is
  available, report the landing result to the parent with it; otherwise report
  in the current conversation.
- Use `status: "success"` only after step 6 verified the commit on the GitHub
  remote's `main`; use `status: "failure"` for a failed attempt or a genuine
  blocker (tests failed, conflicts waiting on the user, push denied). Keep
  `title` to a few sentence-case words ("Landed on main", "Blocked by tests")
  and `description` to one short line linking the commit
  (`https://github.com/Et-Nyx/danfe-renamer/commit/<sha>`).
- The landing report also says where the release page stands: the URL of the
  release that now matches `main`, or the exact command left to publish it. A
  landing whose tag was pushed but whose release workflow failed is a
  `failure`, with the run link. A landing that could not publish for a reason
  outside this machine is still a `success` once steps 6-8 are reported
  honestly.
- Questions - conflicts, unclear scope - belong in the conversation, not in
  the status event.
