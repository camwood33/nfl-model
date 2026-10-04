"""
Nightly commit-and-push of collected data. Run at 02:30 local by the
com.cameronwood.nfl-git-sync LaunchAgent (launchd/).

  1. Wait for the dispatcher's lock, so a Kalshi pull can't be half-written
     into data/raw/ while it's being staged.
  2. Regenerate clv_tracker/records/bets_dump.sql (export_dump reads bets
     inside one SQLite read transaction, so it is a consistent snapshot even
     if something is writing the database).
  3. Commit ONLY data/raw/ and the dump, as "Nightly data sync: YYYY-MM-DD".
     `git commit -- <paths>` commits just those paths, so code edits -- even
     ones already `git add`ed -- are never swept in. nfl_bets.db itself is
     never staged by this job.
  4. Push if the branch is ahead of origin. A failed push is logged (and a
     macOS notification posted); the commit stays local and the next run
     pushes it. Never force-pushes, rebases, or amends.

    python3 scripts/nightly_git_sync.py
"""
from __future__ import annotations

import fcntl
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clv_tracker.export_dump import DUMP_PATH, export_dump
from data.collect.dispatch import LOCK_PATH

logger = logging.getLogger("git_sync")

GIT = "/usr/bin/git"
BRANCH = "main"
SYNC_PATHS = ["data/raw", str(DUMP_PATH.relative_to(ROOT))]
LOCK_WAIT = 15 * 60          # seconds to wait for an in-progress dispatcher pull
PUSH_TIMEOUT = 120           # a credential helper stuck on a prompt must not hang the job
# Never prompt: under launchd there is nobody to answer, so fail fast instead.
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/usr/bin/false"}
_AUTH_MARKERS = ("Authentication failed", "Invalid username or token", "could not read Username",
                 "terminal prompts disabled", "403", "401")


def git(*args: str, check: bool = True, timeout: int | None = 60) -> subprocess.CompletedProcess:
    r = subprocess.run([GIT, *args], cwd=ROOT, env=GIT_ENV, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({r.returncode}): {r.stderr.strip()}")
    return r


def notify(message: str) -> None:
    """Best-effort macOS notification, so a failure is seen without reading the log."""
    try:
        subprocess.run(["/usr/bin/osascript", "-e",
                        f'display notification "{message}" with title "NFL git sync" sound name "Basso"'],
                       timeout=10, capture_output=True)
    except Exception:
        pass


def acquire_lock(f) -> bool:
    deadline = time.monotonic() + LOCK_WAIT
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(5)


def preflight() -> str | None:
    """Reason to skip this run, or None."""
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != BRANCH:
        return f"checked out on {branch!r}, not {BRANCH!r}"
    gitdir = ROOT / ".git"
    for marker in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        if (gitdir / marker).exists():
            return f"a git operation is in progress ({marker})"
    return None


def commit_data(today: str) -> bool:
    """Export the dump and commit data/raw + dump if changed. Returns True if a commit was made."""
    export_dump()
    git("add", "--", *SYNC_PATHS)
    if git("diff", "--cached", "--quiet", "--", *SYNC_PATHS, check=False).returncode == 0:
        logger.info("No data changes in %s -- nothing to commit.", ", ".join(SYNC_PATHS))
        return False
    changed = git("diff", "--cached", "--name-status", "--", *SYNC_PATHS).stdout.strip()
    git("commit", "--quiet", "-m", f"Nightly data sync: {today}", "--", *SYNC_PATHS)
    sha = git("rev-parse", "--short", "HEAD").stdout.strip()
    logger.info("Committed %s:\n%s", sha, changed)
    return True


def push() -> bool:
    ahead = git("rev-list", "--count", f"origin/{BRANCH}..HEAD").stdout.strip()
    if ahead == "0":
        logger.info("Nothing to push: %s is level with origin.", BRANCH)
        return True
    logger.info("Pushing %s commit(s) to origin/%s.", ahead, BRANCH)
    try:
        r = git("push", "origin", f"{BRANCH}:{BRANCH}", check=False, timeout=PUSH_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.error("PUSH FAILED: git push timed out after %ss (credential prompt?). "
                     "Commit(s) left local; will retry next run.", PUSH_TIMEOUT)
        notify("Push timed out -- commits left local")
        return False
    if r.returncode != 0:
        err = r.stderr.strip()
        auth = any(m in err for m in _AUTH_MARKERS)
        logger.error("PUSH FAILED%s (exit %s). %s commit(s) left local; will retry next run.\n%s",
                     " -- GitHub AUTH rejected, token likely expired" if auth else "",
                     r.returncode, ahead, err)
        notify("Push failed: GitHub token expired?" if auth else "Push failed -- see outputs/logs/git_sync.log")
        return False
    logger.info("Pushed: %s", (r.stderr or r.stdout).strip().splitlines()[-1])
    return True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Nightly git sync starting.")
    try:
        reason = preflight()
        if reason:
            logger.warning("Skipping: %s.", reason)
            return 0
        git("fetch", "--quiet", "origin", BRANCH, check=False, timeout=PUSH_TIMEOUT)

        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOCK_PATH, "w") as lock:
            if not acquire_lock(lock):
                logger.error("Dispatcher lock still held after %ss -- skipping tonight.", LOCK_WAIT)
                notify("Skipped: dispatcher lock held")
                return 1
            commit_data(datetime.now().date().isoformat())
        # Lock released: pushing doesn't touch the working tree.
        return 0 if push() else 1
    except Exception as exc:
        logger.exception("Nightly git sync FAILED: %s", exc)
        notify("Sync failed -- see outputs/logs/git_sync.log")
        return 1


if __name__ == "__main__":
    sys.exit(main())
