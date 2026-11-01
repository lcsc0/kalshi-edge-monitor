"""One hourly lineup-test cycle for an *ephemeral* host (scheduled cloud session).

    python scripts/hourly_lineup.py [--no-push] [--data-dir DIR] [-- <shadow_lineup args>]

Rebuilds the club DB, restores ``lineup_log.sqlite`` from the ``shadow-data`` git branch
(same branch/worktree mechanics as daily_shadow.py, separate file so the two jobs never
write the same binary), runs scripts/shadow_lineup.py (log + settle + scorecard), writes
LINEUP_SCORECARD.md and commits + pushes the result. Places no orders.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

from daily_shadow import DATA_BRANCH, prepare_data_dir, run

LOG_NAME = "lineup_log.sqlite"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data-dir", default="/tmp/shadow-data-worktree")
    p.add_argument("--no-push", action="store_true")
    args, passthrough = p.parse_known_args(argv)
    env = {**os.environ, "SIGNALS_DB": os.path.join(args.data_dir, LOG_NAME)}
    py = sys.executable

    if run([py, "scripts/build_club_db.py"]).returncode != 0:
        print("build_club_db failed - aborting (no data to price with).")
        return 1
    prepare_data_dir(args.data_dir)
    res = run([py, "scripts/shadow_lineup.py", *passthrough], env=env, capture_output=True)
    print(res.stdout, res.stderr)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(os.path.join(args.data_dir, "LINEUP_SCORECARD.md"), "w") as f:
        f.write(f"# Lineup paper test\n\nUpdated {stamp}. **PAPER ONLY - UNVALIDATED**\n\n"
                f"```\n{res.stdout}\n```\n")

    git = ["git", "-C", args.data_dir]
    run([*git, "add", "-A"])
    if run([*git, "diff", "--cached", "--quiet"]).returncode == 0:
        print("No changes to commit.")
        return 0
    run([*git, "-c", "user.name=shadow-bot", "-c", "user.email=shadow-bot@users.noreply.github.com",
         "commit", "-q", "-m", f"lineup: hourly run {stamp}"], check=True)
    if args.no_push:
        return 0
    for attempt in range(4):
        # another job (daily_shadow) may have pushed meanwhile: rebase onto it, then push
        run([*git, "pull", "--rebase", "-q", "origin", DATA_BRANCH])
        if run([*git, "push", "-u", "origin", DATA_BRANCH]).returncode == 0:
            return 0
        run(["sleep", str(2 ** (attempt + 1))])
    print("push failed after retries")
    return 1


if __name__ == "__main__":
    sys.exit(main())
