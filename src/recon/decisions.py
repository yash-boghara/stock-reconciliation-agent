"""The decision log: what was posted, what a person decided, and when.

Until now a run printed a queue and forgot it. That is the difference
between a classifier and a system: nothing recorded what happened to a
correction, so nothing could answer the questions that actually matter after
go-live — did the reviewer accept what we drafted, which causes do they
overrule, and is our confidence worth anything.

Three things follow from having this.

**An audit trail.** Auto-posted corrections are adjustments to a stock ledger
made without a human. A system that does that and keeps no record of why is
not one an auditor will sign off.

**A real-world accuracy signal.** Every figure elsewhere in this project is
measured against planted labels, which exist because the data is synthetic.
Reviewer agreement is the measurement that survives contact with a real
store, and it is the one this table produces.

**The substrate for retrieval.** "What happened last time this SKU was
short" is only answerable once there is a last time on record.

SQLite via the standard library: durable, transactional, queryable, and no
dependency — the same constraint the rest of the project runs under.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .correct import Correction, Route

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    seed        INTEGER,
    corrections INTEGER NOT NULL,
    value_nzd   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS corrections (
    run_id      TEXT NOT NULL,
    case_id     TEXT NOT NULL,
    sku_id      TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    cause       TEXT NOT NULL,
    action      TEXT NOT NULL,
    owner       TEXT NOT NULL,
    units       INTEGER NOT NULL,
    value_nzd   REAL NOT NULL,
    route       TEXT NOT NULL,
    confidence  TEXT NOT NULL,
    basis       TEXT NOT NULL,
    PRIMARY KEY (run_id, case_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS decisions (
    run_id        TEXT NOT NULL,
    case_id       TEXT NOT NULL,
    decided_at    TEXT NOT NULL,
    decided_by    TEXT NOT NULL,
    outcome       TEXT NOT NULL,
    amended_cause TEXT,
    note          TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, case_id),
    FOREIGN KEY (run_id, case_id) REFERENCES corrections(run_id, case_id)
);

CREATE INDEX IF NOT EXISTS decisions_by_sku
    ON corrections(sku_id, period_end);
"""


class Outcome(str, Enum):
    POSTED = "posted"      # auto-posted, no human involved
    APPROVED = "approved"  # a reviewer accepted the drafted cause
    REJECTED = "rejected"  # a reviewer rejected it outright
    AMENDED = "amended"    # a reviewer posted a different cause


@dataclass(frozen=True)
class Resolution:
    """One closed case: what was drafted, and what actually happened."""

    case_id: str
    sku_id: str
    period_end: str
    drafted_cause: str
    final_cause: str
    outcome: str
    confidence: str
    decided_by: str
    value_nzd: float


def open_log(path: Path | str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # Foreign keys are off by default in SQLite, which quietly turns the
    # references above into documentation rather than constraints.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_run(conn: sqlite3.Connection, run_id: str,
               queue: list[Correction], *, seed: int | None = None) -> str:
    """Persist a run's corrections, auto-posting the ones nobody reviews.

    Re-recording the same run replaces it rather than duplicating. A run is
    a deterministic function of its input, so a second write is a re-run,
    not a second event — and silently accumulating copies would corrupt
    every rate computed off this table.
    """
    with conn:
        conn.execute("DELETE FROM decisions WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM corrections WHERE run_id = ?", (run_id,))
        conn.execute(
            "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?)",
            (run_id, _now(), seed, len(queue),
             round(sum(c.value_nzd for c in queue), 2)),
        )
        conn.executemany(
            "INSERT INTO corrections VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(run_id, c.case_id, c.sku_id, c.period_end, c.cause.value,
              c.action.value, c.owner, c.units, c.value_nzd, c.route.value,
              c.confidence, c.basis) for c in queue],
        )
        # An auto-posted correction is a decision already taken — by the
        # policy, not by a person. Recording it as one is what makes the
        # ledger complete rather than only tracking the interesting half.
        conn.executemany(
            "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
            [(run_id, c.case_id, _now(), "system", Outcome.POSTED.value,
              None, "auto-posted: rule-certain and under the review threshold")
             # `==` not `is`: running a module with `python -m` gives it a
             # second identity as `__main__`, so a caller's Route.AUTO and
             # this one can be different class objects with the same value.
             # Route subclasses str, so equality compares the value and
             # survives that; identity silently does not, and the failure
             # looks like "nothing was auto-posted" rather than an error.
             for c in queue if c.route == Route.AUTO],
        )
    return run_id


