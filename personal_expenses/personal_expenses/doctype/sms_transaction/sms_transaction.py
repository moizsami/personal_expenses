# Copyright (c) 2026, Aerele Technologies Private Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from personal_expenses.sms_parser.entries import cancel_entry, create_entry, erpnext_installed
from personal_expenses.sms_parser.importer import update_import_summary

DEFAULT_COMPANY_CURRENCY = "EGP"


class SMSTransaction(Document):
	def before_insert(self):
		if self.amended_from:
			# The amendment takes over the fingerprint so re-pasting the SMS is still a duplicate.
			self.dedup_hash = frappe.db.get_value("SMS Transaction", self.amended_from, "dedup_hash")
			frappe.db.set_value("SMS Transaction", self.amended_from, "dedup_hash", None)
		self.dedup_hash = self.dedup_hash or None

	def validate(self):
		self.set_company_currency()
		self.set_amount_in_egp()
		if self.is_company_expense and not erpnext_installed():
			frappe.throw(_("ERPNext is not installed on this site, so company expenses are not available"))
		if self.docstatus == 0:
			self.set_draft_status()

	def set_company_currency(self):
		currency = None
		if self.company and erpnext_installed():
			currency = frappe.get_cached_value("Company", self.company, "default_currency")
		self.company_currency = currency or DEFAULT_COMPANY_CURRENCY

	def set_amount_in_egp(self):
		if not self.currency or self.currency == self.company_currency:
			self.exchange_rate = None
			self.amount_in_egp = self.amount
		else:
			self.amount_in_egp = flt(flt(self.amount) * flt(self.exchange_rate), 2)

	def set_draft_status(self):
		if self.status == "Ignored":
			return
		if not self.amount:
			self.status = "Error"
		else:
			self.status = "Matched" if self.matched_rule else "Needs Review"

	def before_submit(self):
		if self.status == "Ignored":
			frappe.throw(_("Ignored transactions cannot be submitted. Un-ignore it first."))
		if not (self.amount and self.transaction_date and self.direction):
			frappe.throw(_("This message could not be parsed, so there is nothing to create"))
		if self.currency != self.company_currency and flt(self.exchange_rate) <= 0:
			frappe.throw(_("Exchange Rate is required for {0} transactions").format(self.currency))

		if not self.is_company_expense:
			if not self.personal_category:
				frappe.throw(_("Personal Expense Category is required"))
			return

		missing = [f for f in ("company", "entry_type") if not self.get(f)]
		if self.entry_type == "Journal Entry" and not self.expense_account:
			missing.append("expense_account")
		if self.entry_type == "Purchase Invoice":
			missing += [f for f in ("supplier", "item") if not self.get(f)]
		if missing:
			frappe.throw(
				_("Missing for a company expense: {0}").format(
					", ".join(_(self.meta.get_label(f)) for f in missing)
				)
			)

	def on_submit(self):
		doctype, name = create_entry(self)
		self.db_set(
			{
				"linked_doctype": doctype,
				"linked_document": name,
				"status": "Created",
				"error_message": None,
			}
		)
		if self.currency == "USD":
			frappe.db.set_single_value("SMS Parser Settings", "default_usd_rate", self.exchange_rate)
		if self.save_as_rule:
			self.db_set("created_rule", self.make_rule())
		update_import_summary(self.sms_import)

	def on_cancel(self):
		cancel_entry(self)
		self.db_set("status", "Matched" if self.matched_rule else "Needs Review")
		update_import_summary(self.sms_import)

	def on_trash(self):
		# Results rows of the import only point here for display; don't let them block deletion.
		frappe.db.set_value(
			"SMS Import Line", {"sms_transaction": self.name}, "sms_transaction", None, update_modified=False
		)

	def make_rule(self):
		keyword = (self.rule_keyword or "").strip()
		if not keyword:
			frappe.throw(_("Keyword is required to save a new rule"))

		rule = frappe.new_doc("SMS Match Rule")
		rule.rule_name = unique_rule_name(keyword)
		rule.bank = self.bank
		rule.direction = self.direction
		rule.append(
			"keywords",
			{
				"keyword": keyword,
				"match_on": self.rule_match_on or ("Merchant" if self.merchant else "Counterparty"),
				"match_type": "Contains",
			},
		)
		rule.is_company_expense = self.is_company_expense
		if self.is_company_expense:
			for field in ("company", "entry_type", "expense_account", "supplier", "item", "cost_center"):
				rule.set(field, self.get(field))
		else:
			rule.personal_category = self.personal_category
		rule.insert()
		return rule.name

	@frappe.whitelist()
	def set_ignored(self, ignored):
		if self.docstatus != 0:
			frappe.throw(_("Only draft transactions can be ignored"))
		self.check_permission("write")
		self.status = "Ignored" if frappe.utils.cint(ignored) else ""
		self.save()


def unique_rule_name(keyword):
	name, i = keyword, 1
	while frappe.db.exists("SMS Match Rule", name):
		i += 1
		name = f"{keyword} ({i})"
	return name
