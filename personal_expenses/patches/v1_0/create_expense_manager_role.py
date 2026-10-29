import frappe


def execute():
	if frappe.db.exists("Role", "Expense Manager"):
		return
	frappe.get_doc({"doctype": "Role", "role_name": "Expense Manager", "desk_access": 1}).insert(
		ignore_permissions=True
	)
