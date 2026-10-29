// Copyright (c) 2026, Aerele Technologies Private Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on("SMS Import", {
	onload(frm) {
		frappe.call("personal_expenses.sms_parser.api.get_form_setup").then((r) => {
			const senders = r.message.senders;
			if (frm.doc.sender && !senders.includes(frm.doc.sender)) {
				senders.push(frm.doc.sender);
			}
			frm.set_df_property("sender", "options", [""].concat(senders));
			if (frm.is_new() && !frm.doc.sender && senders.length === 1) {
				frm.set_value("sender", senders[0]);
			}
		});
	},

	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(__("Parse"), () => run(frm, "parse", __("Parsing SMS...")));

		if (frm.doc.matched_count > frm.doc.created_count) {
			frm.add_custom_button(__("Create Matched Entries"), () =>
				run(frm, "create_matched_entries", __("Creating entries..."))
			);
		}

		if (frm.doc.needs_review_count) {
			frm.add_custom_button(__("Review Transactions"), () =>
				frappe.set_route("List", "SMS Transaction", {
					sms_import: frm.doc.name,
					status: "Needs Review",
				})
			);
		}

		frm.set_intro(
			frm.doc.parsed_on
				? __(
						"{0} parsed, {1} matched, {2} created, {3} need review, {4} duplicates, {5} noise, {6} errors.",
						[
							frm.doc.parsed_count,
							frm.doc.matched_count,
							frm.doc.created_count,
							frm.doc.needs_review_count,
							frm.doc.duplicate_count,
							frm.doc.noise_count,
							frm.doc.error_count,
						]
				  )
				: __("Paste the SMS text, save, then click Parse."),
			frm.doc.error_count ? "orange" : "blue"
		);
	},
});

function run(frm, method, message) {
	const call = () => frm.call({ method, doc: frm.doc, freeze: true, freeze_message: message });
	const ready = frm.is_dirty() ? frm.save() : Promise.resolve();
	return ready.then(call).then(() => frm.reload_doc());
}
