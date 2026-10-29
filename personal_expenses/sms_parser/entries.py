"""Create (and reverse) the document an SMS Transaction stands for.

Only standard document APIs are used, so ERPNext runs its own validations and GL posting.
"""

import frappe
from frappe import _
from frappe.utils import flt

from personal_expenses.sms_parser.matcher import find_account_row

PERSONAL_EXPENSE = "Personal Expenses"


def erpnext_installed():
	return "erpnext" in frappe.get_installed_apps()


def create_entry(txn):
	"""Create the target document for a submitted SMS Transaction. Returns (doctype, name)."""
	settings = frappe.get_single("SMS Parser Settings")
	account_row = find_account_row(settings, txn.bank, txn.account_identifier, txn.currency)

	if not txn.is_company_expense:
		doc = make_personal_expense(txn, account_row)
	else:
		if not erpnext_installed():
			frappe.throw(_("ERPNext is not installed on this site, so company expenses cannot be created"))
		if not (account_row and account_row.erp_account):
			frappe.throw(
				_("Set the ERP Bank / GL Account for {0} account {1} in SMS Parser Settings").format(
					txn.bank, txn.account_identifier
				)
			)
		if txn.entry_type == "Journal Entry":
			doc = make_journal_entry(txn, account_row)
		elif txn.entry_type == "Purchase Invoice":
			doc = make_purchase_invoice(txn, account_row)
		else:
			frappe.throw(_("Select an Entry Type"))

	doc.insert()
	if settings.auto_submit:
		doc.submit()
	return doc.doctype, doc.name


def make_personal_expense(txn, account_row):
	if not frappe.db.exists("DocType", PERSONAL_EXPENSE):
		frappe.throw(_("DocType {0} does not exist on this site").format(PERSONAL_EXPENSE))

	doc = frappe.new_doc(PERSONAL_EXPENSE)
	doc.update(
		{
			"type": "Income" if txn.direction == "Credit" else "Expense",
			"category": txn.personal_category,
			"amount": txn.amount,
			"currency": txn.currency,
			"account_type": (account_row and account_row.pe_account_type) or txn.bank,
			"date_vtdp": txn.transaction_date,
			"notes": (txn.description or "")[:140],
		}
	)
	if txn.currency != txn.company_currency and doc.meta.has_field("exchange_rate"):
		doc.exchange_rate = txn.exchange_rate
	return doc


def make_journal_entry(txn, account_row):
	company_currency = txn.company_currency
	bank_account = account_row.erp_account
	is_debit = txn.direction != "Credit"

	expense_row = {
		"account": txn.expense_account,
		"cost_center": txn.cost_center,
		"user_remark": txn.description,
	}
	bank_row = {"account": bank_account}
	# A debit SMS is an expense: Dr expense, Cr bank. A credit SMS reverses both sides.
	debit_row, credit_row = (expense_row, bank_row) if is_debit else (bank_row, expense_row)
	for row, amount_field in ((debit_row, "debit_in_account_currency"), (credit_row, "credit_in_account_currency")):
		row[amount_field], row["exchange_rate"] = amount_in_account_currency(txn, row["account"], company_currency)

	je = frappe.new_doc("Journal Entry")
	je.update(
		{
			"voucher_type": "Journal Entry",
			"company": txn.company,
			"posting_date": txn.transaction_date,
			# ERPNext wants a Reference No with a Reference Date; card SMS have no reference.
			"cheque_no": txn.reference or txn.name,
			"cheque_date": txn.transaction_date,
			"user_remark": txn.description,
			"multi_currency": int(
				any(get_account_currency(r["account"]) != company_currency for r in (expense_row, bank_row))
			),
		}
	)
	je.append("accounts", expense_row)
	je.append("accounts", bank_row)
	return je


def make_purchase_invoice(txn, account_row):
	if txn.direction == "Credit":
		frappe.throw(_("A Purchase Invoice cannot be created for a credit. Use a Journal Entry instead."))

	pi = frappe.new_doc("Purchase Invoice")
	pi.update(
		{
			"company": txn.company,
			"supplier": txn.supplier,
			"set_posting_time": 1,
			"posting_date": txn.transaction_date,
			"bill_no": txn.reference,
			"bill_date": txn.transaction_date,
			"currency": txn.currency,
			"conversion_rate": txn.exchange_rate if txn.currency != txn.company_currency else 1,
			"is_paid": 1,
			"mode_of_payment": account_row.mode_of_payment,
			"cash_bank_account": account_row.erp_account,
			"remarks": txn.description,
		}
	)
	item = {"item_code": txn.item, "qty": 1, "rate": txn.amount, "cost_center": txn.cost_center}
	if txn.expense_account:
		item["expense_account"] = txn.expense_account
	pi.append("items", item)
	pi.set_missing_values()
	# set_missing_values may pull the supplier's default currency / price list; the SMS decides.
	pi.currency = txn.currency
	pi.conversion_rate = txn.exchange_rate if txn.currency != txn.company_currency else 1
	return pi


def amount_in_account_currency(txn, account, company_currency):
	"""Amount and exchange rate for a JE row posted to `account`."""
	account_currency = get_account_currency(account)
	foreign = txn.currency != company_currency
	if account_currency == txn.currency:
		return flt(txn.amount, 2), (flt(txn.exchange_rate) if foreign else 1)
	if account_currency == company_currency and foreign:
		return flt(txn.amount * flt(txn.exchange_rate), 2), 1
	frappe.throw(
		_("Account {0} is in {1}; it cannot be used for a {2} transaction").format(
			account, account_currency, txn.currency
		)
	)


def get_account_currency(account):
	return frappe.get_cached_value("Account", account, "account_currency")


def cancel_entry(txn):
	"""Undo the document created for a transaction: cancel it if submitted, delete it if draft.

	A Personal Expense is removed entirely (cancelled first if submitted), unless the existing
	Personal Expenses workflow has already posted it to a Journal Entry.
	"""
	doctype, name = txn.linked_doctype, txn.linked_document
	if not (doctype and name) or not frappe.db.exists(doctype, name):
		return

	doc = frappe.get_doc(doctype, name)
	if doctype == PERSONAL_EXPENSE and doc.get("je"):
		frappe.throw(
			_("{0} {1} is already posted in Journal Entry {2}. Reverse that first.").format(
				doctype, name, doc.je
			)
		)

	txn.db_set({"linked_doctype": None, "linked_document": None})
	if doc.docstatus == 0:
		frappe.delete_doc(doctype, name)
		return
	if doc.docstatus == 1:
		doc.cancel()
	if doctype == PERSONAL_EXPENSE:
		frappe.delete_doc(doctype, name)
