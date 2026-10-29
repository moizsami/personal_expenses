import frappe

DOCTYPE = "Personal Expenses"


def execute():
	"""Personal Expenses is a DB-only (custom) DocType, so Custom Fields are not allowed on it.
	Add the field to the DocType itself, right after Currency, once."""
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	doctype = frappe.get_doc("DocType", DOCTYPE)
	if any(df.fieldname == "exchange_rate" for df in doctype.fields):
		return

	field = doctype.append(
		"fields",
		{
			"fieldname": "exchange_rate",
			"fieldtype": "Float",
			"label": "Exchange Rate (to EGP)",
			"precision": "6",
			"depends_on": "eval:doc.currency && doc.currency != 'EGP'",
			"description": "Rate used to convert the amount to EGP. Set by the SMS parser for foreign currency expenses.",
		},
	)
	fieldnames = [df.fieldname for df in doctype.fields]
	if "currency" in fieldnames:
		doctype.fields.remove(field)
		doctype.fields.insert(fieldnames.index("currency") + 1, field)
		for idx, df in enumerate(doctype.fields, 1):
			df.idx = idx

	doctype.save(ignore_permissions=True)
