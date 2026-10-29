# Copyright (c) 2026, Aerele Technologies Private Limited and contributors
# For license information, please see license.txt

import os
from collections import Counter

import frappe

try:
	from frappe.tests import IntegrationTestCase
except ImportError:  # Frappe v15
	from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from personal_expenses.sms_parser.importer import load_patterns
from personal_expenses.sms_parser.parser import ERROR, NOISE, PARSED, parse_text
from personal_expenses.sms_parser.seed import seed_all

# These tests run against a real site; never generate dependent test records (v15 and v16 names).
LINKED_DOCTYPES = [
	"Account",
	"Categories",
	"Company",
	"Cost Center",
	"Currency",
	"DocType",
	"Item",
	"Mode of Payment",
	"SMS Import",
	"SMS Match Rule",
	"SMS Pattern",
	"SMS Transaction",
	"Supplier",
]
test_ignore = LINKED_DOCTYPES
IGNORE_TEST_RECORD_DEPENDENCIES = LINKED_DOCTYPES

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def read_fixture(name):
	with open(os.path.join(FIXTURES, name)) as f:
		return f.read()


HSBC_TEXT = read_fixture("hsbc_sample.txt")
CIB_TEXT = read_fixture("cib_sample.txt")


def make_import(sender, text):
	doc = frappe.get_doc({"doctype": "SMS Import", "sender": sender, "raw_text": text}).insert()
	doc.parse()
	return doc


def transactions(import_doc, **filters):
	return frappe.get_all(
		"SMS Transaction",
		filters={"sms_import": import_doc.name, **filters},
		fields=["*"],
		order_by="creation asc",
	)


def any_leaf(doctype, **filters):
	if not frappe.db.exists("DocType", doctype):
		return None
	return frappe.db.get_value(doctype, {"is_group": 0, **filters}, "name")


