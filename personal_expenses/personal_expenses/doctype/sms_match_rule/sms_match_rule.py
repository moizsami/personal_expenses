# Copyright (c) 2026, Aerele Technologies Private Limited and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

from personal_expenses.sms_parser.entries import erpnext_installed

COMPANY_FIELDS = ("company", "entry_type", "expense_account", "supplier", "item", "cost_center")


class SMSMatchRule(Document):
	def validate(self):
		for kw in self.keywords:
			if kw.match_type == "Regex":
				try:
					re.compile(kw.keyword)
				except re.error as e:
					frappe.throw(_("Row {0}: invalid regex {1}: {2}").format(kw.idx, kw.keyword, e))

		if self.is_company_expense:
			if not erpnext_installed():
				frappe.throw(_("ERPNext is not installed on this site, so company expenses are not available"))
			self.personal_category = None
			if self.entry_type != "Purchase Invoice":
				self.supplier = self.item = None
		else:
			for field in COMPANY_FIELDS:
				self.set(field, None)
