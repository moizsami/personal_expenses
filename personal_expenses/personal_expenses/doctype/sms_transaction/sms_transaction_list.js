// Copyright (c) 2026, Aerele Technologies Private Limited and contributors
// For license information, please see license.txt

frappe.listview_settings["SMS Transaction"] = {
	add_fields: ["status", "currency"],
	get_indicator(doc) {
		const colors = {
			Matched: "blue",
			"Needs Review": "orange",
			Created: "green",
			Ignored: "gray",
			Duplicate: "gray",
			Error: "red",
		};
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},
};
