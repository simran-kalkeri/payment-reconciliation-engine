import csv
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .contracts import BUSINESS_TZ, FIELDS, SCHEMA_VERSION, local_start, public_id
from .reporting import json_file
from .storage import file_hash

DEV_SEED = 4242
EVAL_SEED = 90125
FIRST_DAY = date(2025, 5, 12)
LEDGER_SOURCE = "ledger-office"
SETTLEMENT_SOURCE = "upi-bank"
SEEDED = ("missing_settlement", "duplicate_settlement", "amount_mismatch",
          "late_settlement", "reference_mismatch")
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PAYMENT_PROFILES = (
    ((5900, 9900, 14900, 24900, 39900), 2500, 75000),
    ((19900, 34900, 49900, 79900, 129900), 9000, 300000),
    ((49900, 99900, 149900, 249900, 399900), 25000, 900000),
)
SETTLEMENT_BATCHES = ((8, 30), (10, 15), (11, 30), (13, 0), (16, 30))


def money(minor):
    return f"{minor // 100}.{minor % 100:02d}"


def timestamp(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), tzinfo=BUSINESS_TZ).isoformat()


def typical_amount(rng, merchant):
    prices, minimum, maximum = PAYMENT_PROFILES[(merchant - 1) % len(PAYMENT_PROFILES)]
    if rng.randrange(10) < 7:
        return rng.choice(prices)
    return rng.randrange(minimum, maximum)


def provider_fee(gross, merchant):
    basis_points = (0, 0, 15, 25, 40)[(merchant - 1) % 5]
    return (gross * basis_points + 5000) // 10000


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def format_day(value, layout):
    months = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
    if layout == "named":
        return f"{value.day:02d}-{months[value.month - 1]}-{value.year}"
    if layout == "dmy":
        return f"{value.day:02d}/{value.month:02d}/{value.year}"
    return value.isoformat()


