// Copyright (c) 2026, Aerele Technologies Private Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on("SMS Match Rule", {
	setup(frm) {
		const by_company = () => ({ filters: { company: frm.doc.company, is_group: 0 } });
		frm.set_query("expense_account", by_company);
		frm.set_query("cost_center", by_company);
		frm.set_query("personal_category", () => ({ filters: { is_group: 0 } }));
	},

	onload(frm) {
		frappe.call("personal_expenses.sms_parser.api.get_form_setup").then((r) => {
			if (!r.message.erpnext_installed) {
				frm.set_df_property("is_company_expense", "hidden", 1);
			}
		});
	},

	is_company_expense(frm) {
		if (frm.doc.is_company_expense && !frm.doc.company) {
			frappe.db
				.get_single_value("SMS Parser Settings", "company")
				.then((company) => company && frm.set_value("company", company));
		}
	},
});
