// frappe.pages['personal-expense-das'].on_page_load = function(wrapper) {
// 	var page = frappe.ui.make_app_page({
// 		parent: wrapper,
// 		title: 'Personal Expense Dashboard',
// 		single_column: true
// 	});
// }

frappe.pages['personal-expense-das'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Personal Expense Dashboard',
        single_column: true
    });

    $(frappe.render_template(`<iframe src="https://erps.samtech.me/insights/shared/dashboard/b8gek21w" width="100%" height="2000" frameborder="0"></iframe>`)).appendTo(page.body);
}
