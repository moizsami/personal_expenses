"""Turn an SMS Import into SMS Transactions and, for matched ones, into entries."""

import frappe
from frappe import _
from frappe.utils import now_datetime, strip_html

from personal_expenses.sms_parser.matcher import find_account_row, load_rules, match_rule, render_description
from personal_expenses.sms_parser.parser import ERROR, NOISE, dedup_hash, parse_text

DECISION_FIELDS = (
	"is_company_expense",
	"personal_category",
	"company",
	"entry_type",
	"expense_account",
	"supplier",
	"item",
	"cost_center",
)


def load_patterns(bank):
	return frappe.get_all(
		"SMS Pattern",
		filters={"enabled": 1, "bank": bank},
		fields=["name", "bank", "regex", "start_marker", "date_format", "direction_rule", "is_noise", "priority"],
	)


def run_import(import_doc):
	settings = frappe.get_single("SMS Parser Settings")
	patterns = load_patterns(import_doc.bank)
	if not any(not p.is_noise for p in patterns):
		frappe.throw(_("There is no enabled SMS Pattern for bank {0}").format(import_doc.bank))

	rules = load_rules()
	salt = frappe.flags.sms_parser_hash_salt or ""
	seen = {}
	new_txns = []
	import_doc.set("results", [])

	for parsed in parse_text(import_doc.raw_text, patterns, import_doc.bank):
		if parsed.kind == NOISE:
			import_doc.append("results", {"outcome": "Noise", "raw_message": parsed.raw})
			continue

		row = {
			"transaction_date": parsed.date,
			"currency": parsed.currency,
			"amount": parsed.amount,
			"description": (parsed.merchant or parsed.counterparty or parsed.error or "")[:140],
			"raw_message": parsed.raw,
		}
		fingerprint = dedup_hash(parsed, salt)
		existing = seen.get(fingerprint) or frappe.db.get_value(
			"SMS Transaction", {"dedup_hash": fingerprint}, "name"
		)
		if existing:
			import_doc.append("results", {**row, "outcome": "Duplicate", "sms_transaction": existing})
			continue

		txn = new_transaction(parsed, fingerprint, import_doc, settings, rules)
		savepoint = new_savepoint()
		try:
			txn.insert()
		except Exception as e:
			frappe.db.rollback(save_point=savepoint)
			frappe.clear_last_message()
			import_doc.append("results", {**row, "outcome": "Error", "description": error_text(e)[:140]})
			continue

		seen[fingerprint] = txn.name
		new_txns.append(txn)
		import_doc.append("results", {**row, "outcome": "New", "sms_transaction": txn.name})

	if settings.auto_create:
		for txn in new_txns:
			if txn.status == "Matched":
				submit_transaction(txn)

	import_doc.parsed_on = now_datetime()
	set_summary(import_doc)
	import_doc.save()


def new_transaction(parsed, fingerprint, import_doc, settings, rules):
	txn = frappe.new_doc("SMS Transaction")
	txn.update(
		{
			"sms_import": import_doc.name,
			"raw_message": parsed.raw,
			"sms_pattern": parsed.pattern,
			"bank": import_doc.bank,
			"dedup_hash": fingerprint,
		}
	)
	if parsed.kind == ERROR:
		txn.status = "Error"
		txn.error_message = parsed.error
		txn.description = _("Unrecognised message")
		return txn

	txn.update(
		{
			"account_identifier": parsed.account,
			"transaction_date": parsed.date,
			"transaction_time": parsed.time,
			"direction": parsed.direction,
			"currency": parsed.currency,
			"amount": parsed.amount,
			"merchant": parsed.merchant,
			"counterparty": parsed.counterparty,
			"reference": parsed.reference,
			"balance_currency": parsed.balance_currency,
			"balance": parsed.balance,
			"company": settings.company,
			"cost_center": settings.cost_center,
		}
	)
	account_row = find_account_row(settings, txn.bank, txn.account_identifier, txn.currency)
	if account_row:
		txn.account_kind = account_row.account_kind
	if txn.currency == "USD" and settings.default_usd_rate:
		txn.exchange_rate = settings.default_usd_rate

	rule = match_rule(txn, rules)
	if rule:
		apply_rule(txn, rule)
	txn.description = render_description(rule.description_template if rule else None, txn)
	txn.status = "Matched" if rule else "Needs Review"
	return txn


def apply_rule(txn, rule):
	txn.matched_rule = rule.name
	for field in DECISION_FIELDS:
		value = rule.get(field)
		if value or field == "is_company_expense":
			txn.set(field, value)


def submit_transaction(txn):
	"""Submit one transaction (which creates its entry) without letting a failure affect the others."""
	if txn.currency and txn.currency != txn.company_currency and not txn.exchange_rate:
		txn.db_set("error_message", _("Set the exchange rate, then submit."))
		return False

	savepoint = new_savepoint()
	try:
		txn.submit()
		return True
	except Exception as e:
		frappe.db.rollback(save_point=savepoint)
		frappe.clear_last_message()
		frappe.db.set_value("SMS Transaction", txn.name, {"status": "Error", "error_message": error_text(e)})
		txn.reload()
		return False


def create_matched_entries(import_doc):
	names = frappe.get_all(
		"SMS Transaction",
		filters={
			"sms_import": import_doc.name,
			"docstatus": 0,
			"status": ["in", ["Matched", "Error"]],
			"matched_rule": ["is", "set"],
			"amount": [">", 0],
		},
		pluck="name",
		order_by="creation asc",
	)
	created = sum(submit_transaction(frappe.get_doc("SMS Transaction", name)) for name in names)
	set_summary(import_doc)
	import_doc.save()
	return created


def set_summary(import_doc):
	"""Recompute counts and row statuses from the rows and the current state of the transactions."""
	txn_names = {row.sms_transaction for row in import_doc.results if row.sms_transaction}
	live = {
		t.name: t
		for t in frappe.get_all(
			"SMS Transaction",
			filters={"name": ["in", list(txn_names) or [""]]},
			fields=["name", "status", "matched_rule", "sms_import"],
		)
	}
	own = [t for t in live.values() if t.sms_import == import_doc.name]

	for row in import_doc.results:
		if row.sms_transaction in live:
			row.status = live[row.sms_transaction].status

	outcomes = [row.outcome for row in import_doc.results]
	import_doc.parsed_count = sum(
		1 for row in import_doc.results if row.outcome in ("New", "Duplicate") and row.amount
	)
	import_doc.matched_count = sum(1 for t in own if t.matched_rule)
	import_doc.created_count = sum(1 for t in own if t.status == "Created")
	import_doc.needs_review_count = sum(1 for t in own if t.status == "Needs Review")
	import_doc.duplicate_count = outcomes.count("Duplicate")
	import_doc.noise_count = outcomes.count("Noise")
	import_doc.error_count = outcomes.count("Error") + sum(1 for t in own if t.status == "Error")


def update_import_summary(import_name):
	"""Refresh an import's counts after one of its transactions changed (no full save, no version)."""
	if not import_name or not frappe.db.exists("SMS Import", import_name):
		return
	import_doc = frappe.get_doc("SMS Import", import_name)
	set_summary(import_doc)
	import_doc.db_update()
	for row in import_doc.results:
		row.db_update()


def new_savepoint():
	name = "sms_" + frappe.generate_hash(length=10)
	frappe.db.savepoint(name)
	return name


def error_text(exc):
	return strip_html(str(exc)).strip() or exc.__class__.__name__
