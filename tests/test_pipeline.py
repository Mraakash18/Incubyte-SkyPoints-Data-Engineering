"""Regression tests: execute with `python -m pytest -q`."""
import json
from datetime import date
from pathlib import Path

import pytest

from skypoints.ingest import read_xlsx
from skypoints.pipeline import connect, load_members, load_redemptions, report
from skypoints.transform import (ValidationError, age_on, normalize_member,
                                 normalize_redemption, usa_compact_date)

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "input"
AS_OF = date(2026, 11, 20)
FEED = date(2024, 1, 15)


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    yield conn
    conn.close()


def load_all(db):
    load_members(db, INPUT / "member_profiles_20240115.txt", "GLOBAL", FEED, AS_OF)
    load_members(db, INPUT / "australia.xlsx", "AUSTRALIA_LOCAL", FEED, AS_OF)
    load_members(db, INPUT / "usa.csv", "USA_LOCAL", FEED, AS_OF)
    load_members(db, INPUT / "india.csv", "INDIA_LOCAL", FEED, AS_OF)
    load_redemptions(db, INPUT / "redemptions_20240115.json")


def test_xlsx_read_and_invalid_date_preserved():
    rows = list(read_xlsx(INPUT / "australia.xlsx"))
    assert len(rows) == 3
    assert rows[1]["Member Name"] == "Jonnathan"
    assert rows[1]["Date of Enrollment"] == "2021-13-13"


def test_usa_date_parser_rejects_ambiguous_dates():
    assert usa_compact_date("6152022") == "2022-06-15"
    assert usa_compact_date("8202022") == "2022-08-20"
    assert usa_compact_date("12282021") == "2021-12-28"
    with pytest.raises(ValidationError, match="AMBIGUOUS_US_DATE"):
        usa_compact_date("1052022")
    with pytest.raises(ValidationError, match="AMBIGUOUS_US_DATE"):
        usa_compact_date("1152022")


def test_age_and_stale_member():
    assert age_on("1998-12-01", AS_OF) == 27
    assert age_on("1982-08-13", AS_OF) == 44
    assert age_on(None, AS_OF) is None
    row = normalize_member({"ID": "1", "Name": "Vikas", "DOB": "12/1/1998",
        "TierCode": "SLV", "EnrollmentDate": "1/1/2022",
        "Individual or Corporate": "I", "Flight Date": "6/15/2022"},
        "INDIA_LOCAL", AS_OF)
    assert row["stale_member"] == 1
    assert row["age"] == 27
    assert row["member_type"] == "I" and row["is_active"] is None


def test_all_samples_and_rejection_reasons(db):
    load_all(db)
    result = report(db)
    assert result["raw_member_rows"] == 14
    assert result["staged_rows"] == 12
    assert result["current_members"] == 12
    assert result["quarantined"] == 2
    assert result["redemptions"] == 2
    assert result["country_counts"] == {"IND": 4, "USA": 3, "AUS": 3, "PHL": 1, "CAN": 1}
    reasons = {x["reason"] for x in result["rejection_reasons"]}
    assert "INVALID_DATE:2021-13-13" in reasons
    assert "AMBIGUOUS_US_DATE:1052022" in reasons


def test_local_ids_do_not_collapse_different_members(db):
    load_all(db)
    rows = db.execute("SELECT member_key,member_name FROM current_members "
                      "WHERE source_member_id='1' ORDER BY member_key").fetchall()
    assert [(r[0], r[1]) for r in rows] == [
        ("AUSTRALIA_LOCAL:1", "Mike"), ("INDIA_LOCAL:1", "Vikas"),
        ("USA_LOCAL:1", "Sam")]


def test_country_move_is_atomic_and_idempotent(db):
    load_all(db)
    moved = ROOT / "data" / "demo" / "member_profiles_20240116.txt"
    first = load_members(db, moved, "GLOBAL", date(2024, 1, 16), AS_OF)
    assert first["accepted"] == 1
    assert db.execute("SELECT country_code FROM current_members WHERE member_key='GLOBAL:223457'").fetchone()[0] == "IND"
    assert db.execute("SELECT COUNT(*) FROM country_usa WHERE member_key='GLOBAL:223457'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM country_india WHERE member_key='GLOBAL:223457'").fetchone()[0] == 1
    second = load_members(db, moved, "GLOBAL", date(2024, 1, 16), AS_OF)
    assert second["accepted"] == 0 and second["unchanged"] == 1
    assert report(db)["current_members"] == 12


