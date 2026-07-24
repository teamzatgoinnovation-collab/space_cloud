/**
 * Vue 3 bootstrap for Space Cloud Desk pages (no Node / Vite in bench).
 * See Docs/Foundation/DESK_VUE.md
 */
frappe.provide("space_cloud.vue");

space_cloud.vue.VUE_ASSET = "/assets/space_cloud/js/vendor/vue.global.prod.js";

space_cloud.vue.ensure = function () {
	if (window.Vue && window.Vue.createApp) {
		return Promise.resolve(window.Vue);
	}
	return new Promise((resolve, reject) => {
		frappe.require(space_cloud.vue.VUE_ASSET, () => {
			if (window.Vue && window.Vue.createApp) {
				resolve(window.Vue);
			} else {
				reject(new Error("Vue failed to load from " + space_cloud.vue.VUE_ASSET));
			}
		});
	});
};

space_cloud.vue.mount = async function (el, options) {
	const Vue = await space_cloud.vue.ensure();
	const app = Vue.createApp(options);
	app.mount(el);
	return app;
};

space_cloud.vue.unmount = function (app) {
	if (app && typeof app.unmount === "function") {
		app.unmount();
	}
};

/** Unwrap space.api.v1 ok({data}) / raw message envelopes. */
space_cloud.vue.unwrap = function (message) {
	if (message == null) return null;
	if (typeof message === "object" && message.ok === false) {
		throw new Error(message.error || message.message || __("Request failed"));
	}
	if (typeof message === "object" && "data" in message) {
		return message.data;
	}
	return message;
};

space_cloud.vue.call = function (method, args) {
	return frappe
		.call({ method, args: args || {}, freeze: false })
		.then((r) => space_cloud.vue.unwrap(r.message));
};