class TestSMSImport(IntegrationTestCase):
	def setUp(self):
		# Fresh fingerprints per test, so real transactions on the site never count as duplicates.
		frappe.flags.sms_parser_hash_salt = frappe.generate_hash(length=12)
		seed_all()
		self.set_settings(auto_create=1, auto_submit=0)

	def tearDown(self):
		frappe.flags.sms_parser_hash_salt = None
		frappe.db.rollback()

	def set_settings(self, **values):
		for field, value in values.items():
			frappe.db.set_single_value("SMS Parser Settings", field, value)

	def make_rule(self, keyword, **values):
		rule = frappe.new_doc("SMS Match Rule")
		rule.rule_name = f"_Test {keyword} {frappe.generate_hash(length=6)}"
		rule.append("keywords", {"keyword": keyword, "match_on": values.pop("match_on", "Merchant")})
		rule.update(values)
		return rule.insert()

	def category(self):
		category = any_leaf("Categories")
		if not category:
			self.skipTest("No Categories to use for a Personal Expense")
		return category

	# Parsing only (no database writes)

	def test_parse_hsbc_sample(self):
		parsed = parse_text(HSBC_TEXT, load_patterns("HSBC"), "HSBC")
		kinds = Counter(p.kind for p in parsed)
		self.assertEqual(kinds, Counter({PARSED: 15, NOISE: 1}))

		real = [p for p in parsed if p.kind == PARSED]
		card = [p for p in real if p.pattern == "HSBC Card Purchase / Credit"]
		ipn = [p for p in real if p.pattern == "HSBC IPN Outward Transfer"]
		self.assertEqual(len(ipn), 6)
		self.assertEqual(len([p for p in card if p.currency == "EGP"]), 1)
		self.assertEqual(len([p for p in card if p.currency == "USD" and p.direction == "Debit"]), 7)
		self.assertEqual(len([p for p in real if p.direction == "Credit"]), 1)
		self.assertEqual(len([p for p in card if p.merchant == "ANTHROPIC* CLAUDE SU"]), 3)

		didi = card[0]
		self.assertEqual(
			(didi.merchant, didi.account, didi.currency, didi.amount, didi.balance),
			("DiDi", "013", "EGP", 277.20, 116713.80),
		)
		self.assertEqual(str(didi.date), "2026-10-06")

		first_ipn = ipn[0]
		self.assertEqual(first_ipn.counterparty, "MOHAMMAD MUSLIM YUSUFALI HAMID")
		self.assertEqual((first_ipn.reference, first_ipn.amount, first_ipn.account), ("4b9e8df7", 40020.0, "8013"))
		self.assertEqual((str(first_ipn.date), first_ipn.time), ("2026-10-12", "17:31:00"))

		credit = next(p for p in real if p.direction == "Credit")
		self.assertEqual((credit.merchant, credit.amount), ("TT", 3562.66))

	def test_parse_cib_sample(self):
		parsed = parse_text(CIB_TEXT, load_patterns("CIB"), "CIB")
		real = [p for p in parsed if p.kind == PARSED]
		self.assertEqual(Counter(p.kind for p in parsed), Counter({PARSED: 7, NOISE: 16}))
		self.assertEqual(
			[p.merchant for p in real],
			[
				"Amazon Retail",
				"AmanPF Saed Mar",
				"CHILLOUT ALEX R",
				"WAT IND ALEX",
				"FAWRY BUTCHER B",
				"WE-FBB-Pre",
				"WE-FBB-Pre",
			],
		)
		amazon = real[0]
		self.assertEqual(
			(amazon.account, amazon.currency, amazon.amount, amazon.balance, amazon.time, str(amazon.date)),
			("9014", "EGP", 19999.0, 49847.56, "20:43:00", "2026-10-20"),
		)

	def test_wrapped_message_and_unknown_line(self):
		text = (
			"Your HSBC Account ********8013 was debited with IPN outward transfer for EGP 1,000.00\n"
			" Monday, Oct 12 · 5:31 PM \n"
			"on 12-10-2026 17:31 to SOMEONE with reference abc123. For further details\n"
			"Something the bank never sent before\n"
			"From HSBC: 06OCT26 DiDi Purchase from 071-014***-013 EGP 1.00- Your available balance is EGP 5.00"
		)
		parsed = parse_text(text, load_patterns("HSBC"), "HSBC")
		self.assertEqual([p.kind for p in parsed], [PARSED, PARSED])
		self.assertEqual(parsed[0].counterparty, "SOMEONE")
		# Text without a start marker sticks to the message before it; the regex ignores the tail.
		self.assertIn("Something the bank never sent before", parsed[0].raw)

		parsed = parse_text("Hello from an unknown format\n" + text, load_patterns("HSBC"), "HSBC")
		self.assertEqual(parsed[0].kind, ERROR)

	# Imports

	def test_hsbc_import_and_repaste(self):
		first = make_import("HSBC", HSBC_TEXT)
		txns = transactions(first)
		self.assertEqual(len(txns), 15)
		self.assertEqual((first.parsed_count, first.noise_count, first.error_count), (15, 1, 0))
		self.assertTrue(all(t.bank == "HSBC" for t in txns))

		anthropic_27 = [
			t for t in txns if t.merchant == "ANTHROPIC* CLAUDE SU" and str(t.transaction_date) == "2026-10-27"
		]
		self.assertEqual(len(anthropic_27), 2)
		self.assertEqual({t.balance for t in anthropic_27}, {32870.53, 32847.73})

		# Credits are never expenses unless a credit rule matches.
		credit = next(t for t in txns if t.direction == "Credit")
		self.assertEqual(credit.status, "Needs Review")

		second = make_import("HSBC", HSBC_TEXT)
		self.assertEqual(len(transactions(second)), 0)
		self.assertEqual((second.duplicate_count, second.noise_count), (15, 1))

	def test_cib_import_and_repaste(self):
		first = make_import("CIB", CIB_TEXT)
		txns = transactions(first)
		self.assertEqual(len(txns), 7)
		self.assertEqual((first.error_count, first.noise_count), (0, 16))
		self.assertEqual(len([t for t in txns if t.merchant == "WE-FBB-Pre"]), 2)
		self.assertTrue(all(t.bank == "CIB" and t.account_kind == "Credit Card" for t in txns))

		second = make_import("CIB", CIB_TEXT)
		self.assertEqual(len(transactions(second)), 0)
		self.assertEqual(second.duplicate_count, 7)

	def test_unknown_format_becomes_error_transaction(self):
		doc = make_import("CIB", "Your account was debited with something new\n" + CIB_TEXT.splitlines()[0])
		errors = transactions(doc, status="Error")
		self.assertEqual(len(errors), 1)
		self.assertIn("something new", errors[0].raw_message)
		self.assertEqual(len(transactions(doc, status="Needs Review")), 1)

		# Re-pasting the same unknown text doesn't pile up errors.
		again = make_import("CIB", "Your account was debited with something new")
		self.assertEqual(len(transactions(again)), 0)

	def test_sender_must_be_configured(self):
		doc = frappe.get_doc({"doctype": "SMS Import", "sender": "Unknown Bank", "raw_text": "x"})
		self.assertRaises(frappe.ValidationError, doc.insert)

	# Rules and entries

	def test_rule_creates_personal_expense_and_cancel_removes_it(self):
		category = self.category()
		self.make_rule("didi", personal_category=category)
		doc = make_import("HSBC", HSBC_TEXT.splitlines()[0])

		txn = frappe.get_doc("SMS Transaction", transactions(doc)[0].name)
		self.assertEqual((txn.status, txn.docstatus, txn.linked_doctype), ("Created", 1, "Personal Expenses"))
		pe = frappe.get_doc("Personal Expenses", txn.linked_document)
		self.assertEqual(
			(pe.category, pe.amount, pe.currency, pe.account_type, str(pe.date_vtdp), pe.type),
			(category, 277.20, "EGP", "HSBC", "2026-10-06", "Expense"),
		)
		self.assertEqual(pe.docstatus, 0)
		self.assertEqual(frappe.db.get_value("SMS Import", doc.name, "created_count"), 1)

		txn.cancel()
		self.assertFalse(frappe.db.exists("Personal Expenses", pe.name))
		self.assertEqual(frappe.db.get_value("SMS Transaction", txn.name, "status"), "Matched")

		amended = frappe.copy_doc(txn)
		amended.docstatus = 0
		amended.amended_from = txn.name
		amended.insert()
		self.assertEqual(amended.dedup_hash, txn.dedup_hash)
		self.assertEqual(len(transactions(make_import("HSBC", HSBC_TEXT.splitlines()[0]))), 0)

	def test_usd_rate_default_and_write_back(self):
		category = self.category()
		self.set_settings(default_usd_rate=50)
		self.make_rule("hostinger", personal_category=category, filter_currency="USD")
		doc = make_import("HSBC", HSBC_TEXT)

		hostinger = frappe.get_doc("SMS Transaction", transactions(doc, merchant="HOSTINGER* HOSTINGER")[0].name)
		self.assertEqual((hostinger.status, hostinger.exchange_rate, hostinger.amount_in_egp), ("Created", 50, 21197.0))
		pe = frappe.get_doc("Personal Expenses", hostinger.linked_document)
		self.assertEqual((pe.currency, pe.amount), ("USD", 423.94))
		if pe.meta.has_field("exchange_rate"):
			self.assertEqual(pe.exchange_rate, 50)

		# Reviewing a USD transaction with a new rate makes it the new default, and can save a rule.
		openai = frappe.get_doc("SMS Transaction", transactions(doc, merchant="OPENAI")[0].name)
		self.assertEqual((openai.status, openai.exchange_rate), ("Needs Review", 50))
		openai.update(
			{"exchange_rate": 51.5, "personal_category": category, "save_as_rule": 1, "rule_keyword": "openai"}
		)
		openai.save()
		openai.submit()
		self.assertEqual(frappe.db.get_single_value("SMS Parser Settings", "default_usd_rate"), 51.5)
		self.assertTrue(openai.created_rule)

		next_month = (
			"From HSBC: 28NOV26 OPENAI Purchase from 071-014***-111 USD 5.70- Your available balance is USD 100.00"
		)
		matched = transactions(make_import("HSBC", next_month))[0]
		self.assertEqual((matched.matched_rule, matched.status, matched.exchange_rate), (openai.created_rule, "Created", 51.5))

	def test_failed_auto_create_marks_error_without_rolling_back_batch(self):
		category = self.category()
		self.make_rule("didi", personal_category=category)
		# Company expense rule with no ERP account mapped -> creation fails for this one only.
		if "erpnext" not in frappe.get_installed_apps():
			self.skipTest("ERPNext not installed")
		company = frappe.db.get_single_value("SMS Parser Settings", "company") or frappe.db.get_value("Company", {}, "name")
		expense = any_leaf("Account", company=company, root_type="Expense")
		self.make_rule(
			"MUSTANSIR",
			match_on="Counterparty",
			is_company_expense=1,
			company=company,
			entry_type="Journal Entry",
			expense_account=expense,
		)
		settings = frappe.get_single("SMS Parser Settings")
		for row in settings.bank_accounts:
			if row.account_identifier == "8013":
				row.erp_account = None
		settings.save()

		doc = make_import("HSBC", HSBC_TEXT)
		self.assertEqual(len(transactions(doc, status="Error")), 3)
		self.assertEqual(len(transactions(doc, status="Created")), 1)
		self.assertEqual(len(transactions(doc)), 15)

	def test_journal_entry_multi_currency(self):
		if "erpnext" not in frappe.get_installed_apps():
			self.skipTest("ERPNext not installed")
		company = frappe.db.get_single_value("SMS Parser Settings", "company")
		company_currency = frappe.db.get_value("Company", company, "default_currency") if company else None
		usd_bank = any_leaf("Account", company=company, account_type="Bank", account_currency="USD")
		expense = any_leaf("Account", company=company, root_type="Expense", account_currency=company_currency)
		if not (company and usd_bank and expense and company_currency != "USD"):
			self.skipTest("Needs a company with a USD bank account and an expense account")

		self.set_settings(default_usd_rate=50, auto_submit=1)
		self.map_account("111", usd_bank)
		self.make_rule(
			"hostinger", is_company_expense=1, company=company, entry_type="Journal Entry", expense_account=expense
		)
		doc = make_import("HSBC", HSBC_TEXT)
		txn = frappe.get_doc("SMS Transaction", transactions(doc, merchant="HOSTINGER* HOSTINGER")[0].name)
		self.assertEqual(txn.status, "Created", txn.error_message)

		je = frappe.get_doc("Journal Entry", txn.linked_document)
		self.assertEqual((je.docstatus, je.multi_currency, str(je.posting_date)), (1, 1, "2026-10-25"))
		rows = {r.account: r for r in je.accounts}
		self.assertEqual(rows[expense].debit, 21197.0)
		self.assertEqual((rows[usd_bank].credit_in_account_currency, rows[usd_bank].exchange_rate), (423.94, 50))

		txn.cancel()
		self.assertEqual(frappe.db.get_value("Journal Entry", je.name, "docstatus"), 2)

	def test_purchase_invoice_paid_by_credit_card(self):
		if "erpnext" not in frappe.get_installed_apps():
			self.skipTest("ERPNext not installed")
		company = frappe.db.get_single_value("SMS Parser Settings", "company")
		company_currency = frappe.db.get_value("Company", company, "default_currency") if company else None
		card_account = frappe.db.get_value(
			"Account",
			{
				"company": company,
				"is_group": 0,
				"root_type": "Liability",
				"account_type": ["not in", ["Payable", "Receivable", "Tax"]],
				"account_currency": company_currency,
			},
			"name",
		)
		if not card_account:
			self.skipTest("Needs a liability account for the credit card")

		self.set_settings(auto_submit=1)
		self.map_account("9014", card_account)
		supplier, item = self.supplier_and_item()
		self.make_rule(
			"amazon", is_company_expense=1, company=company, entry_type="Purchase Invoice", supplier=supplier, item=item
		)
		doc = make_import("CIB", CIB_TEXT)
		txn = frappe.get_doc("SMS Transaction", transactions(doc, merchant="Amazon Retail")[0].name)
		self.assertEqual(txn.status, "Created", txn.error_message)

		pi = frappe.get_doc("Purchase Invoice", txn.linked_document)
		self.assertEqual((pi.docstatus, pi.is_paid, pi.cash_bank_account), (1, 1, card_account))
		self.assertEqual((pi.grand_total, pi.outstanding_amount), (19999.0, 0))
		card_credits = frappe.get_all(
			"GL Entry", filters={"voucher_no": pi.name, "account": card_account, "is_cancelled": 0}, pluck="credit"
		)
		self.assertEqual(sum(card_credits), 19999.0)

	def map_account(self, identifier, account):
		settings = frappe.get_single("SMS Parser Settings")
		for row in settings.bank_accounts:
			if row.account_identifier == identifier:
				row.erp_account = account
		settings.save()

	def supplier_and_item(self):
		supplier_group = any_leaf("Supplier Group")
		if not supplier_group:
			self.skipTest("Needs a Supplier Group")
		# A fresh supplier, so its party account currency is the company currency.
		supplier = frappe.get_doc(
			{"doctype": "Supplier", "supplier_name": "_Test SMS Supplier " + frappe.generate_hash(length=6), "supplier_group": supplier_group}
		).insert().name
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "_Test SMS Service " + frappe.generate_hash(length=6),
				"item_group": any_leaf("Item Group"),
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
		).insert()
		return supplier, item.name