def test_older_feed_does_not_overwrite_newer(db, tmp_path):
    load_all(db)
    moved = ROOT / "data" / "demo" / "member_profiles_20240116.txt"
    load_members(db, moved, "GLOBAL", date(2024, 1, 16), AS_OF)
    old = tmp_path / "older_20240114.txt"
    old.write_text("|H|Member_Name|Member_Id|Enrollment_Date|Last_Flight_Date|Tier_Code|Agent_Name|State|Country|DOB|Is_Active\n"
                   "|D|Elena|223457|20101012|20121013|GLD|Sam|CA|CAN|03051985|A\n")
    result = load_members(db, old, "GLOBAL", date(2024, 1, 14), AS_OF)
    assert result["older"] == 1
    assert db.execute("SELECT country_code FROM current_members WHERE member_key='GLOBAL:223457'").fetchone()[0] == "IND"


def test_conflicting_same_date_is_quarantined(db, tmp_path):
    load_all(db)
    conflict = tmp_path / "same_day_conflict.txt"
    conflict.write_text("|H|Member_Name|Member_Id|Enrollment_Date|Last_Flight_Date|Tier_Code|Agent_Name|State|Country|DOB|Is_Active\n"
                        "|D|Elena|223457|20101012|20121013|GLD|Sam|CA|CAN|03051985|A\n")
    result = load_members(db, conflict, "GLOBAL", FEED, AS_OF)
    assert result["rejected"] == 1
    assert db.execute("SELECT country_code FROM current_members WHERE member_key='GLOBAL:223457'").fetchone()[0] == "USA"
    assert db.execute("SELECT COUNT(*) FROM rejected_records WHERE reason='CONFLICTING_SAME_FEED_DATE'").fetchone()[0] == 1


def test_json_join_to_verified_global_member(db):
    load_all(db)
    result = report(db)
    assert len(result["redemptions_joined"]) == 2
    assert all(x["member_name"] == "Elena" for x in result["redemptions_joined"])
    assert {x["status"] for x in result["redemptions_joined"]} == {"PENDING", "COMPLETED"}


def test_bad_redemption_is_quarantined(db, tmp_path):
    bad = tmp_path / "bad_redemption.json"
    bad.write_text(json.dumps({"member_id":"223457", "feed_date":"20240115", "redemptions":[
        {"txn_id":"BAD", "txn_date":"20240110", "partner":"AeroLink",
         "miles_redeemed":-5, "status":"COMPLETED"}]}))
    result = load_redemptions(db, bad)
    assert result["rejected"] == 1
    assert db.execute("SELECT reason FROM rejected_records").fetchone()[0] == "NON_POSITIVE_MILES"


def test_missing_dob_is_allowed_and_stale_unknown_when_no_flight():
    row = normalize_member({"Unique ID":"8", "Member Name":"NoFlight", "Tier Type":"SLV",
         "Date of Birth":"NULL", "Date of Enrollment":"2022-01-01",
         "Date of Flight":""}, "AUSTRALIA_LOCAL", AS_OF)
    assert row["age"] is None
    assert row["stale_member"] is None


def test_global_dob_format_is_documented_assumption():
    row = normalize_member({"Member_Id":"123", "Member_Name":"Test", "Enrollment_Date":"20101012",
         "Last_Flight_Date":"20121013", "Country":"PHIL", "DOB":"03051985"},
         "GLOBAL", AS_OF)
    assert row["dob"] == "1985-05-03"
    assert row["country_code"] == "PHL"


def test_duplicate_redemption_file_is_idempotent(db):
    path = INPUT / "redemptions_20240115.json"
    assert load_redemptions(db, path)["accepted"] == 2
    again = load_redemptions(db, path)
    assert again["accepted"] == 0 and again["unchanged"] == 2
    assert db.execute("SELECT COUNT(*) FROM redemption_transactions").fetchone()[0] == 2


def test_malformed_flat_record_is_quarantined_without_stopping_batch(db, tmp_path):
    bad = tmp_path / "mixed_flat.txt"
    bad.write_text("|H|Member_Name|Member_Id|Enrollment_Date|Last_Flight_Date|Tier_Code|Agent_Name|State|Country|DOB|Is_Active\n"
                   "|D|Broken|123|20101012\n"
                   "|D|Valid|124|20101012|20121013|GLD|Sam|CA|USA|03051985|A\n")
    result = load_members(db, bad, "GLOBAL", FEED, AS_OF)
    assert result["accepted"] == 1 and result["rejected"] == 1
    assert db.execute("SELECT reason FROM rejected_records").fetchone()[0] == "MALFORMED_FLAT_RECORD"
