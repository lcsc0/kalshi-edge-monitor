"""One daily shadow-trading cycle: log every open club market, then settle.

Designed for an *ephemeral* host (a scheduled cloud session): the football DB is
rebuilt each run, while the signal log is persisted on the ``shadow-data`` git
branch, checked out as a worktree and committed back at the end.

    python scripts/daily_shadow.py [--no-push] [--data-dir shadow]

Steps: refresh club results -> restore signal log -> shadow_club (logs every open
club market, model vs market) -> settle + scorecard -> write SCORECARD.md -> commit +
push to shadow-data.
Nothing here places an order; the repo has no order-placement code.
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone

DATA_BRANCH = "shadow-data"
LOG_NAME = "signal_log.sqlite"


def run(cmd, **kw) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, text=True, **kw)


def git_out(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


def prepare_data_dir(path: str) -> bool:
    """Check out the data branch into ``path`` (creating it empty on first run).
    Returns True if the branch already existed on the remote."""
    run(["git", "worktree", "prune"])  # forget worktrees whose directory is gone
    existed = bool(git_out("ls-remote", "--heads", "origin", DATA_BRANCH))
    if os.path.isdir(os.path.join(path, ".git")) or os.path.exists(path) and os.listdir(path):
        return existed  # already prepared (e.g. a rerun in the same session)
    if existed:
        run(["git", "fetch", "origin", DATA_BRANCH], check=True)
        run(["git", "worktree", "add", "-B", DATA_BRANCH, path, f"origin/{DATA_BRANCH}"], check=True)
    else:
        # First run ever: no remote data branch. Drop any stale local one (e.g. from an
        # aborted earlier run) so the orphan checkout below can't collide with it.
        run(["git", "branch", "-D", DATA_BRANCH], capture_output=True)
        run(["git", "worktree", "add", "--detach", path], check=True)
        run(["git", "-C", path, "checkout", "--orphan", DATA_BRANCH], check=True)
        run(["git", "-C", path, "rm", "-rf", "--quiet", "."], check=False)
    return existed


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data-dir", default="/tmp/shadow-data-worktree")
    p.add_argument("--no-push", action="store_true")
    args = p.parse_args(argv)

    env = {**os.environ, "SIGNALS_DB": os.path.join(args.data_dir, LOG_NAME)}
    py = sys.executable

    # Results change daily, so always refresh; the DB is rebuilt from scratch each run.
    if run([py, "scripts/build_club_db.py"]).returncode != 0:
        print("build_club_db failed — aborting (no data to price with).")
        return 1
    prepare_data_dir(args.data_dir)

    rc = run([py, "scripts/shadow_club.py"], env=env).returncode  # logs every open market
    if rc != 0:
        print(f"shadow_club exited {rc}; continuing so earlier signals still settle.")
    settle = run([py, "scripts/settle_signals.py"], env=env, capture_output=True)
    print(settle.stdout, settle.stderr)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(os.path.join(args.data_dir, "SCORECARD.md"), "w") as f:
        f.write(f"# Shadow scorecard\n\nUpdated {stamp}. **UNVALIDATED MODEL — TRADE SMALL**\n\n"
                f"```\n{settle.stdout}\n```\n")

    git = ["git", "-C", args.data_dir]
    run([*git, "add", "-A"])
    if run([*git, "diff", "--cached", "--quiet"]).returncode == 0:
        print("No changes to commit.")
        return 0
    run([*git, "-c", "user.name=shadow-bot", "-c", "user.email=shadow-bot@users.noreply.github.com",
         "commit", "-q", "-m", f"shadow: daily run {stamp}"], check=True)
    if args.no_push:
        return 0
    for attempt in range(4):
        if run([*git, "push", "-u", "origin", DATA_BRANCH]).returncode == 0:
            return 0
        run(["sleep", str(2 ** (attempt + 1))])
    print("push failed after retries")
    return 1


if __name__ == "__main__":
    sys.exit(main())
