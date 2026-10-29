// Copyright (c) 2026, Aerele Technologies Private Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on("SMS Transaction", {
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

	refresh(frm) {
		const credit_card = frm.doc.account_kind === "Credit Card";
		frm.set_df_property("balance", "label", credit_card ? __("Available Limit") : __("Balance After"));

		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			const ignored = frm.doc.status === "Ignored";
			frm.add_custom_button(ignored ? __("Un-ignore") : __("Ignore"), () =>
				frm
					.call({ method: "set_ignored", doc: frm.doc, args: { ignored: ignored ? 0 : 1 } })
					.then(() => frm.reload_doc())
			);
		}

		if (frm.doc.linked_doctype && frm.doc.linked_document) {
			frm.add_custom_button(__("Open {0}", [__(frm.doc.linked_doctype)]), () =>
				frappe.set_route("Form", frm.doc.linked_doctype, frm.doc.linked_document)
			);
		}

		if (frm.doc.error_message) {
			frm.set_intro(frm.doc.error_message, "red");
		}
	},

	save_as_rule(frm) {
		if (frm.doc.save_as_rule && !frm.doc.rule_keyword) {
			frm.set_value("rule_keyword", frm.doc.merchant || frm.doc.counterparty);
			frm.set_value("rule_match_on", frm.doc.merchant ? "Merchant" : "Counterparty");
		}
	},

	exchange_rate(frm) {
		frm.set_value("amount_in_egp", flt(frm.doc.amount * frm.doc.exchange_rate, 2));
	},
});
