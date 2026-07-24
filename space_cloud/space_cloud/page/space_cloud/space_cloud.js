frappe.pages["space-cloud"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Space Cloud"),
		single_column: true,
	});

	page.main.html('<div class="space-cloud-root"></div>');
	const el = page.main.find(".space-cloud-root")[0];

	const api = (method, args) => space_cloud.vue.call(method, args);

	const CloudApp = {
		data() {
			return {
				tab: "overview",
				busy: false,
				error: "",
				summary: {},
				sites: [],
				jobs: [],
				servers: [],
				plans: [],
				subscriptions: [],
				selectedSite: null,
				selectedJob: null,
				jobDetail: null,
				jobPoll: null,
			};
		},
		computed: {
			cards() {
				const s = this.summary || {};
				return [
					{ label: __("Customers"), value: s.customers ?? "—" },
					{ label: __("Servers"), value: s.servers ?? "—" },
					{ label: __("Sites"), value: s.sites ?? "—" },
					{ label: __("Active"), value: s.active_sites ?? "—" },
					{ label: __("Running jobs"), value: s.running_jobs ?? "—" },
					{ label: __("Failed jobs"), value: s.failed_jobs ?? "—" },
					{ label: __("Trials"), value: s.trials ?? "—" },
					{ label: __("CPU avg %"), value: s.cpu_usage ?? "—" },
				];
			},
		},
		mounted() {
			wrapper.space_cloud_vm = this;
			this.bootstrap();
		},
		beforeUnmount() {
			this.stopJobPoll();
			if (wrapper.space_cloud_vm === this) {
				wrapper.space_cloud_vm = null;
			}
		},
		methods: {
			statusClass(status) {
				const key = String(status || "")
					.toLowerCase()
					.replace(/\s+/g, "-");
				return `sc-status sc-status-${key}`;
			},
			async bootstrap() {
				await this.refreshAll();
				const params = frappe.utils.get_query_params
					? frappe.utils.get_query_params()
					: {};
				if (params.tab) this.tab = params.tab;
				if (params.site) {
					this.tab = "sites";
					this.selectedSite = params.site;
				}
				if (params.job) {
					this.tab = "deployments";
					await this.openJob(params.job);
				}
			},
			async refreshAll() {
				this.busy = true;
				this.error = "";
				try {
					await Promise.all([
						this.loadSummary(),
						this.loadSites(),
						this.loadJobs(),
						this.loadServers(),
						this.loadCatalog(),
						this.loadSubscriptions(),
					]);
				} catch (e) {
					this.error = e.message || String(e);
					frappe.show_alert({ message: this.error, indicator: "red" });
				} finally {
					this.busy = false;
				}
			},
			async loadSummary() {
				try {
					this.summary = (await api("space.api.v1.space.monitoring_summary")) || {};
				} catch (e) {
					this.summary = {};
				}
			},
			async loadSites() {
				const data = await api("space.api.v1.space.list_sites");
				this.sites = Array.isArray(data) ? data : data?.sites || [];
			},
			async loadJobs() {
				const r = await frappe.call({
					method: "frappe.client.get_list",
					args: {
						doctype: "Space Deployment Job",
						fields: [
							"name",
							"site",
							"server",
							"job_type",
							"status",
							"progress",
							"modified",
							"creation",
						],
						order_by: "modified desc",
						limit_page_length: 50,
					},
				});
				this.jobs = r.message || [];
			},
			async loadServers() {
				const r = await frappe.call({
					method: "frappe.client.get_list",
					args: {
						doctype: "Space Server",
						fields: [
							"name",
							"title",
							"status",
							"health",
							"ip_address",
							"active_sites",
							"cpu_used_percent",
							"ram_used_mb",
							"disk_used_mb",
							"is_default",
						],
						order_by: "is_default desc, modified desc",
						limit_page_length: 50,
					},
				});
				this.servers = r.message || [];
			},
			async loadCatalog() {
				try {
					const cat = await api("space.api.v1.space.list_catalog");
					this.plans = cat?.plans || [];
				} catch (e) {
					this.plans = [];
				}
			},
			async loadSubscriptions() {
				try {
					const data = await api("space.api.v1.space.list_subscriptions");
					this.subscriptions = Array.isArray(data) ? data : data?.subscriptions || [];
				} catch (e) {
					this.subscriptions = [];
				}
			},
			setTab(tab) {
				this.tab = tab;
				if (tab !== "deployments") this.stopJobPoll();
			},
			openDoc(doctype, name) {
				frappe.set_route("Form", doctype, name);
			},
			async siteAction(name, action) {
				const map = {
					suspend: "space.api.v1.space.suspend_site",
					resume: "space.api.v1.space.resume_site",
					delete: "space.api.v1.space.delete_site",
				};
				const method = map[action];
				if (!method) return;
				if (action === "delete") {
					const ok = await new Promise((resolve) => {
						frappe.confirm(
							__("Delete site {0}? This cannot be undone.", [name]),
							() => resolve(true),
							() => resolve(false)
						);
					});
					if (!ok) return;
				}
				this.busy = true;
				try {
					const res = await api(method, { name });
					frappe.show_alert({
						message: __("Job queued: {0}", [res?.job || "ok"]),
						indicator: "green",
					});
					await this.loadSites();
					await this.loadJobs();
					if (res?.job) {
						this.tab = "deployments";
						await this.openJob(res.job);
					}
				} catch (e) {
					frappe.show_alert({ message: e.message || String(e), indicator: "red" });
				} finally {
					this.busy = false;
				}
			},
			promptCreateSite() {
				const planOptions = (this.plans || []).map((p) => p.name || p.code).filter(Boolean);
				frappe.prompt(
					[
						{
							fieldname: "site_name",
							label: __("Site slug"),
							fieldtype: "Data",
							reqd: 1,
							description: __("Reserved: space, portal, erp"),
						},
						{
							fieldname: "plan",
							label: __("Plan"),
							fieldtype: "Select",
							options: planOptions.join("\n") || "basic",
							reqd: 1,
							default: planOptions[0] || "basic",
						},
						{
							fieldname: "admin_password",
							label: __("Admin password"),
							fieldtype: "Password",
							reqd: 1,
						},
					],
					async (values) => {
						this.busy = true;
						try {
							const res = await api("space.api.v1.space.create_site", values);
							frappe.show_alert({
								message: __("Creating {0}", [res?.domain || values.site_name]),
								indicator: "blue",
							});
							await this.loadSites();
							await this.loadJobs();
							if (res?.job) {
								this.tab = "deployments";
								await this.openJob(res.job);
							}
						} catch (e) {
							frappe.show_alert({ message: e.message || String(e), indicator: "red" });
						} finally {
							this.busy = false;
						}
					},
					__("Create Site"),
					__("Create")
				);
			},
			stopJobPoll() {
				if (this.jobPoll) {
					clearInterval(this.jobPoll);
					this.jobPoll = null;
				}
			},
			async openJob(name) {
				this.selectedJob = name;
				await this.refreshJobDetail();
				this.stopJobPoll();
				this.jobPoll = setInterval(() => {
					if (!this.selectedJob) return;
					const st = this.jobDetail?.status;
					if (st && ["Success", "Failed", "Cancelled", "Completed"].includes(st)) {
						this.stopJobPoll();
						return;
					}
					this.refreshJobDetail();
				}, 4000);
			},
			async refreshJobDetail() {
				if (!this.selectedJob) return;
				try {
					this.jobDetail = await api("space.api.v1.space.get_job", {
						name: this.selectedJob,
					});
					await this.loadJobs();
				} catch (e) {
					/* keep last detail */
				}
			},
			async serverAction(name, action) {
				this.busy = true;
				try {
					await frappe.call({
						doc: { doctype: "Space Server", name },
						method: action,
					});
					frappe.show_alert({ message: __("{0} done", [action]), indicator: "green" });
					await this.loadServers();
					await this.loadSummary();
				} catch (e) {
					frappe.show_alert({
						message: e.message || e.exc || String(e),
						indicator: "red",
					});
				} finally {
					this.busy = false;
				}
			},
		},
		template: `
		<div class="sc-page" :class="{'sc-busy': busy}">
			<div class="sc-brand">
				<div>
					<h1 class="sc-brand-title">{{ __("Space Cloud") }}</h1>
					<p class="sc-brand-sub">{{ __("Provision and operate ERPNext sites across your server pool.") }}</p>
				</div>
				<button class="btn btn-default btn-sm" @click="refreshAll">{{ __("Refresh") }}</button>
			</div>

			<div class="sc-tabs">
				<button class="sc-tab" :class="{'is-active': tab==='overview'}" @click="setTab('overview')">{{ __("Overview") }}</button>
				<button class="sc-tab" :class="{'is-active': tab==='sites'}" @click="setTab('sites')">{{ __("Sites") }}</button>
				<button class="sc-tab" :class="{'is-active': tab==='deployments'}" @click="setTab('deployments')">{{ __("Deployments") }}</button>
				<button class="sc-tab" :class="{'is-active': tab==='servers'}" @click="setTab('servers')">{{ __("Servers") }}</button>
				<button class="sc-tab" :class="{'is-active': tab==='billing'}" @click="setTab('billing')">{{ __("Plans") }}</button>
			</div>

			<div v-if="error" class="alert alert-danger">{{ error }}</div>

			<div v-if="tab==='overview'">
				<div class="sc-cards">
					<div class="sc-card" v-for="c in cards" :key="c.label">
						<p class="sc-card-label">{{ c.label }}</p>
						<p class="sc-card-value">{{ c.value }}</p>
					</div>
				</div>
				<div class="sc-panel" v-if="summary.server_health && summary.server_health.length">
					<div class="sc-toolbar"><strong>{{ __("Server health") }}</strong></div>
					<div class="sc-row" v-for="s in summary.server_health" :key="s.name" @click="openDoc('Space Server', s.name)">
						<div>
							<span class="sc-row-title">{{ s.name }}</span>
							<span :class="statusClass(s.health || s.status)">{{ s.health || s.status }}</span>
						</div>
					</div>
				</div>
			</div>

			<div v-if="tab==='sites'" class="sc-panel">
				<div class="sc-toolbar">
					<strong>{{ __("Sites") }} ({{ sites.length }})</strong>
					<button class="btn btn-primary btn-sm" @click="promptCreateSite">{{ __("Create Site") }}</button>
				</div>
				<div v-if="!sites.length" class="sc-empty">
					<div class="sc-empty-title">{{ __("No sites yet") }}</div>
					<div>{{ __("Create a site to start provisioning on the pool.") }}</div>
				</div>
				<div
					v-for="row in sites"
					:key="row.name"
					class="sc-row"
					:class="{'is-selected': selectedSite===row.name}"
					@click="selectedSite=row.name"
				>
					<div>
						<span class="sc-row-title">{{ row.domain || row.site_name || row.name }}</span>
						<span :class="statusClass(row.status)">{{ row.status }}</span>
						<div class="sc-row-meta">
							<span>{{ row.plan || "—" }}</span>
							<span class="dot">·</span>
							<span>{{ row.server || "—" }}</span>
							<span class="dot" v-if="row.job">·</span>
							<a v-if="row.job" href="#" @click.prevent="openJob(row.job); setTab('deployments')">{{ row.job }}</a>
						</div>
					</div>
					<div class="sc-btn-row" @click.stop>
						<button class="btn btn-xs btn-default" @click="openDoc('Space Site', row.name)">{{ __("Open") }}</button>
						<button class="btn btn-xs btn-default" v-if="row.status==='Active'" @click="siteAction(row.name, 'suspend')">{{ __("Suspend") }}</button>
						<button class="btn btn-xs btn-default" v-if="row.status==='Suspended'" @click="siteAction(row.name, 'resume')">{{ __("Resume") }}</button>
						<button class="btn btn-xs btn-danger" v-if="row.status!=='Deleted'" @click="siteAction(row.name, 'delete')">{{ __("Delete") }}</button>
					</div>
				</div>
			</div>

			<div v-if="tab==='deployments'" class="sc-panel">
				<div class="sc-toolbar">
					<strong>{{ __("Deployment jobs") }}</strong>
					<button class="btn btn-default btn-sm" @click="loadJobs">{{ __("Reload") }}</button>
				</div>
				<div v-if="!jobs.length" class="sc-empty">
					<div class="sc-empty-title">{{ __("No jobs") }}</div>
				</div>
				<div
					v-for="row in jobs"
					:key="row.name"
					class="sc-row"
					:class="{'is-selected': selectedJob===row.name}"
					@click="openJob(row.name)"
				>
					<div style="flex:1">
						<span class="sc-row-title">{{ row.job_type }} · {{ row.site }}</span>
						<span :class="statusClass(row.status)">{{ row.status }}</span>
						<div class="sc-row-meta">
							<span>{{ row.name }}</span>
							<span class="dot">·</span>
							<span>{{ row.progress || 0 }}%</span>
						</div>
						<div class="sc-progress"><span :style="{width: (row.progress||0)+'%'}"></span></div>
					</div>
					<div class="sc-btn-row" @click.stop>
						<button class="btn btn-xs btn-default" @click="openDoc('Space Deployment Job', row.name)">{{ __("Form") }}</button>
					</div>
				</div>
				<div class="sc-detail" v-if="jobDetail">
					<div class="sc-toolbar">
						<strong>{{ jobDetail.name }} — {{ jobDetail.status }} ({{ jobDetail.progress || 0 }}%)</strong>
						<button class="btn btn-xs btn-default" @click="refreshJobDetail">{{ __("Poll") }}</button>
					</div>
					<pre class="sc-pre">{{ jobDetail.output || jobDetail.error_log || __("No output yet") }}</pre>
				</div>
			</div>

			<div v-if="tab==='servers'" class="sc-panel">
				<div class="sc-toolbar"><strong>{{ __("Servers") }}</strong></div>
				<div v-if="!servers.length" class="sc-empty">
					<div class="sc-empty-title">{{ __("No servers") }}</div>
				</div>
				<div class="sc-row" v-for="row in servers" :key="row.name">
					<div>
						<span class="sc-row-title">{{ row.title || row.name }}</span>
						<span :class="statusClass(row.health || row.status)">{{ row.health || row.status }}</span>
						<div class="sc-row-meta">
							<span>{{ row.ip_address || "—" }}</span>
							<span class="dot">·</span>
							<span>{{ __("Sites") }}: {{ row.active_sites || 0 }}</span>
							<span class="dot">·</span>
							<span>CPU {{ row.cpu_used_percent || 0 }}%</span>
						</div>
					</div>
					<div class="sc-btn-row" @click.stop>
						<button class="btn btn-xs btn-default" @click="openDoc('Space Server', row.name)">{{ __("Open") }}</button>
						<button class="btn btn-xs btn-default" @click="serverAction(row.name, 'test_connection')">{{ __("Test") }}</button>
						<button class="btn btn-xs btn-default" @click="serverAction(row.name, 'refresh_statistics')">{{ __("Refresh stats") }}</button>
					</div>
				</div>
			</div>

			<div v-if="tab==='billing'">
				<div class="sc-panel" style="margin-bottom:12px">
					<div class="sc-toolbar"><strong>{{ __("Plans") }}</strong></div>
					<div class="sc-row" v-for="p in plans" :key="p.name" @click="openDoc('Space Plan', p.name)">
						<div>
							<span class="sc-row-title">{{ p.title || p.name }}</span>
							<div class="sc-row-meta">
								<span>{{ p.mock_price || ("$" + (p.monthly_price||0) + " / mo") }}</span>
								<span class="dot">·</span>
								<span>{{ p.storage_mb || 0 }} MB disk</span>
							</div>
						</div>
					</div>
					<div v-if="!plans.length" class="sc-empty"><div class="sc-empty-title">{{ __("No plans") }}</div></div>
				</div>
				<div class="sc-panel">
					<div class="sc-toolbar"><strong>{{ __("Subscriptions") }}</strong></div>
					<div class="sc-row" v-for="s in subscriptions" :key="s.name" @click="openDoc('Space Subscription', s.name)">
						<div>
							<span class="sc-row-title">{{ s.customer }} · {{ s.plan }}</span>
							<span :class="statusClass(s.status)">{{ s.status }}</span>
							<div class="sc-row-meta">
								<span>{{ s.payment_status }}</span>
								<span class="dot" v-if="s.end_date">·</span>
								<span v-if="s.end_date">{{ __("Ends") }} {{ s.end_date }}</span>
							</div>
						</div>
					</div>
					<div v-if="!subscriptions.length" class="sc-empty"><div class="sc-empty-title">{{ __("No subscriptions") }}</div></div>
				</div>
			</div>
		</div>
		`,
	};

	space_cloud.vue.mount(el, CloudApp).then((app) => {
		wrapper.space_cloud_vue_app = app;
	});
};

frappe.pages["space-cloud"].on_page_show = function (wrapper) {
	if (wrapper.space_cloud_vm && typeof wrapper.space_cloud_vm.refreshAll === "function") {
		wrapper.space_cloud_vm.refreshAll();
	}
};
