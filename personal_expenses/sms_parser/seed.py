"""Default SMS patterns, senders and account rows. Seeding only inserts what is missing,
so it is safe to run again and never overwrites edits made in the UI."""

import frappe

AMOUNT = r"[\d,]+(?:\.\d+)?"

PATTERNS = [
	{
		"pattern_name": "HSBC Card Purchase / Credit",
		"bank": "HSBC",
		"priority": 10,
		"start_marker": "From HSBC:",
		"date_format": "%d%b%y",
		"direction_rule": "From sign",
		"regex": (
			r"^From\s+HSBC:\s*(?P<date>\d{2}[A-Za-z]{3}\d{2})\s+(?P<merchant>.+?)\s+"
			r"(?:Purchase\s+from|Payment\s+to)\s+(?P<account>[\d*X-]+)\s+"
			rf"(?P<currency>[A-Z]{{3}})\s+(?P<amount>{AMOUNT})\s*(?P<sign>[-+])\s*"
			r"Your\s+available\s+balance\s+is\s+"
			rf"(?P<balance_currency>[A-Z]{{3}})\s+(?P<balance>{AMOUNT})"
		),
		"sample_message": (
			"From HSBC: 15OCT26 ANTHROPIC* CLAUDE SU Purchase from 071-014***-111 USD 22.80- "
			"Your available balance is USD 33,321.80"
		),
	},
	{
		"pattern_name": "HSBC IPN Outward Transfer",
		"bank": "HSBC",
		"priority": 20,
		"start_marker": "Your HSBC Account",
		"date_format": "%d-%m-%Y",
		"direction_rule": "Debit",
		"regex": (
			r"^Your\s+HSBC\s+Account\s+(?P<account>[\d*X]+)\s+was\s+debited\s+with\s+IPN\s+outward\s+"
			rf"transfer\s+for\s+(?P<currency>[A-Z]{{3}})\s+(?P<amount>{AMOUNT})\s+on\s+"
			r"(?P<date>\d{1,2}-\d{1,2}-\d{4})\s+(?P<time>\d{1,2}:\d{2})\s+to\s+(?P<counterparty>.+?)\s+"
			r"with\s+reference\s+(?P<reference>[A-Za-z0-9]+)"
		),
		"sample_message": (
			"Your HSBC Account ********8013 was debited with IPN outward transfer for EGP 40,020.00 on "
			"12-10-2026 17:31 to MOHAMMAD MUSLIM YUSUFALI HAMID with reference 4b9e8df7. For further "
			"details, please contact HSBC call centre"
		),
	},
	{
		"pattern_name": "HSBC Invalid IPN PIN",
		"bank": "HSBC",
		"priority": 1,
		"is_noise": 1,
		"regex": r"You\s+have\s+entered\s+an\s+invalid\s+IPN\s+PIN",
		"sample_message": (
			"25-10-2026 20:31 You have entered an invalid IPN PIN for your HSBC Account XXX013."
		),
	},
	{
		"pattern_name": "CIB Credit Card Charge",
		"bank": "CIB",
		"priority": 10,
		"start_marker": "Your credit card ending with#",
		"date_format": "%d/%m/%y",
		"direction_rule": "Debit",
		"regex": (
			r"^Your\s+credit\s+card\s+ending\s+with\s*#\s*(?P<account>\d+)\s+was\s+charged\s+for\s+"
			rf"(?P<currency>[A-Z]{{3}})\s+(?P<amount>{AMOUNT})\s+at\s+(?P<merchant>.+?)\s+on\s+"
			r"(?P<date>\d{1,2}/\d{1,2}/\d{2})\s+at\s+(?P<time>\d{1,2}:\d{2})\.?\s+"
			rf"Card\s+available\s+limit\s+is\s+(?P<balance_currency>[A-Z]{{3}})\s+(?P<balance>{AMOUNT})"
		),
		"sample_message": (
			"Your credit card ending with#9014 was charged for EGP 19999.00 at Amazon Retail on 20/10/26  "
			"at 20:43. Card available limit is EGP  49847.56. For more details, please visit https://cib.eg/mb"
		),
	},
	{
		"pattern_name": "CIB Link Line",
		"bank": "CIB",
		"priority": 1,
		"is_noise": 1,
		"regex": r"^\[.*\]\(https?://.*\)$",
		"sample_message": "[Online Banking - Ways to Bank | Personal | CIB Egypt](https://cib.eg/mb)",
	},
	{
		"pattern_name": "CIB Bare URL",
		"bank": "CIB",
		"priority": 2,
		"is_noise": 1,
		"regex": r"^(?:https?://|www\.)\S+$",
		"sample_message": "www.cibeg.com",
	},
	{
		"pattern_name": "CIB Announcement",
		"bank": "CIB",
		"priority": 3,
		"is_noise": 1,
		"start_marker": "Dear Customer,",
		"regex": r"^Dear\s+Customer,",
		"sample_message": (
			"Dear Customer, we would like to inform you that the Bank will upgrade the credit cards services."
		),
	},
	{
		# Placeholder until sample SMS for CIB debit card / account transfers are available.
		"pattern_name": "CIB Account Debit (placeholder)",
		"bank": "CIB",
		"enabled": 0,
		"priority": 50,
		"start_marker": "CIB-PLACEHOLDER",
		"date_format": "%d/%m/%y",
		"direction_rule": "Debit",
		"regex": r"^CIB-PLACEHOLDER\s+(?P<currency>[A-Z]{3})\s+(?P<amount>[\d,.]+)\s+(?P<date>\S+)",
	},
]

SENDERS = [
	{"sender": "HSBC", "bank": "HSBC", "enabled": 1},
	{"sender": "CIB", "bank": "CIB", "enabled": 1},
]

# ERP accounts are left blank on purpose: choose them in SMS Parser Settings.
BANK_ACCOUNTS = [
	{"bank": "HSBC", "account_identifier": "8013", "currency": "EGP", "account_kind": "Bank Account", "pe_account_type": "HSBC"},
	{"bank": "HSBC", "account_identifier": "111", "currency": "USD", "account_kind": "Bank Account", "pe_account_type": "HSBC"},
	{"bank": "CIB", "account_identifier": "9014", "currency": "EGP", "account_kind": "Credit Card", "pe_account_type": "CIB"},
]


def seed_patterns():
	for pattern in PATTERNS:
		if frappe.db.exists("SMS Pattern", pattern["pattern_name"]):
			continue
		doc = frappe.new_doc("SMS Pattern")
		doc.update({"enabled": 1, **pattern})
		doc.insert(ignore_permissions=True)


def seed_settings():
	settings = frappe.get_single("SMS Parser Settings")

	known_senders = {(row.sender or "").strip().lower() for row in settings.senders}
	for row in SENDERS:
		if row["sender"].lower() not in known_senders:
			settings.append("senders", row)

	known_accounts = {(row.bank, row.account_identifier) for row in settings.bank_accounts}
	for row in BANK_ACCOUNTS:
		if (row["bank"], row["account_identifier"]) in known_accounts:
			continue
		if not frappe.db.exists("Currency", row["currency"]):
			continue
		settings.append("bank_accounts", row)

	if not settings.company and "erpnext" in frappe.get_installed_apps():
		companies = frappe.get_all("Company", pluck="name", limit=2)
		if len(companies) == 1:
			settings.company = companies[0]
			settings.cost_center = frappe.db.get_value("Company", companies[0], "cost_center")

	settings.flags.ignore_permissions = True
	settings.save()


def seed_all():
	seed_patterns()
	seed_settings()
