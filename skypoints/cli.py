"""Run: python -m skypoints.cli --db output/skypoints.db --as-of 2026-11-20"""
from __future__ import annotations
import argparse
from datetime import date
import json
from pathlib import Path

from .pipeline import connect, load_members, load_redemptions, report


def main() -> None:
    parser = argparse.ArgumentParser(description="SkyPoints reproducible ETL demo")
    parser.add_argument("--db", type=Path, default=Path("output/skypoints.db"))
    parser.add_argument("--input-dir", type=Path, default=Path("data/input"))
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 11, 20))
    parser.add_argument("--local-feed-date", type=date.fromisoformat, default=date(2024, 1, 15))
    parser.add_argument("--move-demo", action="store_true",
                        help="Apply explicitly synthetic Jan 16 global member country move")
    args = parser.parse_args()
    conn = connect(args.db)
    inputs = [
        ("member_profiles_20240115.txt", "GLOBAL", date(2024, 1, 15)),
        ("australia.xlsx", "AUSTRALIA_LOCAL", args.local_feed_date),
        ("usa.csv", "USA_LOCAL", args.local_feed_date),
        ("india.csv", "INDIA_LOCAL", args.local_feed_date),
    ]
    for name, source, feed_date in inputs:
        path = args.input_dir / name
        print(f"{name}: {load_members(conn, path, source, feed_date, args.as_of)}")
    json_path = args.input_dir / "redemptions_20240115.json"
    print(f"{json_path.name}: {load_redemptions(conn, json_path)}")
    if args.move_demo:
        move = Path("data/demo/member_profiles_20240116.txt")
        print(f"SYNTHETIC MOVE {move.name}: "
              f"{load_members(conn, move, 'GLOBAL', date(2024,1,16), args.as_of)}")
    print(json.dumps(report(conn), indent=2))
    conn.close()


if __name__ == "__main__":
    main()
