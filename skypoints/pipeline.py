"""Local, executable SkyPoints ETL reference implementation.

SQLite is used for a laptop demo only. See sql/ for the Snowflake production design.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from .ingest import iter_source
from .transform import ValidationError, normalize_member, normalize_redemption, iso_date

COUNTRY_TABLES = {"IND": "country_india", "USA": "country_usa", "AUS": "country_australia",
                  "PHL": "country_philippines", "CAN": "country_canada"}
PROFILE_FIELDS = ("member_key", "source_member_id", "source_namespace", "member_name",
                  "tier_code", "enrollment_date", "last_flight_date", "dob", "country_code",
                  "member_type", "is_active", "agent_name", "state_code", "post_code",
                  "age", "stale_member", "as_of_date")
CURRENT_FIELDS = PROFILE_FIELDS + ("source_feed_date", "source_file", "source_row")


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(obj: Any) -> str:
    return hashlib.sha256(_json(obj).encode("utf-8")).hexdigest()


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS raw_members (
      raw_id INTEGER PRIMARY KEY AUTOINCREMENT, source_file TEXT NOT NULL,
      source_namespace TEXT NOT NULL, source_row INTEGER NOT NULL,
      feed_date TEXT NOT NULL, ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      raw_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
      UNIQUE(source_file, source_row, raw_hash)
    );
    CREATE TABLE IF NOT EXISTS staging_members (
      raw_id INTEGER PRIMARY KEY REFERENCES raw_members(raw_id),
      member_key TEXT NOT NULL, source_member_id TEXT NOT NULL,
      source_namespace TEXT NOT NULL, member_name TEXT NOT NULL,
      tier_code TEXT, enrollment_date TEXT NOT NULL, last_flight_date TEXT,
      dob TEXT, country_code TEXT NOT NULL, member_type TEXT, is_active TEXT,
      agent_name TEXT, state_code TEXT, post_code TEXT, age INTEGER, stale_member INTEGER, as_of_date TEXT NOT NULL,
      source_feed_date TEXT NOT NULL, apply_status TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_stage_key_date ON staging_members(member_key, source_feed_date);
    CREATE TABLE IF NOT EXISTS current_members (
      member_key TEXT PRIMARY KEY, source_member_id TEXT NOT NULL,
      source_namespace TEXT NOT NULL, member_name TEXT NOT NULL,
      tier_code TEXT, enrollment_date TEXT NOT NULL, last_flight_date TEXT,
      dob TEXT, country_code TEXT NOT NULL, member_type TEXT, is_active TEXT,
      agent_name TEXT, state_code TEXT, post_code TEXT, age INTEGER, stale_member INTEGER, as_of_date TEXT NOT NULL,
      source_feed_date TEXT NOT NULL, source_file TEXT NOT NULL, source_row INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_current_country ON current_members(country_code);
    CREATE TABLE IF NOT EXISTS rejected_records (
      reject_id INTEGER PRIMARY KEY AUTOINCREMENT, source_file TEXT NOT NULL,
      source_row INTEGER NOT NULL, raw_hash TEXT NOT NULL,
      reason TEXT NOT NULL, payload_json TEXT NOT NULL,
      UNIQUE(source_file, source_row, raw_hash, reason)
    );
    CREATE TABLE IF NOT EXISTS raw_redemptions (
      raw_id INTEGER PRIMARY KEY AUTOINCREMENT, source_file TEXT NOT NULL,
      source_row INTEGER NOT NULL, feed_date TEXT, raw_hash TEXT NOT NULL,
      payload_json TEXT NOT NULL, ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(source_file, source_row, raw_hash)
    );
    CREATE TABLE IF NOT EXISTS redemption_transactions (
      member_key TEXT NOT NULL, source_member_id TEXT NOT NULL,
      partner TEXT NOT NULL, txn_id TEXT NOT NULL, txn_date TEXT NOT NULL,
      miles_redeemed INTEGER NOT NULL CHECK(miles_redeemed > 0),
      status TEXT NOT NULL, feed_date TEXT NOT NULL,
      PRIMARY KEY(member_key, partner, txn_id)
    );
    CREATE INDEX IF NOT EXISTS idx_redemptions_member ON redemption_transactions(member_key);
    """)
    for table in COUNTRY_TABLES.values():
        conn.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
          member_key TEXT PRIMARY KEY, source_member_id TEXT NOT NULL,
          source_namespace TEXT NOT NULL, member_name TEXT NOT NULL,
          tier_code TEXT, enrollment_date TEXT NOT NULL, last_flight_date TEXT,
          dob TEXT, country_code TEXT NOT NULL, member_type TEXT, is_active TEXT,
          agent_name TEXT, state_code TEXT, post_code TEXT, age INTEGER, stale_member INTEGER, as_of_date TEXT NOT NULL,
          source_feed_date TEXT NOT NULL, source_file TEXT NOT NULL, source_row INTEGER NOT NULL
        )""")
    conn.commit()


def _reject(conn: sqlite3.Connection, file: str, row: int, payload: Any, reason: str) -> None:
    conn.execute("""INSERT OR IGNORE INTO rejected_records
       (source_file,source_row,raw_hash,reason,payload_json) VALUES (?,?,?,?,?)""",
       (file, row, _hash(payload), reason, _json(payload)))


def _put_row(conn: sqlite3.Connection, table: str, fields: tuple[str, ...], record: dict) -> None:
    cols = ",".join(fields)
    params = ",".join("?" for _ in fields)
    updates = ",".join(f"{col}=excluded.{col}" for col in fields if col != "member_key")
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({params}) "
                 f"ON CONFLICT(member_key) DO UPDATE SET {updates}",
                 tuple(record.get(field) for field in fields))


def _same_business_values(current: sqlite3.Row, new: dict) -> bool:
    compare = ("member_name", "tier_code", "enrollment_date", "last_flight_date", "dob",
               "country_code", "member_type", "is_active", "agent_name", "state_code", "post_code")
    return all(current[field] == new[field] for field in compare)


def load_members(conn: sqlite3.Connection, path: Path, source: str, feed_date: date,
                 as_of: date, *, flat_dob_format: str = "%d%m%Y") -> dict[str, int]:
    """Ingest a file atomically. Feed date is a *proxy*, not true update timestamp."""
    if feed_date > as_of:
        raise ValueError("feed_date cannot be later than as_of")
    stats = {"seen": 0, "accepted": 0, "rejected": 0, "older": 0, "unchanged": 0}
    with conn:
        for number, raw in enumerate(iter_source(path, source), start=1):
            stats["seen"] += 1
            digest = _hash(raw)
            cur = conn.execute("""INSERT OR IGNORE INTO raw_members
                (source_file,source_namespace,source_row,feed_date,raw_hash,payload_json)
                VALUES (?,?,?,?,?,?)""",
                (path.name, source, number, feed_date.isoformat(), digest, _json(raw)))
            if cur.rowcount == 0:
                stats["unchanged"] += 1
                continue
            raw_id = cur.lastrowid
            try:
                normalized = normalize_member(raw, source, as_of,
                                              flat_dob_format=flat_dob_format)
            except ValidationError as exc:
                _reject(conn, path.name, number, raw, str(exc))
                stats["rejected"] += 1
                continue
            current = conn.execute("SELECT * FROM current_members WHERE member_key=?",
                                   (normalized["member_key"],)).fetchone()
            status = "APPLIED"
            if current:
                if current["source_feed_date"] > feed_date.isoformat():
                    status = "IGNORED_OLDER"
                elif current["source_feed_date"] == feed_date.isoformat():
                    if _same_business_values(current, normalized):
                        status = "SKIPPED_EQUAL"
                    else:
                        status = "REJECTED_CONFLICT"
                        _reject(conn, path.name, number, raw, "CONFLICTING_SAME_FEED_DATE")
            stage_fields = ("raw_id",) + PROFILE_FIELDS + ("source_feed_date", "apply_status")
            stage_record = {"raw_id": raw_id, **normalized,
                            "source_feed_date": feed_date.isoformat(), "apply_status": status}
            conn.execute(f"INSERT INTO staging_members ({','.join(stage_fields)}) "
                         f"VALUES ({','.join('?' for _ in stage_fields)})",
                         tuple(stage_record.get(k) for k in stage_fields))
            if status == "REJECTED_CONFLICT":
                stats["rejected"] += 1
                continue
            if status == "IGNORED_OLDER":
                stats["older"] += 1
                continue
            if status == "SKIPPED_EQUAL":
                stats["unchanged"] += 1
                continue
            # The old country row is removed in the same transaction as the new upsert.
            if current and current["country_code"] != normalized["country_code"]:
                old_table = COUNTRY_TABLES[current["country_code"]]
                conn.execute(f"DELETE FROM {old_table} WHERE member_key=?",
                             (normalized["member_key"],))
            full = {**normalized, "source_feed_date": feed_date.isoformat(),
                    "source_file": path.name, "source_row": number}
            _put_row(conn, "current_members", CURRENT_FIELDS, full)
            _put_row(conn, COUNTRY_TABLES[normalized["country_code"]], CURRENT_FIELDS, full)
            stats["accepted"] += 1
    return stats


def load_redemptions(conn: sqlite3.Connection, path: Path) -> dict[str, int]:
    stats = {"seen": 0, "accepted": 0, "rejected": 0, "unchanged": 0, "older": 0}
    document = json.loads(path.read_text(encoding="utf-8"))
    feeds = document if isinstance(document, list) else [document]
    with conn:
        index = 0
        for feed in feeds:
            member_id = str(feed.get("member_id", "") or "").strip()
            try:
                feed_date = iso_date(feed.get("feed_date"), "%Y%m%d", required=True)
            except ValidationError:
                feed_date = None
            redemptions = feed.get("redemptions", [])
            if not isinstance(redemptions, list):
                redemptions = [redemptions]
            for item in redemptions:
                index += 1
                stats["seen"] += 1
                payload = {"member_id": member_id, "feed_date": feed.get("feed_date"), "item": item}
                digest = _hash(payload)
                cur = conn.execute("""INSERT OR IGNORE INTO raw_redemptions
                    (source_file,source_row,feed_date,raw_hash,payload_json)
                    VALUES (?,?,?,?,?)""",
                    (path.name, index, feed_date, digest, _json(payload)))
                if cur.rowcount == 0:
                    stats["unchanged"] += 1
                    continue
                try:
                    if not feed_date:
                        raise ValidationError("INVALID_FEED_DATE")
                    if not isinstance(item, dict):
                        raise ValidationError("INVALID_REDEMPTION_OBJECT")
                    record = normalize_redemption(member_id, feed_date, item)
                except ValidationError as exc:
                    _reject(conn, path.name, index, payload, str(exc))
                    stats["rejected"] += 1
                    continue
                existing = conn.execute("""SELECT * FROM redemption_transactions
                    WHERE member_key=? AND partner=? AND txn_id=?""",
                    (record["member_key"], record["partner"], record["txn_id"])).fetchone()
                if existing and existing["feed_date"] > feed_date:
                    stats["older"] += 1
                    continue
                if existing and existing["feed_date"] == feed_date:
                    keys = ("txn_date", "miles_redeemed", "status")
                    if all(existing[k] == record[k] for k in keys):
                        stats["unchanged"] += 1
                    else:
                        _reject(conn, path.name, index, payload, "CONFLICTING_REDEMPTION_SAME_FEED_DATE")
                        stats["rejected"] += 1
                    continue
                cols = ("member_key", "source_member_id", "partner", "txn_id", "txn_date",
                        "miles_redeemed", "status", "feed_date")
                conn.execute(f"INSERT INTO redemption_transactions ({','.join(cols)}) "
                             f"VALUES ({','.join('?' for _ in cols)}) "
                             "ON CONFLICT(member_key,partner,txn_id) DO UPDATE SET "
                             + ",".join(f"{k}=excluded.{k}" for k in cols if k not in
                                        ("member_key", "partner", "txn_id")),
                             tuple(record[k] for k in cols))
                stats["accepted"] += 1
    return stats


def report(conn: sqlite3.Connection) -> dict[str, Any]:
    def count(table: str) -> int:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return {
        "raw_member_rows": count("raw_members"),
        "staged_rows": count("staging_members"),
        "current_members": count("current_members"),
        "quarantined": count("rejected_records"),
        "redemptions": count("redemption_transactions"),
        "country_counts": {code: count(table) for code, table in COUNTRY_TABLES.items()},
        "redemptions_joined": [dict(row) for row in conn.execute("""
            SELECT r.member_key, m.member_name, m.country_code, r.partner,
                   r.txn_id, r.miles_redeemed, r.status
            FROM redemption_transactions r
            LEFT JOIN current_members m ON r.member_key = m.member_key
            ORDER BY r.txn_id
        """)],
        "rejection_reasons": [dict(row) for row in conn.execute("""
            SELECT source_file, source_row, reason FROM rejected_records
            ORDER BY source_file, source_row
        """)],
    }
