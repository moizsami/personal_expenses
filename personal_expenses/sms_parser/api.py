import frappe
from frappe import _

from personal_expenses.sms_parser.entries import erpnext_installed


def get_enabled_senders():
	"""{sender: bank} for enabled rows of SMS Parser Settings > SMS Senders."""
	settings = frappe.get_single("SMS Parser Settings")
	return {row.sender.strip(): row.bank for row in settings.senders if row.enabled and row.sender}


def get_sender_bank(sender):
	bank = get_enabled_senders().get((sender or "").strip())
	if not bank:
		frappe.throw(_("Sender {0} is not an enabled sender in SMS Parser Settings").format(frappe.bold(sender)))
	return bank


@frappe.whitelist()
def get_form_setup():
	"""Options the SMS forms load at runtime, so new senders show up without a migrate."""
	frappe.has_permission("SMS Import", "read", throw=True)
	return {"senders": list(get_enabled_senders()), "erpnext_installed": erpnext_installed()}
