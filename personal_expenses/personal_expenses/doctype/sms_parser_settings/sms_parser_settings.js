// Copyright (c) 2026, Aerele Technologies Private Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on("SMS Parser Settings", {
	setup(frm) {
		const by_company = () => ({ filters: { company: frm.doc.company, is_group: 0 } });
		frm.set_query("cost_center", by_company);
		frm.set_query("erp_account", "bank_accounts", by_company);
	},
});
