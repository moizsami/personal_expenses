# Copyright (c) 2026, Aerele Technologies Private Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from personal_expenses.sms_parser import importer
from personal_expenses.sms_parser.api import get_sender_bank


class SMSImport(Document):
	def validate(self):
		self.sender = (self.sender or "").strip()
		self.bank = get_sender_bank(self.sender)

	@frappe.whitelist()
	def parse(self):
		self.check_permission("write")
		importer.run_import(self)

	@frappe.whitelist()
	def create_matched_entries(self):
		self.check_permission("write")
		return importer.create_matched_entries(self)
