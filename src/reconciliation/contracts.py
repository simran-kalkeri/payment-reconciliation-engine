import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo("Asia/Kolkata")
SCHEMA_VERSION = 1
COMMON = ("id", "merchant", "account", "reference", "currency")
FIELDS = {
    "ledger": (*COMMON, "gross", "collection_date", "deadline_date"),
    "settlement": (*COMMON, "net", "fee", "settlement_date", "available_at"),
}
DATE_FORMATS = ("iso", "dmy", "named", "mixed")
CATEGORIES = ("missing_settlement", "duplicate_settlement", "amount_mismatch", "late_settlement",
              "reference_mismatch", "ambiguous_match", "unexpected_settlement", "data_quality")
MAX_MINOR = 10**15


class InvalidRow(ValueError):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code


def scope_id(value):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value):
        raise ValueError("Use 1–64 letters, digits, dots, underscores or hyphens for a source or scope")
    return value


def public_id(source, external_id):
    return f"{source}:{external_id}"


def amount(raw, field):
    if not re.fullmatch(r"[0-9]{1,14}(?:\.[0-9]{1,2})?", raw):
        raise InvalidRow("invalid_amount", f"{field} requires a nonnegative decimal with at most two decimal places")
    result = int(Decimal(raw) * 100)
    if result > MAX_MINOR:
        raise InvalidRow("amount_out_of_range", f"{field} exceeds the supported range")
    return result


def local_date(raw, date_format):
    if date_format in ("iso", "mixed") and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
        return date.fromisoformat(raw)
    if date_format in ("dmy", "mixed") and re.fullmatch(r"[0-9]{2}/[0-9]{2}/[0-9]{4}", raw):
        day, month, year = map(int, raw.split("/"))
        return date(year, month, day)
    if date_format in ("named", "mixed"):
        match = re.fullmatch(r"([0-9]{2})-([A-Z]{3})-([0-9]{4})", raw)
        months = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
        if match and match[2] in months:
            return date(int(match[3]), months.index(match[2]) + 1, int(match[1]))
    raise ValueError("Date does not use the declared format")


def timestamp(raw):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|[+-][0-9]{2}:[0-9]{2})", raw):
        raise ValueError("Use an ISO timestamp with seconds and an explicit UTC offset")
    return datetime.fromisoformat(raw).astimezone(UTC)


def local_start(value):
    return datetime.combine(value, time.min, tzinfo=BUSINESS_TZ).astimezone(UTC)


def normalize(kind, source, payload, date_format):
    if payload["extra"] or len(payload["cells"]) != len(FIELDS[kind]):
        raise InvalidRow("row_shape", "Row contains an unexpected number of columns")
    values = {key: value.strip() for key, value in payload["cells"].items() if isinstance(value, str)}
    for key in FIELDS[kind]:
        if (not values.get(key) or len(values[key]) > 256
                or not all(char.isprintable() or char == "\t" for char in values[key])):
            raise InvalidRow("invalid_field", f"{key} is required and must be printable and at most 256 characters")
    if values["currency"].upper() != "INR":
        raise InvalidRow("unsupported_currency", "The declared currency is unsupported; expected INR")
    normalized = dict(kind=kind, source=source, external_id=values["id"], merchant=values["merchant"],
                      account=values["account"], reference="".join(values["reference"].upper().split()),
                      currency="INR", net=None, fee=None, deadline_at=None, available_at=None)
    try:
        if kind == "ledger":
            day = local_date(values["collection_date"], date_format)
            deadline = local_date(values["deadline_date"], date_format)
            if deadline < day:
                raise ValueError("Deadline precedes collection")
            normalized.update(business_date=day, deadline_at=local_start(deadline + timedelta(days=1)),
                              gross=amount(values["gross"], "gross"))
        else:
            day = local_date(values["settlement_date"], date_format)
            arrival = timestamp(values["available_at"])
            if arrival.astimezone(BUSINESS_TZ).date() < day:
                raise ValueError("Arrival precedes settlement date")
            net, fee = amount(values["net"], "net"), amount(values["fee"], "fee")
            normalized.update(business_date=day, available_at=arrival, net=net, fee=fee, gross=net + fee)
    except InvalidRow:
        raise
    except (ValueError, OverflowError) as exc:
        raise InvalidRow("invalid_date", "Invalid date, timestamp, or chronological order for the declared contract") from exc
    if not 0 < normalized["gross"] <= MAX_MINOR:
        raise InvalidRow("amount_out_of_range", "Gross amount must be positive and within the supported range")
    return normalized
