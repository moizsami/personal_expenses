"""Keyword rules (SMS Match Rule) and account map lookups."""

import re

import frappe


def load_rules():
	"""Enabled SMS Match Rules with their keywords, in the order they should be tried."""
	rules = frappe.get_all(
		"SMS Match Rule",
		filters={"enabled": 1},
		fields=[
			"name",
			"priority",
			"bank",
			"filter_currency",
			"direction",
			"is_company_expense",
			"personal_category",
			"company",
			"entry_type",
			"expense_account",
			"supplier",
			"item",
			"cost_center",
			"description_template",
		],
		order_by="priority asc, name asc",
	)
	keywords = frappe.get_all(
		"SMS Match Rule Keyword",
		filters={"parenttype": "SMS Match Rule", "parent": ["in", [r.name for r in rules] or [""]]},
		fields=["parent", "keyword", "match_on", "match_type"],
		order_by="idx asc",
	)
	by_rule = {}
	for kw in keywords:
		by_rule.setdefault(kw.parent, []).append(kw)
	for rule in rules:
		rule.keywords = by_rule.get(rule.name, [])
	return rules


def match_rule(txn, rules):
	"""Return the first rule (rules are pre-sorted) whose filters and any keyword match the transaction."""
	for rule in rules:
		if rule.bank and rule.bank != txn.bank:
			continue
		if rule.filter_currency and rule.filter_currency != txn.currency:
			continue
		if (rule.direction or "Debit") != txn.direction:
			continue
		if any(keyword_matches(kw, txn) for kw in rule.keywords):
			return rule
	return None


def keyword_matches(kw, txn):
	keyword = (kw.keyword or "").strip()
	if not keyword:
		return False

	if kw.match_on == "Counterparty":
		haystack = txn.counterparty
	elif kw.match_on == "Full Text":
		haystack = txn.raw_message
	else:
		haystack = txn.merchant
	haystack = " ".join((haystack or "").split())
	if not haystack:
		return False

	if kw.match_type == "Exact":
		return haystack.casefold() == keyword.casefold()
	if kw.match_type == "Regex":
		try:
			return bool(re.search(keyword, haystack, re.IGNORECASE))
		except re.error:
			return False
	return keyword.casefold() in haystack.casefold()


def find_account_row(settings, bank, identifier, currency=None):
	"""Find the SMS Bank Account Map row for an account seen in an SMS.

	SMS show different lengths of the same number (8013 in transfers, 013 on card slips),
	so identifiers match when one ends with the other. Rows in the same currency win, then
	exact matches, then the longest identifier.
	"""
	if not identifier:
		return None

	candidates = []
	for row in settings.bank_accounts:
		ident = (row.account_identifier or "").strip()
		if row.bank != bank or not ident:
			continue
		if ident == identifier or ident.endswith(identifier) or identifier.endswith(ident):
			candidates.append(row)

	if not candidates:
		return None
	return sorted(
		candidates,
		key=lambda r: (
			r.currency != currency,
			r.account_identifier.strip() != identifier,
			-len(r.account_identifier.strip()),
		),
	)[0]


PLACEHOLDER = re.compile(r"\{(\w+)\}")


def render_description(template, txn):
	values = {
		"merchant": txn.merchant,
		"counterparty": txn.counterparty,
		"date": frappe.utils.formatdate(txn.transaction_date) if txn.transaction_date else "",
		"time": (str(txn.transaction_time) or "")[:5] if txn.transaction_time else "",
		"reference": txn.reference,
		"amount": frappe.utils.fmt_money(txn.amount, currency=txn.currency) if txn.amount else "",
		"currency": txn.currency,
		"bank": txn.bank,
		"account": txn.account_identifier,
	}
	if template:
		text = PLACEHOLDER.sub(lambda m: str(values.get(m.group(1)) or ""), template)
	else:
		text = txn.merchant or txn.counterparty or ""
		if txn.reference:
			text = f"{text} (ref {txn.reference})"
	return " ".join(text.split())