def record_decision(conn: sqlite3.Connection, run_id: str, case_id: str,
                    outcome: Outcome, *, decided_by: str,
                    amended_cause: str | None = None, note: str = "") -> None:
    """Record what a reviewer did with one correction."""
    if outcome is Outcome.AMENDED and not amended_cause:
        raise ValueError("an amended decision must say what it was amended to")
    if outcome is not Outcome.AMENDED and amended_cause:
        raise ValueError(f"{outcome.value} decisions carry no amended cause")

    exists = conn.execute(
        "SELECT 1 FROM corrections WHERE run_id = ? AND case_id = ?",
        (run_id, case_id)).fetchone()
    if exists is None:
        raise KeyError(f"no correction {case_id} in run {run_id}")

    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?,?,?)",
            (run_id, case_id, _now(), decided_by, outcome.value,
             amended_cause, note),
        )


def pending(conn: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    """Corrections still waiting on a person, worst money first."""
    return conn.execute(
        """
        SELECT c.* FROM corrections c
        LEFT JOIN decisions d ON d.run_id = c.run_id AND d.case_id = c.case_id
        WHERE c.run_id = ? AND d.case_id IS NULL
        ORDER BY c.value_nzd DESC, c.case_id
        """,
        (run_id,)).fetchall()


def resolutions(conn: sqlite3.Connection,
                sku_id: str | None = None) -> list[Resolution]:
    """Closed cases — the record a future retrieval step would search.

    `final_cause` is what was actually posted, which is the amended cause
    where a reviewer overruled the draft. Reading the drafted cause as the
    outcome would make the log agree with the system by construction.
    """
    sql = """
        SELECT c.case_id, c.sku_id, c.period_end, c.cause AS drafted,
               COALESCE(d.amended_cause, c.cause) AS final,
               d.outcome, c.confidence, d.decided_by, c.value_nzd
        FROM corrections c
        JOIN decisions d ON d.run_id = c.run_id AND d.case_id = c.case_id
        WHERE d.outcome != 'rejected'
    """
    params: tuple = ()
    if sku_id is not None:
        sql += " AND c.sku_id = ?"
        params = (sku_id,)
    sql += " ORDER BY c.period_end DESC, c.case_id"
    return [
        Resolution(r["case_id"], r["sku_id"], r["period_end"], r["drafted"],
                   r["final"], r["outcome"], r["confidence"], r["decided_by"],
                   r["value_nzd"])
        for r in conn.execute(sql, params).fetchall()
    ]


def agreement(conn: sqlite3.Connection) -> dict:
    """How often a human accepted what the system drafted.

    This is the accuracy figure that would survive in a real store, where
    there are no planted labels — only whether the person who had to act on
    a correction agreed with it. Auto-posted rows are excluded: nobody
    reviewed them, so counting them as agreement would measure the policy
    rather than the judgement.
    """
    rows = conn.execute(
        """
        SELECT c.confidence, d.outcome
        FROM corrections c
        JOIN decisions d ON d.run_id = c.run_id AND d.case_id = c.case_id
        WHERE d.decided_by != 'system'
        """).fetchall()

    by_confidence: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_confidence.setdefault(
            row["confidence"], {"reviewed": 0, "approved": 0})
        bucket["reviewed"] += 1
        bucket["approved"] += row["outcome"] == Outcome.APPROVED.value

    reviewed = len(rows)
    approved = sum(1 for r in rows if r["outcome"] == Outcome.APPROVED.value)
    return {
        "reviewed": reviewed,
        "approved": approved,
        "agreement_rate": round(approved / reviewed, 4) if reviewed else None,
        "by_confidence": by_confidence,
    }