def generate(inputs, truth_dir, seed, count=12400, per_category=140, *, two_files=False,
             merchant_profiles=False):
    inputs, truth_dir = Path(inputs), Path(truth_dir)
    if (inputs.resolve() == truth_dir.resolve() or inputs.resolve() in truth_dir.resolve().parents
            or truth_dir.resolve() in inputs.resolve().parents):
        raise ValueError("Use separate sibling directories for inputs and evaluation truth")
    if per_category < 1 or count < per_category * len(SEEDED) + 36:
        raise ValueError("Dataset is too small for the requested error counts")
    inputs.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    ledger, settlement, truths, invalid, unexpected, ambiguous = [], [], [], [], [], []
    slots = rng.sample(range(count), per_category * len(SEEDED) + 36)
    anomalies = {index: [label] for offset, label in enumerate(SEEDED)
                 for index in slots[offset * per_category:(offset + 1) * per_category]}
    overlap = slots[per_category * len(SEEDED):]
    for index in overlap[:24]:
        anomalies[index] = ["late_settlement", "reference_mismatch" if index % 2 else "amount_mismatch"]

    def opaque_id():
        return f"{rng.getrandbits(96):024x}"

    def reference():
        return "".join(rng.choices(ALPHABET, k=16))

    def settlement_row(common, ref, amount, fee, day, arrival_hour=11, arrival_minute=0):
        return dict(id=opaque_id(), **common, reference=ref, net=money(amount - fee), fee=money(fee),
                    settlement_date=day.isoformat(), available_at=timestamp(day, arrival_hour, arrival_minute))

    for index in range(count):
        day_offset = rng.choices(range(3), (29, 34, 37))[0] if merchant_profiles else index % 3
        day = FIRST_DAY + timedelta(days=day_offset)
        deadline = day + timedelta(days=1)
        ref = reference()
        merchant = rng.randrange(1, 41)
        common = dict(merchant=f"merchant-{merchant:02d}", account=f"account-{rng.randrange(1, 4)}",
                      currency="INR")
        if merchant_profiles:
            gross = typical_amount(rng, merchant)
        elif index % 3:
            gross = rng.choice([9900, 14900, 19900, 24900, 49900, 99900])
        else:
            gross = rng.randrange(2500, 900000)
        if index in overlap[24:]:
            merchant = 41
            common.update(merchant="merchant-41", account=f"account-{overlap.index(index)}")
        left = dict(id=opaque_id(), **common, reference=f"  {ref.lower()}  " if index % 7 == 0 else ref,
                    gross=money(gross), collection_date=day.isoformat(), deadline_date=deadline.isoformat())
        ledger.append(left)
        labels = anomalies.get(index, [])
        truth = dict(ledger=public_id(LEDGER_SOURCE, left["id"]), business_date=day.isoformat(),
                     deadline=local_start(deadline + timedelta(days=1)).isoformat(), labels=labels,
                     settlement=None, available_at=None, extras=[])
        truths.append(truth)
        if "missing_settlement" in labels:
            continue
        settle_day = deadline + timedelta(days=int("late_settlement" in labels))
        if "reference_mismatch" in labels:
            if index % 11 == 0:
                ref = ref[:-3]
            elif index % 3 == 0:
                ref = ref[:-1]
            else:
                pos = rng.randrange(len(ref))
                ref = ref[:pos] + rng.choice(ALPHABET.replace(ref[pos], "")) + ref[pos + 1:]
        if "amount_mismatch" in labels:
            gross += rng.choice((100, 199, 500, -100))
        hour, minute, duplicate_hour = 11, 0, 14
        if merchant_profiles:
            fee = provider_fee(gross, merchant)
            hour, minute = SETTLEMENT_BATCHES[(merchant - 1) % len(SETTLEMENT_BATCHES)]
            minute += rng.randrange(20)
            duplicate_hour = hour + 2
        else:
            fee = min(gross // 10, rng.choice((0, 0, 15, 35, 75, 140)))
        if index in overlap[24:]:
            # Equal reference distance from the true and competing ledger entries.
            clone = dict(left, id=opaque_id(), reference="B" + ref[1:])
            left["reference"] = "A" + ref[1:]
            ref = "C" + ref[1:]
            ledger.append(clone)
            ambiguous.extend(public_id(LEDGER_SOURCE, row["id"]) for row in (left, clone))
            truths.append(dict(truth, ledger=public_id(LEDGER_SOURCE, clone["id"]),
                               labels=["missing_settlement"]))
            truth["labels"] = ["reference_mismatch"]
        right = settlement_row(common, ref.lower() if index % 5 == 0 else ref, gross, fee, settle_day, hour, minute)
        settlement.append(right)
        truth.update(settlement=public_id(SETTLEMENT_SOURCE, right["id"]), available_at=right["available_at"],
                     settlement_day_start=local_start(settle_day).isoformat())
        if "duplicate_settlement" in labels:
            extra = settlement_row(common, ref, gross, fee, settle_day, duplicate_hour, minute)
            settlement.append(extra)
            truth["extras"].append(dict(settlement=public_id(SETTLEMENT_SOURCE, extra["id"]),
                                        available_at=extra["available_at"]))

    for _ in range(24):
        common = dict(merchant="merchant-42", account="account-1", currency="INR")
        day = FIRST_DAY + timedelta(days=rng.randrange(3))
        right = settlement_row(common, reference(), 14900, 20, day)
        settlement.append(right)
        unexpected.append(dict(settlement=public_id(SETTLEMENT_SOURCE, right["id"]),
                               business_date=day.isoformat(), available_at=right["available_at"]))

    for rows, source, mutations in (
        (ledger, LEDGER_SOURCE, (("gross", "not-a-number"), ("merchant", ""), ("collection_date", "2025-02-30"),
                                 ("currency", "USD"))),
        (settlement, SETTLEMENT_SOURCE, (("fee", "1.234"), ("reference", ""), ("available_at", "yesterday"),
                                         ("currency", "EUR"))),
    ):
        for field, bad in mutations:
            malformed = dict(rows[0], id=opaque_id(), **{field: bad})
            rows.append(malformed)
            invalid.append(dict(source=source, id=malformed["id"], invalid_field=field))

    rng.shuffle(ledger)
    rng.shuffle(settlement)
    invalid_ids = {item["id"] for item in invalid}
    files = []
    for kind, source, rows, date_format, columns, basename in (
        ("ledger", LEDGER_SOURCE, ledger, "named", ("collection_date", "deadline_date"), "ledger"),
        ("settlement", SETTLEMENT_SOURCE, settlement, "dmy", ("settlement_date",), "settlements"),
    ):
        if two_files:
            layout = "iso"
            if kind == "settlement":
                layout = "mixed"
                for index, row in enumerate(rows):
                    if row["id"] in invalid_ids:
                        continue
                    if index % 5 < 2:
                        day = date.fromisoformat(row["settlement_date"])
                        row["settlement_date"] = format_day(day, ("dmy", "named")[index % 5])
                    if index % 7 == 0:
                        row["reference"] = f"  {row['reference']}  "
            outputs = [(f"{basename}.csv", rows, layout)]
        else:
            alternate = [row for row in rows if row["id"] not in invalid_ids][:20]
            selected = {row["id"] for row in alternate}
            for row in alternate:
                for key in columns:
                    row[key] = format_day(date.fromisoformat(row[key]), date_format)
            main = [row for row in rows if row["id"] not in selected]
            outputs = [(f"{basename}.csv", main, "iso"), (f"{basename}-{date_format}.csv", alternate, date_format)]
        for name, subset, layout in outputs:
            path = inputs / name
            write_csv(path, FIELDS[kind], subset)
            files.append(dict(name=name, kind=kind, source=source, date_format=layout,
                              rows=len(subset), sha256=file_hash(path)))

    cutoff = local_start(FIRST_DAY + timedelta(days=6)).isoformat()
    dates = [(FIRST_DAY + timedelta(days=offset)).isoformat() for offset in range(3)]
    configuration = dict(ledger_count=count, isolated_cases_per_category=per_category)
    if merchant_profiles:
        configuration["merchant_profiles"] = True
    manifest = dict(seed=seed, schema_version=SCHEMA_VERSION, business_dates=dates, final_cutoff=cutoff,
                    configuration=configuration, files=files)
    json_file(inputs / "manifest.json", manifest)
    answer = dict(seed=seed, schema_version=SCHEMA_VERSION, rows=truths, invalid_rows=invalid, unexpected=unexpected,
                  deliberate_ambiguity=sorted(ambiguous), files=files, business_dates=dates, final_cutoff=cutoff)
    json_file(truth_dir / "answer_key.json", answer)
    return manifest
