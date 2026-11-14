import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from rapidfuzz.distance import DamerauLevenshtein

from .contracts import BUSINESS_TZ, local_start, public_id

MATCHER_VERSION = "1.0.0"


@dataclass(frozen=True)
class Rules:
    minimum_score: int = 88
    minimum_margin: int = 8
    date_window: int = 4
    grace_hours: int = 0

    def __post_init__(self):
        if (any(type(value) is not int for value in vars(self).values()) or
                not (1 <= self.minimum_score <= 100 and 1 <= self.minimum_margin <= 100 and
                     0 <= self.date_window <= 31 and 0 <= self.grace_hours <= 720)):
            raise ValueError("Invalid matcher rules")

    @classmethod
    def read(cls, path):
        return cls(**json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Payment:
    id: int
    kind: str
    source: str
    external_id: str
    merchant: str
    account: str
    reference: str
    currency: str
    gross: int
    business_date: date
    deadline_at: datetime | None = None
    available_at: datetime | None = None
    net: int | None = None
    fee: int | None = None

    @property
    def key(self):
        return public_id(self.source, self.external_id)

    @property
    def scope(self):
        return self.merchant, self.account, self.currency


def evidence(ledger, settlement, score):
    return dict(ledger=ledger.key, settlement=settlement.key, score=score,
                ledger_reference=ledger.reference, settlement_reference=settlement.reference,
                amount_difference=settlement.gross - ledger.gross,
                date_difference=(settlement.business_date - ledger.business_date).days)


def score_reference(left, right):
    distance = DamerauLevenshtein.distance(left, right)
    width = max(len(left), len(right))
    return ((width - distance) * 100) // width


def match(ledgers, settlements, rules, *, progress=None):
    """Prioritize exact evidence and require reciprocal confidence for fuzzy links."""
    ledgers = sorted(ledgers, key=lambda row: row.key)
    settlements = sorted(settlements, key=lambda row: row.key)
    by_reference, by_amount = defaultdict(list), defaultdict(list)
    for row in settlements:
        by_reference[(*row.scope, row.reference)].append(row)
        by_amount[(*row.scope, row.gross, row.business_date)].append(row)
    links, unresolved, duplicates = {}, {}, {}
    used, held, held_ledgers = set(), set(), set()

    def eligible(left, right):
        return 0 <= (right.business_date - left.business_date).days <= rules.date_window

    def accept(left, right, method, score, candidates, runner_up=None, reverse_runner_up=None):
        links[left] = right, method, {**evidence(left, right, score), "runner_up": runner_up,
                                     "reverse_runner_up": reverse_runner_up, "candidates": candidates,
                                     "reason": {"exact": "unique_exact_or_observed_original",
                                                "diagnostic": "unique_exact_reference_with_unequal_amount",
                                                "fuzzy": "reciprocal_top_score_and_margin"}[method]}
        used.add(right)

    for method in ("exact", "diagnostic"):
        if progress:
            progress(method)
        forward, reverse = {}, defaultdict(list)
        for left in ledgers:
            if left in links or left in held_ledgers:
                continue
            candidates = [right for right in by_reference[(*left.scope, left.reference)]
                          if eligible(left, right) and right not in used and right not in held
                          and (left.gross == right.gross) == (method == "exact")]
            if candidates:
                forward[left] = candidates
                for right in candidates:
                    reverse[right].append(left)
        for left, candidates in forward.items():
            items = [evidence(left, row, 100) for row in candidates]
            if all(len(reverse[row]) == 1 for row in candidates):
                if len(candidates) == 1:
                    accept(left, candidates[0], method, 100, items)
                    continue
                if method == "exact" and len({row.source for row in candidates}) == 1:
                    ordered = sorted(candidates, key=lambda row: (row.business_date, row.available_at))
                    first, second = ordered[:2]
                    if (first.business_date, first.available_at) != (second.business_date, second.available_at):
                        accept(left, first, method, 100, items, runner_up=100)
                        duplicates[left] = ordered[1:]
                        held.update(ordered[1:])
                        continue
            held_ledgers.add(left)
            held.update(candidates)
            unresolved[left] = {"reason": f"competing_{method}_claims", "candidates": items}

    if progress:
        progress("fuzzy")
    forward, reverse = defaultdict(list), defaultdict(list)
    for left in ledgers:
        if left in links or left in held_ledgers:
            continue
        for offset in range(rules.date_window + 1):
            for right in by_amount[(*left.scope, left.gross, left.business_date + timedelta(days=offset))]:
                if right in used or right in held:
                    continue
                score = score_reference(left.reference, right.reference)
                if score >= max(1, rules.minimum_score - rules.minimum_margin):
                    forward[left].append((score, right))
                    reverse[right].append((score, left))

    def rank(pairs):
        return sorted(pairs, key=lambda pair: (-pair[0], pair[1].key))

    for left, pairs in forward.items():
        ranked = rank(pairs)
        score, right = ranked[0]
        runner = ranked[1][0] if len(ranked) > 1 else None
        contenders = rank(reverse[right])
        reverse_runner = contenders[1][0] if len(contenders) > 1 else None
        items = [evidence(left, row, value) for value, row in ranked]
        reverse_items = [evidence(row, right, value) for value, row in contenders if row != left]
        if (score >= rules.minimum_score and (runner is None or score - runner >= rules.minimum_margin)
                and contenders[0][1] == left
                and (reverse_runner is None or score - reverse_runner >= rules.minimum_margin)):
            accept(left, right, "fuzzy", score, items + reverse_items, runner, reverse_runner)
        else:
            unresolved[left] = dict(reason="below_score_or_reciprocal_margin",
                                    candidates=items + reverse_items, runner_up=runner,
                                    reverse_runner_up=reverse_runner)
    return links, unresolved, duplicates


def classify(day, cutoff, ledgers, settlements, rules, *, progress=None):
    links, unresolved, duplicates = match(ledgers, settlements, rules, progress=progress)
    focal = [row for row in ledgers if row.business_date == day]
    owned = {right: left for left, (right, _, _) in links.items()}
    owned.update({right: left for left, rows in duplicates.items() for right in rows})
    contested = {item["settlement"] for data in unresolved.values() for item in data["candidates"]}
    scoped = [right for right in settlements
              if (owned[right].business_date if right in owned else right.business_date) == day]
    issues, pending = [], []

    def add(category, row, value, **details):
        issues.append(dict(category=category, subject=row.key, merchant=row.merchant, amount=value,
                           evidence={row.kind: row.key, **details}))

    for left in focal:
        deadline = left.deadline_at + timedelta(hours=rules.grace_hours)
        if left in links:
            right, method, proof = links[left]
            if method == "diagnostic":
                add("amount_mismatch", left, abs(proof["amount_difference"]), **proof)
            if method == "fuzzy":
                add("reference_mismatch", left, left.gross, **proof)
            if local_start(right.business_date) >= deadline:
                add("late_settlement", left, left.gross, **proof)
        elif left in unresolved:
            add("ambiguous_match", left, left.gross, **unresolved[left])
        elif cutoff >= deadline:
            add("missing_settlement", left, left.gross)
        else:
            pending.append(left)
        if left in duplicates:
            extras = duplicates[left]
            add("duplicate_settlement", left, sum(row.gross for row in extras),
                original=links[left][0].key, extras=[row.key for row in extras])
    for right in scoped:
        if right not in owned and right.key not in contested:
            add("unexpected_settlement", right, right.gross)
    return focal, scoped, {left: links[left] for left in focal if left in links}, issues, pending
