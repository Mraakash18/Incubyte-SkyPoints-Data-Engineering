"""Print human-readable evidence for the live demo.

Run: python -m skypoints.inspect --db output/skypoints.db
"""
import argparse
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect the SkyPoints local database")
    parser.add_argument("--db", type=Path, default=Path("output/skypoints.db"))
    args = parser.parse_args()
    if not args.db.exists():
        parser.error(f"Database not found: {args.db}. Run the ETL first.")
    conn = sqlite3.connect(args.db)
    sections = [
        ("CURRENT MEMBERS", """SELECT member_key,member_name,country_code,age,stale_member
                               FROM current_members ORDER BY country_code,member_name"""),
        ("QUARANTINED RECORDS", """SELECT source_file,source_row,reason
                                    FROM rejected_records ORDER BY source_file,source_row"""),
        ("REDEMPTION JOIN", """SELECT r.txn_id,r.status,r.miles_redeemed,
                               m.member_name,m.country_code
                               FROM redemption_transactions r
                               LEFT JOIN current_members m ON r.member_key=m.member_key
                               ORDER BY r.txn_id"""),
        ("ELENA COUNTRY MOVE CHECK", """SELECT 'USA' AS target,COUNT(*) AS copies
                                     FROM country_usa WHERE member_key='GLOBAL:223457'
                                     UNION ALL SELECT 'IND',COUNT(*)
                                     FROM country_india WHERE member_key='GLOBAL:223457'"""),
    ]
    for title, query in sections:
        print("\n" + title)
        cur = conn.execute(query)
        print(" | ".join(col[0] for col in cur.description))
        for row in cur.fetchall():
            print(" | ".join("NULL" if val is None else str(val) for val in row))
    conn.close()


if __name__ == "__main__":
    main()
