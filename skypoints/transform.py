"""Pure normalization and validation functions for member/redemption feeds."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

COUNTRIES = {"IND": "IND", "INDIA": "IND", "USA": "USA", "US": "USA",
             "AU": "AUS", "AUS": "AUS", "AUSTRALIA": "AUS",
             "CAN": "CAN", "CANADA": "CAN", "PHIL": "PHL", "PHL": "PHL"}
VALID_TIERS = {"SLV", "GLD", "PLT"}
VALID_STATUS = {"COMPLETED", "PENDING", "CANCELLED", "FAILED"}


class ValidationError(ValueError):
    pass


def iso_date(value: str | None, fmt: str, *, required: bool = False) -> str | None:
    value = (str(value or "")).strip()
    if value.upper() in {"", "NULL", "NONE", "N/A"}:
        if required:
            raise ValidationError("MISSING_REQUIRED_DATE")
        return None
    try:
        return datetime.strptime(value, fmt).date().isoformat()
    except ValueError as exc:
        raise ValidationError(f"INVALID_DATE:{value}") from exc


def usa_compact_date(value: str | None) -> str:
    """Accept only a unique M/D/YYYY interpretation, reject ambiguous 7 digits."""
    digits = str(value or "").strip()
    if not digits.isdigit() or len(digits) not in (6, 7, 8):
        raise ValidationError(f"INVALID_US_DATE:{digits}")
    year = int(digits[-4:])
    prefix = digits[:-4]
    matches = set()
    for month_width in (1, 2):
        day_width = len(prefix) - month_width
        if day_width not in (1, 2):
            continue
        month, day = int(prefix[:month_width]), int(prefix[month_width:])
        try:
            matches.add(date(year, month, day).isoformat())
        except ValueError:
            pass
    if not matches:
        raise ValidationError(f"INVALID_US_DATE:{digits}")
    if len(matches) > 1:
        raise ValidationError(f"AMBIGUOUS_US_DATE:{digits}")
    return matches.pop()


def age_on(dob: str | None, as_of: date) -> int | None:
    if not dob:
        return None
    born = date.fromisoformat(dob)
    return as_of.year - born.year - ((as_of.month, as_of.day) < (born.month, born.day))


def _required(raw: dict, key: str) -> str:
    value = str(raw.get(key, "") or "").strip()
    if not value or value.upper() == "NULL":
        raise ValidationError(f"MISSING_{key.upper().replace(' ', '_')}")
    return value


def normalize_member(raw: dict[str, str], source: str, as_of: date,
                     *, flat_dob_format: str = "%d%m%Y") -> dict[str, Any]:
    if raw.get("_parse_error"):
        raise ValidationError(str(raw["_parse_error"]))
    if source == "GLOBAL":
        member_id = _required(raw, "Member_Id")
        name = _required(raw, "Member_Name")
        enrollment = iso_date(raw.get("Enrollment_Date"), "%Y%m%d", required=True)
        flight = iso_date(raw.get("Last_Flight_Date"), "%Y%m%d")
        dob = iso_date(raw.get("DOB"), flat_dob_format)
        tier = str(raw.get("Tier_Code", "") or "").strip().upper() or None
        country_raw = _required(raw, "Country")
        member_type = None
        active = str(raw.get("Is_Active", "") or "").strip().upper() or None
        agent_name = str(raw.get("Agent_Name", "") or "").strip() or None
        state_code = str(raw.get("State", "") or "").strip() or None
        post_code = str(raw.get("Post_Code", "") or "").strip() or None
        namespace = "GLOBAL"
    elif source == "INDIA_LOCAL":
        member_id = _required(raw, "ID")
        name = _required(raw, "Name")
        enrollment = iso_date(raw.get("EnrollmentDate"), "%m/%d/%Y", required=True)
        flight = iso_date(raw.get("Flight Date"), "%m/%d/%Y")
        dob = iso_date(raw.get("DOB"), "%m/%d/%Y")
        tier = str(raw.get("TierCode", "") or "").strip().upper() or None
        country_raw = "IND"
        member_type = str(raw.get("Individual or Corporate", "") or "").strip().upper() or None
        active = None
        agent_name = state_code = post_code = None
        namespace = source
    elif source == "USA_LOCAL":
        member_id = _required(raw, "ID")
        name = _required(raw, "Name")
        enrollment = usa_compact_date(raw.get("EnrollmentDate"))
        flight = usa_compact_date(raw.get("FlightDate")) if raw.get("FlightDate") else None
        dob = None
        tier = str(raw.get("TierCode", "") or "").strip().upper() or None
        country_raw = "USA"
        member_type = None
        active = None
        agent_name = state_code = post_code = None
        namespace = source
    elif source == "AUSTRALIA_LOCAL":
        member_id = _required(raw, "Unique ID")
        name = _required(raw, "Member Name")
        enrollment = iso_date(raw.get("Date of Enrollment"), "%Y-%m-%d", required=True)
        flight = iso_date(raw.get("Date of Flight"), "%Y-%m-%d")
        dob = iso_date(raw.get("Date of Birth"), "%Y-%m-%d")
        tier = str(raw.get("Tier Type", "") or "").strip().upper() or None
        country_raw = "AUS"
        member_type = None
        active = None
        agent_name = state_code = post_code = None
        namespace = source
    else:
        raise ValidationError(f"UNKNOWN_SOURCE:{source}")
    if len(member_id) > 18:
        raise ValidationError("MEMBER_ID_TOO_LONG")
    if len(name) > 255:
        raise ValidationError("MEMBER_NAME_TOO_LONG")
    if tier is not None and tier not in VALID_TIERS:
        raise ValidationError(f"UNKNOWN_TIER:{tier}")
    if member_type not in (None, "I", "C"):
        raise ValidationError("INVALID_MEMBER_TYPE")
    if active not in (None, "A", "I"):
        raise ValidationError("INVALID_ACTIVE_FLAG")
    country = COUNTRIES.get(country_raw.upper())
    if country is None:
        raise ValidationError(f"UNKNOWN_COUNTRY:{country_raw}")
    if dob and date.fromisoformat(dob) > as_of:
        raise ValidationError("DOB_IN_FUTURE")
    if dob and dob > enrollment:
        raise ValidationError("DOB_AFTER_ENROLLMENT")
    if flight and flight < enrollment:
        raise ValidationError("FLIGHT_BEFORE_ENROLLMENT")
    if flight and date.fromisoformat(flight) > as_of:
        raise ValidationError("FLIGHT_IN_FUTURE")
    return {"member_key": f"{namespace}:{member_id}", "source_member_id": member_id,
            "source_namespace": namespace, "member_name": name, "tier_code": tier,
            "enrollment_date": enrollment, "last_flight_date": flight,
            "dob": dob, "country_code": country, "member_type": member_type,
            "is_active": active, "agent_name": agent_name, "state_code": state_code,
            "post_code": post_code, "age": age_on(dob, as_of),
            "stale_member": (int((as_of - date.fromisoformat(flight)).days > 90) if flight else None),
            "as_of_date": as_of.isoformat()}


def normalize_redemption(member_id: str, feed_date: str, item: dict) -> dict[str, Any]:
    if not member_id:
        raise ValidationError("MISSING_MEMBER_ID")
    txn_id = _required(item, "txn_id")
    partner = _required(item, "partner")
    txn_date = iso_date(item.get("txn_date"), "%Y%m%d", required=True)
    if txn_date > feed_date:
        raise ValidationError("TRANSACTION_AFTER_FEED_DATE")
    try:
        miles = int(item.get("miles_redeemed"))
        if isinstance(item.get("miles_redeemed"), bool):
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise ValidationError("INVALID_MILES") from exc
    if miles <= 0:
        raise ValidationError("NON_POSITIVE_MILES")
    status = _required(item, "status").upper()
    if status not in VALID_STATUS:
        raise ValidationError("INVALID_REDEMPTION_STATUS")
    return {"member_key": f"GLOBAL:{member_id}", "source_member_id": member_id,
            "txn_id": txn_id, "txn_date": txn_date, "partner": partner,
            "miles_redeemed": miles, "status": status, "feed_date": feed_date}
