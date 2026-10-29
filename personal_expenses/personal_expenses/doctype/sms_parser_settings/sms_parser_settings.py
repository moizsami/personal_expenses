# Copyright (c) 2026, Aerele Technologies Private Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SMSParserSettings(Document):
	def validate(self):
		seen = set()
		for row in self.senders:
			row.sender = (row.sender or "").strip()
			if row.sender.lower() in seen:
				frappe.throw(_("Sender {0} is listed twice").format(frappe.bold(row.sender)))
			seen.add(row.sender.lower())

		seen = set()
		for row in self.bank_accounts:
			row.account_identifier = (row.account_identifier or "").strip()
			key = (row.bank, row.account_identifier, row.currency)
			if key in seen:
				frappe.throw(_("Row {0}: {1} account {2} is listed twice").format(row.idx, row.bank, row.account_identifier))
			seen.add(key)
			self.check_account_kind(row)

	def check_account_kind(self, row):
		if not row.erp_account:
			return
		root_type = frappe.db.get_value("Account", row.erp_account, "root_type")
		if row.account_kind == "Credit Card" and root_type != "Liability":
			frappe.msgprint(
				_("Row {0}: {1} is a credit card, but {2} is not a liability account").format(
					row.idx, row.account_identifier, row.erp_account
				),
				indicator="orange",
				alert=True,
			)
		elif row.account_kind == "Bank Account" and root_type != "Asset":
			frappe.msgprint(
				_("Row {0}: {1} is a bank account, but {2} is not an asset account").format(
					row.idx, row.account_identifier, row.erp_account
				),
				indicator="orange",
				alert=True,
			)
