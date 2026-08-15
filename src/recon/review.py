"""Work the review queue: see what is pending, decide it, record it.

The queue and the log existed; nothing connected a person to them. This is
that connection — deliberately a command-line tool over the decision log
rather than a web interface, because the interesting part is the decision
record and its constraints, not a form.

Subcommands are separate rather than one interactive prompt for a reason
beyond testing: a reviewer working a queue of forty is interrupted, and a
tool that loses its place when they walk away is a tool they stop using.
Every command is idempotent against the log, so the queue is the state.

    python3 -m src.recon.review list
    python3 -m src.recon.review show CHL-4002-W03
    python3 -m src.recon.review approve CHL-4002-W03 --by "priya s"
    python3 -m src.recon.review amend CHL-4002-W03 --cause miscount --by "priya s"
    python3 -m src.recon.review reject CHL-4002-W03 --by "priya s" --note "duplicate"
    python3 -m src.recon.review stats
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from .decisions import Outcome, agreement, open_log, pending, record_decision
from .models import Cause

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "decisions.db"


def _latest_run(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT run_id FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()
    return row["run_id"] if row else None


def cmd_list(conn: sqlite3.Connection, args) -> int:
    run_id = args.run or _latest_run(conn)
    if run_id is None:
        print("no runs recorded — run `python3 -m src.recon.correct` first")
        return 1

    rows = pending(conn, run_id)
    if not rows:
        print(f"run {run_id}: queue is clear")
        return 0

    total = sum(r["value_nzd"] for r in rows)
    print(f"run {run_id}: {len(rows)} awaiting a decision, "
          f"NZ${total:,.2f} at stake\n")
    print(f"{'case':<17}{'value':>10}  {'route':<9}{'cause':<18}{'owner'}")
    print("-" * 74)
    for row in rows[:args.limit]:
        print(f"{row['case_id']:<17}{row['value_nzd']:>10,.2f}  "
              f"{row['route']:<9}{row['cause']:<18}{row['owner']}")
    if len(rows) > args.limit:
        print(f"\n... {len(rows) - args.limit} more (--limit to see them)")
    return 0


def cmd_show(conn: sqlite3.Connection, args) -> int:
    """One correction in full — the evidence a reviewer decides on."""
    row = conn.execute(
        "SELECT * FROM corrections WHERE case_id = ? ORDER BY run_id DESC LIMIT 1",
        (args.case_id,)).fetchone()
    if row is None:
        print(f"no correction for {args.case_id}")
        return 1

    decision = conn.execute(
        "SELECT * FROM decisions WHERE run_id = ? AND case_id = ?",
        (row["run_id"], row["case_id"])).fetchone()

    print(f"{row['case_id']} — NZ${row['value_nzd']:,.2f}")
    print(f"  do        : {row['action'].replace('_', ' ')} "
          f"{row['units']:+d} units of {row['sku_id']}")
    print(f"  owner     : {row['owner']}")
    print(f"  cause     : {row['cause']} (confidence: {row['confidence']})")
    print(f"  week ended: {row['period_end']}")
    print(f"  because   : {row['basis']}")
    if decision is None:
        print("  status    : awaiting a decision")
    else:
        print(f"  status    : {decision['outcome']} by {decision['decided_by']} "
              f"at {decision['decided_at']}")
        if decision["amended_cause"]:
            print(f"  amended to: {decision['amended_cause']}")
        if decision["note"]:
            print(f"  note      : {decision['note']}")
    return 0


def _decide(conn: sqlite3.Connection, args, outcome: Outcome,
            amended_cause: str | None = None) -> int:
    run_id = args.run or _latest_run(conn)
    if run_id is None:
        print("no runs recorded")
        return 1
    try:
        record_decision(conn, run_id, args.case_id, outcome,
                        decided_by=args.by, amended_cause=amended_cause,
                        note=getattr(args, "note", "") or "")
    except KeyError:
        print(f"{args.case_id} is not in run {run_id}")
        return 1
    except ValueError as exc:
        print(f"refused: {exc}")
        return 1

    remaining = len(pending(conn, run_id))
    detail = f" as {amended_cause}" if amended_cause else ""
    print(f"{args.case_id}: {outcome.value}{detail} by {args.by} "
          f"({remaining} left in the queue)")
    return 0


def cmd_approve(conn, args) -> int:
    return _decide(conn, args, Outcome.APPROVED)


def cmd_reject(conn, args) -> int:
    return _decide(conn, args, Outcome.REJECTED)


def cmd_amend(conn, args) -> int:
    valid = {c.value for c in Cause if c is not Cause.NONE}
    if args.cause not in valid:
        print(f"unknown cause {args.cause!r}; expected one of "
              f"{', '.join(sorted(valid))}")
        return 1
    return _decide(conn, args, Outcome.AMENDED, amended_cause=args.cause)


def cmd_stats(conn: sqlite3.Connection, args) -> int:
    """How often a human accepted what the system drafted.

    The figure that would survive in a real store, where nobody has planted
    labels — only whether the person who had to act on a correction agreed
    with it.
    """
    stats = agreement(conn)
    if stats["agreement_rate"] is None:
        print("nobody has reviewed anything yet")
        return 0

    print(f"reviewed  : {stats['reviewed']}")
    print(f"approved  : {stats['approved']} "
          f"({stats['agreement_rate']:.0%} agreement)")
    print("\nby stated confidence:")
    for level in ("high", "medium", "low", "rule"):
        bucket = stats["by_confidence"].get(level)
        if bucket:
            rate = bucket["approved"] / bucket["reviewed"]
            print(f"  {level:<8}{bucket['approved']:>4}/{bucket['reviewed']:<5}"
                  f"{rate:>7.0%}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m src.recon.review",
        description="Work the correction review queue.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--run", help="run id (defaults to the most recent)")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="corrections awaiting a decision")
    listing.add_argument("--limit", type=int, default=20)
    listing.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="one correction, with its evidence")
    show.add_argument("case_id")
    show.set_defaults(func=cmd_show)

    approve = sub.add_parser("approve", help="accept the drafted cause")
    approve.add_argument("case_id")
    approve.add_argument("--by", required=True)
    approve.add_argument("--note", default="")
    approve.set_defaults(func=cmd_approve)

    amend = sub.add_parser("amend", help="post a different cause")
    amend.add_argument("case_id")
    amend.add_argument("--cause", required=True)
    amend.add_argument("--by", required=True)
    amend.add_argument("--note", default="")
    amend.set_defaults(func=cmd_amend)

    reject = sub.add_parser("reject", help="post nothing")
    reject.add_argument("case_id")
    reject.add_argument("--by", required=True)
    reject.add_argument("--note", default="")
    reject.set_defaults(func=cmd_reject)

    stats = sub.add_parser("stats", help="reviewer agreement with the system")
    stats.set_defaults(func=cmd_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.db.exists():
        print(f"no decision log at {args.db} — "
              "run `python3 -m src.recon.correct` first")
        return 1
    conn = open_log(args.db)
    try:
        return args.func(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
