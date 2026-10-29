"""Split a pasted SMS dump into messages and parse them with data-driven patterns.

Nothing in this module touches the database: patterns come in as plain dicts
(see `load_patterns` in `importer.py`), so the parsing rules can be unit tested
in isolation.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

NOISE = "noise"
PARSED = "parsed"
ERROR = "error"

PATTERN_GROUPS = (
	"date",
	"merchant",
	"counterparty",
	"account",
	"currency",
	"amount",
	"sign",
	"balance_currency",
	"balance",
	"reference",
	"time",
)

# Phone UI timestamps between messages, e.g. " Monday, Oct 12 · 5:31 PM", " Sunday · 12:03 PM", " 7:02 AM"
TIMESTAMP_LINE = re.compile(
	r"^(?:[A-Za-z]+,?\s*)?(?:[A-Za-z]{3,9}\.?\s+\d{1,2}(?:,\s*\d{4})?\s*)?(?:·\s*)?\d{1,2}:\d{2}\s*(?:[AP]\.?M\.?)?$",
	re.IGNORECASE,
)


@dataclass
class CompiledPattern:
	name: str
	bank: str
	regex: re.Pattern
	start_marker: str | None
	date_format: str | None
	direction_rule: str | None
	is_noise: bool
	priority: int


@dataclass
class ParsedMessage:
	kind: str
	raw: str
	bank: str | None = None
	pattern: str | None = None
	error: str | None = None
	account: str | None = None
	date: object = None
	time: str | None = None
	direction: str | None = None
	currency: str | None = None
	amount: float | None = None
	merchant: str | None = None
	counterparty: str | None = None
	reference: str | None = None
	balance_currency: str | None = None
	balance: float | None = None


def compile_patterns(patterns):
	"""Turn pattern dicts (SMS Pattern rows) into CompiledPattern objects, sorted by priority."""
	compiled = []
	for p in patterns:
		compiled.append(
			CompiledPattern(
				name=p["name"],
				bank=p.get("bank"),
				regex=re.compile(p["regex"]),
				start_marker=(p.get("start_marker") or "").strip() or None,
				date_format=(p.get("date_format") or "").strip() or None,
				direction_rule=p.get("direction_rule"),
				is_noise=bool(p.get("is_noise")),
				priority=int(p.get("priority") or 0),
			)
		)
	return sorted(compiled, key=lambda p: (p.priority, p.name))


def parse_text(raw_text, patterns, bank=None):
	"""Parse a pasted SMS dump. Returns ParsedMessage objects in the order they appear.

	`patterns` are the SMS Pattern dicts for one bank. Steps:
	1. drop blank lines and phone timestamp lines,
	2. drop lines that are noise on their own (noise patterns without a start marker),
	3. split what is left on start markers, so a message wrapped over several lines stays one message,
	4. parse each message with the first pattern (by priority) whose regex matches it.
	"""
	compiled = compile_patterns(patterns)
	line_noise = [p for p in compiled if p.is_noise and not p.start_marker]
	markers = [p.start_marker for p in compiled if p.start_marker]

	results = []
	block = []

	def flush():
		for segment in split_on_markers("\n".join(block), markers):
			results.append(parse_message(segment, compiled, bank))
		block.clear()

	for line in (raw_text or "").splitlines():
		line = line.strip()
		if not line or TIMESTAMP_LINE.match(line):
			continue
		if any(p.regex.search(line) for p in line_noise):
			flush()
			results.append(ParsedMessage(kind=NOISE, raw=line, bank=bank))
			continue
		block.append(line)
	flush()

	return results


def split_on_markers(text, markers):
	"""Split text at every occurrence of a start marker. Text before the first marker is its own segment."""
	if not text.strip():
		return []
	if not markers:
		return [normalize_space(text)]

	marker_re = re.compile("|".join(re.escape(m) for m in sorted(set(markers), key=len, reverse=True)))
	starts = [m.start() for m in marker_re.finditer(text)]
	if not starts or starts[0] != 0:
		starts.insert(0, 0)
	starts.append(len(text))

	segments = (normalize_space(text[a:b]) for a, b in zip(starts, starts[1:], strict=False))
	return [s for s in segments if s]


def parse_message(text, compiled, bank=None):
	for pattern in compiled:
		match = pattern.regex.search(text)
		if not match:
			continue
		if pattern.is_noise:
			return ParsedMessage(kind=NOISE, raw=text, bank=bank, pattern=pattern.name)
		try:
			return build_parsed(text, pattern, match.groupdict(), bank or pattern.bank)
		except ValueError as e:
			return ParsedMessage(kind=ERROR, raw=text, bank=bank, pattern=pattern.name, error=str(e))

	return ParsedMessage(kind=ERROR, raw=text, bank=bank, error="No SMS Pattern matched this message")


def build_parsed(text, pattern, groups, bank):
	g = {k: (v or "").strip() or None for k, v in groups.items()}

	if not g.get("amount"):
		raise ValueError(f"Pattern {pattern.name} did not capture an amount")
	if not g.get("date"):
		raise ValueError(f"Pattern {pattern.name} did not capture a date")
	try:
		date = datetime.strptime(g["date"], pattern.date_format).date()
	except (TypeError, ValueError):
		raise ValueError(f"Date {g['date']!r} does not match format {pattern.date_format!r}") from None

	return ParsedMessage(
		kind=PARSED,
		raw=text,
		bank=bank,
		pattern=pattern.name,
		account=normalize_account(g.get("account")),
		date=date,
		time=normalize_time(g.get("time")),
		direction=get_direction(pattern, g.get("sign")),
		currency=(g.get("currency") or "").upper() or None,
		amount=to_amount(g["amount"]),
		merchant=g.get("merchant"),
		counterparty=g.get("counterparty"),
		reference=g.get("reference"),
		balance_currency=(g.get("balance_currency") or "").upper() or None,
		balance=to_amount(g["balance"]) if g.get("balance") else None,
	)


def get_direction(pattern, sign):
	if pattern.direction_rule in ("Debit", "Credit"):
		return pattern.direction_rule
	if sign == "-":
		return "Debit"
	if sign == "+":
		return "Credit"
	raise ValueError(f"Pattern {pattern.name} takes direction from the sign but no sign was captured")


def to_amount(value):
	cleaned = re.sub(r"[,\s]", "", value)
	try:
		return float(cleaned)
	except ValueError:
		raise ValueError(f"Cannot read amount {value!r}") from None


def normalize_account(value):
	"""Keep the trailing digits of a masked account, e.g. 071-014***-111 -> 111, ********8013 -> 8013."""
	if not value:
		return None
	match = re.search(r"(\d+)\D*$", value)
	return match.group(1) if match else value


def normalize_time(value):
	if not value:
		return None
	hours, minutes = value.split(":")[:2]
	return f"{int(hours):02d}:{int(minutes):02d}:00"


def normalize_space(text):
	return " ".join(text.split())


def dedup_hash(parsed, salt=""):
	"""Fingerprint of a real-world transaction.

	The balance is part of the key: two identical charges on the same day leave different balances,
	so they stay two transactions, while the same SMS pasted twice produces the same hash.
	Unparseable messages are fingerprinted by their text so re-pasting them doesn't pile up errors.
	"""
	if parsed.kind == ERROR:
		parts = ["ERROR", parsed.bank or "", normalize_space(parsed.raw).upper()]
	else:
		parts = [
			parsed.bank or "",
			parsed.date.isoformat() if parsed.date else "",
			parsed.time or "",
			parsed.currency or "",
			f"{parsed.amount:.2f}",
			parsed.direction or "",
			normalize_space(parsed.merchant or "").upper(),
			normalize_space(parsed.counterparty or "").upper(),
			(parsed.reference or "").upper(),
			f"{parsed.balance:.2f}" if parsed.balance is not None else "",
		]
	return hashlib.sha256((salt + "|".join(parts)).encode()).hexdigest()
