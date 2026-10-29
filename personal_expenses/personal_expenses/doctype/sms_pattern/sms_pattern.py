# Copyright (c) 2026, Aerele Technologies Private Limited and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

from personal_expenses.sms_parser.parser import PATTERN_GROUPS, compile_patterns, normalize_space, parse_message


class SMSPattern(Document):
	def validate(self):
		try:
			regex = re.compile(self.regex)
		except re.error as e:
			frappe.throw(_("Invalid regex: {0}").format(e))

		unknown = set(regex.groupindex) - set(PATTERN_GROUPS)
		if unknown:
			frappe.throw(
				_("Unknown named groups: {0}. Allowed: {1}").format(
					", ".join(sorted(unknown)), ", ".join(PATTERN_GROUPS)
				)
			)

		if not self.is_noise:
			required = {"amount", "date"} | ({"sign"} if self.direction_rule == "From sign" else set())
			missing = required - set(regex.groupindex)
			if missing:
				frappe.throw(_("The regex must have the named groups: {0}").format(", ".join(sorted(missing))))

		if self.sample_message:
			self.check_sample()

	def check_sample(self):
		sample = normalize_space(self.sample_message)
		pattern = compile_patterns([{**self.as_dict(), "name": self.pattern_name}])
		parsed = parse_message(sample, pattern, self.bank)
		if parsed.kind == "error":
			frappe.throw(_("The regex does not parse the Sample Message: {0}").format(parsed.error))
