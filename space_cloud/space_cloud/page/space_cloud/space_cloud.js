/* ============================================================
   Space Cloud — Admin Cockpit
   Frappe Vue3 Page  |  SpaceCloud app
   ============================================================ */

frappe.pages["space-cloud"].on_page_load = function (wrapper) {
	/* ── inject design-system CSS once ── */
	if (!document.getElementById("sc-theme")) {
		const style = document.createElement("style");
		style.id = "sc-theme";
		style.textContent = `
/* ── Google Font ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Root tokens ── */
.sc-page {
  --sc-bg:        #0f1117;
  --sc-surface:   #181b24;
  --sc-surface2:  #1e2230;
  --sc-border:    rgba(255,255,255,.07);
  --sc-accent:    #7c5cfc;
  --sc-accent2:   #5b8ef0;
  --sc-text:      #e2e8f0;
  --sc-muted:     #8892a4;
  --sc-green:     #22c55e;
  --sc-yellow:    #f59e0b;
  --sc-red:       #ef4444;
  --sc-blue:      #3b82f6;
  --sc-orange:    #f97316;
  --sc-radius:    14px;
  --sc-radius-sm: 8px;
  --sc-shadow:    0 4px 24px rgba(0,0,0,.45);

  font-family: 'Inter', system-ui, sans-serif;
  background: var(--sc-bg);
  color: var(--sc-text);
  min-height: 100vh;
  padding: 0 0 60px;
  position: relative;
}

/* ── Busy overlay ── */
.sc-page.sc-busy::after {
  content: '';
  position: fixed;
  inset: 0;
  background: rgba(15,17,23,.6);
  backdrop-filter: blur(3px);
  z-index: 9999;
}
.sc-page.sc-busy::before {
  content: '';
  position: fixed;
  top: 50%; left: 50%;
  transform: translate(-50%,-50%);
  width: 44px; height: 44px;
  border: 3px solid var(--sc-border);
  border-top-color: var(--sc-accent);
  border-radius: 50%;
  animation: sc-spin .8s linear infinite;
  z-index: 10000;
}
@keyframes sc-spin { to { transform: translate(-50%,-50%) rotate(360deg); } }

/* ── Brand bar ── */
.sc-brand {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 28px 32px 0;
  gap: 16px;
}
.sc-brand-logo {
  display: flex;
  align-items: center;
  gap: 14px;
}
.sc-brand-icon {
  width: 44px; height: 44px;
  background: var(--sc-accent);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.sc-brand-icon svg { fill: #fff; }
.sc-brand-title {
  font-size: 1.7rem;
  font-weight: 800;
  color: #ffffff;
  margin: 0;
  letter-spacing: -0.01em;
}
.sc-brand-sub {
  font-size: .82rem;
  color: var(--sc-muted);
  margin: 2px 0 0;
}
.sc-brand-actions { display: flex; gap: 10px; align-items: center; }

/* ── Buttons ── */
.sc-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px;
  border-radius: var(--sc-radius-sm);
  border: none; cursor: pointer;
  font-size: .82rem; font-weight: 500; font-family: inherit;
  transition: all .18s ease;
  line-height: 1;
}
.sc-btn-ghost {
  background: var(--sc-surface2);
  color: var(--sc-text);
  border: 1px solid var(--sc-border);
}
.sc-btn-ghost:hover { background: rgba(255,255,255,.08); border-color: rgba(255,255,255,.15); }
.sc-btn-primary {
  background: var(--sc-accent);
  color: #fff;
}
.sc-btn-primary:hover { filter: brightness(1.08); }
.sc-btn-danger {
  background: rgba(239,68,68,.12);
  color: var(--sc-red);
  border: 1px solid rgba(239,68,68,.25);
}
.sc-btn-danger:hover { background: rgba(239,68,68,.22); }
.sc-btn-xs { padding: 5px 10px; font-size: .75rem; }
.sc-btn-sm { padding: 7px 14px; font-size: .80rem; }

/* ── Tabs ── */
.sc-tabs {
  display: flex; gap: 4px;
  padding: 20px 32px 0;
  border-bottom: 1px solid var(--sc-border);
  overflow-x: auto;
}
.sc-tab {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 10px 18px;
  background: transparent;
  border: none; cursor: pointer;
  font-size: .85rem; font-weight: 500;
  color: var(--sc-muted);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: all .2s ease;
  white-space: nowrap;
  font-family: inherit;
}
.sc-tab:hover { color: var(--sc-text); }
.sc-tab.is-active {
  color: var(--sc-accent);
  border-bottom-color: var(--sc-accent);
}
.sc-tab svg { opacity: .7; }
.sc-tab.is-active svg { opacity: 1; }

/* ── Content wrapper ── */
.sc-content { padding: 24px 32px; }

/* ── Alert ── */
.sc-alert {
  display: flex; align-items: center; gap: 10px;
  background: rgba(239,68,68,.1);
  border: 1px solid rgba(239,68,68,.3);
  border-radius: var(--sc-radius-sm);
  padding: 12px 16px;
  color: var(--sc-red);
  font-size: .85rem;
  margin-bottom: 20px;
}

/* ── Stat cards ── */
.sc-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
  margin-bottom: 28px;
}
.sc-card {
  background: var(--sc-surface);
  border: 1px solid var(--sc-border);
  border-radius: var(--sc-radius);
  padding: 20px;
  display: flex; flex-direction: column; gap: 10px;
  transition: transform .2s, box-shadow .2s;
  position: relative; overflow: hidden;
}
.sc-card::before {
  content: '';
  position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: var(--sc-accent);
  opacity: 0;
  transition: opacity .2s;
}
.sc-card:hover { transform: translateY(-2px); box-shadow: var(--sc-shadow); }
.sc-card:hover::before { opacity: 1; }
.sc-card-icon {
  width: 36px; height: 36px;
  border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
}
.sc-card-label { font-size: .75rem; color: var(--sc-muted); font-weight: 500; letter-spacing: .04em; text-transform: uppercase; }
.sc-card-value { font-size: 2rem; font-weight: 700; color: var(--sc-text); line-height: 1; }

/* Card icon colors */
.sc-card-icon-violet  { background: rgba(124,92,252,.15); color: var(--sc-accent); }
.sc-card-icon-blue    { background: rgba(91,142,240,.15); color: var(--sc-accent2); }
.sc-card-icon-green   { background: rgba(34,197,94,.15);  color: var(--sc-green); }
.sc-card-icon-yellow  { background: rgba(245,158,11,.15); color: var(--sc-yellow); }
.sc-card-icon-red     { background: rgba(239,68,68,.15);  color: var(--sc-red); }
.sc-card-icon-orange  { background: rgba(249,115,22,.15); color: var(--sc-orange); }

/* ── Panel ── */
.sc-panel {
  background: var(--sc-surface);
  border: 1px solid var(--sc-border);
  border-radius: var(--sc-radius);
  overflow: hidden;
  margin-bottom: 20px;
}
.sc-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--sc-border);
  font-size: .88rem; font-weight: 600;
  color: var(--sc-text);
  gap: 12px;
}
.sc-toolbar-left { display: flex; align-items: center; gap: 10px; }
.sc-toolbar-right { display: flex; gap: 8px; }
.sc-panel-title { font-size: .88rem; font-weight: 600; color: var(--sc-text); }
.sc-panel-count {
  background: var(--sc-surface2);
  border: 1px solid var(--sc-border);
  border-radius: 20px;
  padding: 2px 10px;
  font-size: .74rem;
  color: var(--sc-muted);
}

/* ── Rows ── */
.sc-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid var(--sc-border);
  cursor: pointer;
  transition: background .15s;
  gap: 12px;
}
.sc-row:last-child { border-bottom: none; }
.sc-row:hover { background: rgba(255,255,255,.03); }
.sc-row.is-selected { background: rgba(124,92,252,.08); border-left: 3px solid var(--sc-accent); }
.sc-row-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.sc-row-header { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.sc-row-title {
  font-size: .88rem; font-weight: 600;
  color: var(--sc-text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.sc-row-meta {
  display: flex; align-items: center; gap: 8px;
  font-size: .76rem; color: var(--sc-muted);
  flex-wrap: wrap;
}
.sc-row-meta a { color: var(--sc-accent2); text-decoration: none; }
.sc-row-meta a:hover { text-decoration: underline; }
.dot { opacity: .4; }
.sc-btn-row { display: flex; gap: 6px; flex-shrink: 0; }

/* ── Status badges ── */
.sc-status {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 10px;
  border-radius: 20px;
  font-size: .72rem; font-weight: 600;
  white-space: nowrap;
  letter-spacing: .03em;
}
.sc-status::before {
  content: '';
  width: 6px; height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
.sc-status-active    { background: rgba(34,197,94,.12);  color: var(--sc-green);  }
.sc-status-healthy   { background: rgba(34,197,94,.12);  color: var(--sc-green);  }
.sc-status-online    { background: rgba(34,197,94,.12);  color: var(--sc-green);  }
.sc-status-success   { background: rgba(34,197,94,.12);  color: var(--sc-green);  }
.sc-status-completed { background: rgba(34,197,94,.12);  color: var(--sc-green);  }
.sc-status-running   { background: rgba(59,130,246,.12); color: var(--sc-blue);   }
.sc-status-provisioning { background: rgba(59,130,246,.12); color: var(--sc-blue); }
.sc-status-pending   { background: rgba(59,130,246,.12); color: var(--sc-blue);   }
.sc-status-suspended { background: rgba(245,158,11,.12); color: var(--sc-yellow); }
.sc-status-paused    { background: rgba(245,158,11,.12); color: var(--sc-yellow); }
.sc-status-warning   { background: rgba(245,158,11,.12); color: var(--sc-yellow); }
.sc-status-failed    { background: rgba(239,68,68,.12);  color: var(--sc-red);    }
.sc-status-error     { background: rgba(239,68,68,.12);  color: var(--sc-red);    }
.sc-status-deleted   { background: rgba(255,255,255,.06); color: var(--sc-muted); }
.sc-status-inactive  { background: rgba(255,255,255,.06); color: var(--sc-muted); }

/* Running pulse animation */
.sc-status-running::before,
.sc-status-provisioning::before,
.sc-status-pending::before {
  animation: sc-pulse 1.4s ease-in-out infinite;
}
@keyframes sc-pulse {
  0%,100% { opacity: 1; } 50% { opacity: .3; }
}

/* ── Progress bar ── */
.sc-progress {
  height: 4px;
  background: rgba(255,255,255,.08);
  border-radius: 2px;
  overflow: hidden;
  margin-top: 6px;
}
.sc-progress-bar {
  height: 100%;
  background: var(--sc-accent);
  border-radius: 2px;
  transition: width .5s ease;
}
.sc-progress-bar.is-running {
  background: var(--sc-accent);
  opacity: 0.8;
}
@keyframes sc-progress-shimmer { to { background-position: -200% 0; } }

/* ── Job detail pane ── */
.sc-detail {
  background: var(--sc-surface2);
  border-top: 1px solid var(--sc-border);
  padding: 0;
}
.sc-pre {
  background: #0b0d14;
  color: #a3e635;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: .78rem;
  padding: 16px 20px;
  margin: 0;
  overflow-x: auto;
  max-height: 340px;
  overflow-y: auto;
  border: none;
  border-radius: 0;
  line-height: 1.6;
}

/* ── Server metric pills ── */
.sc-metrics { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 4px; }
.sc-metric {
  display: flex; align-items: center; gap: 5px;
  background: var(--sc-surface2);
  border: 1px solid var(--sc-border);
  border-radius: 6px;
  padding: 3px 9px;
  font-size: .73rem; color: var(--sc-muted);
}
.sc-metric-bar {
  width: 36px; height: 4px;
  background: rgba(255,255,255,.08);
  border-radius: 2px;
  overflow: hidden;
}
.sc-metric-bar span {
  display: block; height: 100%; border-radius: 2px;
  background: var(--sc-accent2);
  transition: width .4s ease;
}
.sc-metric-bar span.is-warn  { background: var(--sc-yellow); }
.sc-metric-bar span.is-danger{ background: var(--sc-red); }

/* ── Pricing cards ── */
.sc-plans-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
  padding: 20px;
}
.sc-plan-card {
  background: var(--sc-surface2);
  border: 1px solid var(--sc-border);
  border-radius: var(--sc-radius);
  padding: 22px;
  display: flex; flex-direction: column; gap: 12px;
  cursor: pointer;
  transition: border-color .2s, box-shadow .2s;
}
.sc-plan-card:hover { border-color: var(--sc-accent); box-shadow: 0 0 0 1px var(--sc-accent); }
.sc-plan-name { font-size: .95rem; font-weight: 700; color: var(--sc-text); }
.sc-plan-price {
  font-size: 1.8rem; font-weight: 700;
  color: var(--sc-accent);
  line-height: 1;
}
.sc-plan-price span { font-size: .85rem; color: var(--sc-muted); font-weight: 400; }
.sc-plan-features { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.sc-plan-feature { display: flex; align-items: center; gap: 8px; font-size: .8rem; color: var(--sc-muted); }
.sc-plan-feature svg { flex-shrink: 0; color: var(--sc-green); }

/* ── Subscriptions ── */
.sc-subs-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

/* ── Server health in overview ── */
.sc-health-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
  padding: 16px 20px;
}
.sc-health-card {
  background: var(--sc-surface2);
  border: 1px solid var(--sc-border);
  border-radius: var(--sc-radius-sm);
  padding: 14px 16px;
  display: flex; align-items: center; gap: 12px;
  cursor: pointer;
  transition: background .15s;
}
.sc-health-card:hover { background: rgba(255,255,255,.04); }
.sc-health-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.sc-health-dot.is-healthy { background: var(--sc-green); box-shadow: 0 0 8px var(--sc-green); }
.sc-health-dot.is-warn    { background: var(--sc-yellow); box-shadow: 0 0 8px var(--sc-yellow); }
.sc-health-dot.is-error   { background: var(--sc-red); box-shadow: 0 0 8px var(--sc-red); }
.sc-health-name { font-size: .84rem; font-weight: 600; color: var(--sc-text); }

/* ── Empty state ── */
.sc-empty {
  display: flex; flex-direction: column; align-items: center;
  gap: 12px; padding: 56px 20px;
  color: var(--sc-muted);
}
.sc-empty-icon {
  width: 64px; height: 64px;
  background: var(--sc-surface2);
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  border: 1px solid var(--sc-border);
}
.sc-empty-title { font-size: 1rem; font-weight: 600; color: var(--sc-text); }
.sc-empty p { font-size: .84rem; text-align: center; max-width: 280px; margin: 0; }

/* ── Responsive ── */
@media (max-width: 640px) {
  .sc-brand { padding: 16px; }
  .sc-tabs  { padding: 12px 16px 0; }
  .sc-content { padding: 16px; }
  .sc-toolbar { padding: 12px 16px; }
  .sc-row { padding: 12px 16px; }
}
`;
		document.head.appendChild(style);
	}

	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Space Cloud"),
		single_column: true,
	});

	page.main.html('<div class="space-cloud-root"></div>');
	const el = page.main.find(".space-cloud-root")[0];

	const api = (method, args) => space_cloud.vue.call(method, args);

	/* ── SVG icon helpers ── */
	const ICONS = {
		cloud: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>`,
		grid:  `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>`,
		globe: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>`,
		zap:   `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
		server:`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>`,
		dollar:`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>`,
		refresh:`<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`,
		plus:  `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>`,
		check: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`,
		box:   `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>`,
		users: `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
		cpu:   `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>`,
		wave:  `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>`,
		alert: `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
		trial: `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2V9M9 21H5a2 2 0 0 1-2-2V9m0 0h18"/></svg>`,
	};

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
					{ label: __("Customers"), value: s.customers ?? "—", icon: "users",  cls: "sc-card-icon-violet" },
					{ label: __("Servers"),   value: s.servers   ?? "—", icon: "server", cls: "sc-card-icon-blue"   },
					{ label: __("Sites"),     value: s.sites     ?? "—", icon: "globe",  cls: "sc-card-icon-violet" },
					{ label: __("Active"),    value: s.active_sites ?? "—", icon: "box", cls: "sc-card-icon-green"  },
					{ label: __("Running jobs"), value: s.running_jobs ?? "—", icon: "zap",   cls: "sc-card-icon-blue"   },
					{ label: __("Failed jobs"),  value: s.failed_jobs  ?? "—", icon: "alert", cls: "sc-card-icon-red"    },
					{ label: __("Trials"),   value: s.trials    ?? "—", icon: "trial", cls: "sc-card-icon-yellow"  },
					{ label: __("CPU avg %"), value: s.cpu_usage ?? "—", icon: "cpu",   cls: "sc-card-icon-orange"  },
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
			healthDotClass(s) {
				const st = String(s || "").toLowerCase();
				if (["healthy","active","online"].includes(st)) return "sc-health-dot is-healthy";
				if (["warning","degraded"].includes(st)) return "sc-health-dot is-warn";
				return "sc-health-dot is-error";
			},
			metricBarClass(pct) {
				if (pct >= 85) return "is-danger";
				if (pct >= 65) return "is-warn";
				return "";
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
							"name", "site", "server", "job_type",
							"status", "progress", "modified", "creation",
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
							"name", "title", "status", "health", "ip_address",
							"active_sites", "cpu_used_percent", "ram_used_mb",
							"disk_used_mb", "is_default",
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
					resume:  "space.api.v1.space.resume_site",
					delete:  "space.api.v1.space.delete_site",
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

		/* ══════════════════════════════════════════════════════
		   TEMPLATE
		══════════════════════════════════════════════════════ */
		template: `
<div class="sc-page" :class="{'sc-busy': busy}">

  <!-- ── Brand bar ── -->
  <div class="sc-brand">
    <div class="sc-brand-logo">
      <div class="sc-brand-icon">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>
      </div>
      <div>
        <h1 class="sc-brand-title">{{ __("Space Cloud") }}</h1>
        <p class="sc-brand-sub">{{ __("Provision and operate ERPNext sites across your server pool.") }}</p>
      </div>
    </div>
    <div class="sc-brand-actions">
      <button class="sc-btn sc-btn-ghost sc-btn-sm" @click="refreshAll">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        {{ __("Refresh") }}
      </button>
    </div>
  </div>

  <!-- ── Tabs ── -->
  <div class="sc-tabs">
    <button class="sc-tab" :class="{'is-active': tab==='overview'}" @click="setTab('overview')">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
      {{ __("Overview") }}
    </button>
    <button class="sc-tab" :class="{'is-active': tab==='sites'}" @click="setTab('sites')">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
      {{ __("Sites") }}
      <span v-if="sites.length" class="sc-panel-count">{{ sites.length }}</span>
    </button>
    <button class="sc-tab" :class="{'is-active': tab==='deployments'}" @click="setTab('deployments')">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
      {{ __("Deployments") }}
      <span v-if="jobs.length" class="sc-panel-count">{{ jobs.length }}</span>
    </button>
    <button class="sc-tab" :class="{'is-active': tab==='servers'}" @click="setTab('servers')">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
      {{ __("Servers") }}
    </button>
    <button class="sc-tab" :class="{'is-active': tab==='billing'}" @click="setTab('billing')">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
      {{ __("Plans & Billing") }}
    </button>
  </div>

  <div class="sc-content">

    <!-- ── Error banner ── -->
    <div v-if="error" class="sc-alert">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      {{ error }}
    </div>

    <!-- ══════ OVERVIEW ══════ -->
    <div v-if="tab==='overview'">

      <!-- Stat cards -->
      <div class="sc-cards">
        <div class="sc-card" v-for="c in cards" :key="c.label">
          <div class="sc-card-icon" :class="c.cls">
            <svg v-if="c.icon==='users'"  width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
            <svg v-if="c.icon==='server'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
            <svg v-if="c.icon==='globe'"  width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
            <svg v-if="c.icon==='box'"    width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
            <svg v-if="c.icon==='zap'"    width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
            <svg v-if="c.icon==='alert'"  width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            <svg v-if="c.icon==='trial'"  width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2V9M9 21H5a2 2 0 0 1-2-2V9m0 0h18"/></svg>
            <svg v-if="c.icon==='cpu'"    width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>
          </div>
          <div class="sc-card-label">{{ c.label }}</div>
          <div class="sc-card-value">{{ c.value }}</div>
        </div>
      </div>

      <!-- Server health grid -->
      <div class="sc-panel" v-if="summary.server_health && summary.server_health.length">
        <div class="sc-toolbar">
          <span class="sc-panel-title">{{ __("Server Health") }}</span>
          <span class="sc-panel-count">{{ summary.server_health.length }}</span>
        </div>
        <div class="sc-health-grid">
          <div class="sc-health-card" v-for="s in summary.server_health" :key="s.name" @click="openDoc('Space Server', s.name)">
            <div :class="healthDotClass(s.health || s.status)"></div>
            <div>
              <div class="sc-health-name">{{ s.name }}</div>
              <span :class="statusClass(s.health || s.status)">{{ s.health || s.status }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Overview empty -->
      <div class="sc-panel" v-if="!summary.server_health || !summary.server_health.length">
        <div class="sc-empty">
          <div class="sc-empty-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#8892a4" stroke-width="1.5"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
          </div>
          <div class="sc-empty-title">{{ __("No servers yet") }}</div>
          <p>{{ __("Add a server to start monitoring health and provisioning sites.") }}</p>
        </div>
      </div>
    </div>

    <!-- ══════ SITES ══════ -->
    <div v-if="tab==='sites'" class="sc-panel">
      <div class="sc-toolbar">
        <div class="sc-toolbar-left">
          <span class="sc-panel-title">{{ __("Sites") }}</span>
          <span class="sc-panel-count">{{ sites.length }}</span>
        </div>
        <div class="sc-toolbar-right">
          <button class="sc-btn sc-btn-primary sc-btn-sm" @click="promptCreateSite">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            {{ __("Create Site") }}
          </button>
        </div>
      </div>

      <!-- Empty -->
      <div v-if="!sites.length" class="sc-empty">
        <div class="sc-empty-icon">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#8892a4" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
        </div>
        <div class="sc-empty-title">{{ __("No sites yet") }}</div>
        <p>{{ __("Create a site to start provisioning on the pool.") }}</p>
        <button class="sc-btn sc-btn-primary sc-btn-sm" @click="promptCreateSite">{{ __("Create Site") }}</button>
      </div>

      <!-- Site rows -->
      <div
        v-for="row in sites"
        :key="row.name"
        class="sc-row"
        :class="{'is-selected': selectedSite===row.name}"
        @click="selectedSite=row.name"
      >
        <div class="sc-row-body">
          <div class="sc-row-header">
            <span class="sc-row-title">{{ row.domain || row.site_name || row.name }}</span>
            <span :class="statusClass(row.status)">{{ row.status }}</span>
          </div>
          <div class="sc-row-meta">
            <span>{{ row.plan || "—" }}</span>
            <span class="dot">·</span>
            <span>{{ row.server || "—" }}</span>
            <span class="dot" v-if="row.job">·</span>
            <a v-if="row.job" href="#" @click.prevent="openJob(row.job); setTab('deployments')">{{ row.job }}</a>
          </div>
        </div>
        <div class="sc-btn-row" @click.stop>
          <button class="sc-btn sc-btn-ghost sc-btn-xs" @click="openDoc('Space Site', row.name)">{{ __("Open") }}</button>
          <button class="sc-btn sc-btn-ghost sc-btn-xs" v-if="row.status==='Active'" @click="siteAction(row.name, 'suspend')">{{ __("Suspend") }}</button>
          <button class="sc-btn sc-btn-ghost sc-btn-xs" v-if="row.status==='Suspended'" @click="siteAction(row.name, 'resume')">{{ __("Resume") }}</button>
          <button class="sc-btn sc-btn-danger sc-btn-xs" v-if="row.status!=='Deleted'" @click="siteAction(row.name, 'delete')">{{ __("Delete") }}</button>
        </div>
      </div>
    </div>

    <!-- ══════ DEPLOYMENTS ══════ -->
    <div v-if="tab==='deployments'" class="sc-panel">
      <div class="sc-toolbar">
        <div class="sc-toolbar-left">
          <span class="sc-panel-title">{{ __("Deployment Jobs") }}</span>
          <span class="sc-panel-count">{{ jobs.length }}</span>
        </div>
        <div class="sc-toolbar-right">
          <button class="sc-btn sc-btn-ghost sc-btn-sm" @click="loadJobs">{{ __("Reload") }}</button>
        </div>
      </div>

      <div v-if="!jobs.length" class="sc-empty">
        <div class="sc-empty-icon">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#8892a4" stroke-width="1.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
        </div>
        <div class="sc-empty-title">{{ __("No deployment jobs") }}</div>
        <p>{{ __("Jobs will appear here when you create or manage sites.") }}</p>
      </div>

      <div
        v-for="row in jobs"
        :key="row.name"
        class="sc-row"
        :class="{'is-selected': selectedJob===row.name}"
        @click="openJob(row.name)"
      >
        <div class="sc-row-body">
          <div class="sc-row-header">
            <span class="sc-row-title">{{ row.job_type }} · {{ row.site }}</span>
            <span :class="statusClass(row.status)">{{ row.status }}</span>
          </div>
          <div class="sc-row-meta">
            <span>{{ row.name }}</span>
            <span class="dot">·</span>
            <span>{{ row.progress || 0 }}%</span>
          </div>
          <div class="sc-progress">
            <div
              class="sc-progress-bar"
              :class="{'is-running': row.status==='Running' || row.status==='Pending'}"
              :style="{width: (row.progress||0)+'%'}"
            ></div>
          </div>
        </div>
        <div class="sc-btn-row" @click.stop>
          <button class="sc-btn sc-btn-ghost sc-btn-xs" @click="openDoc('Space Deployment Job', row.name)">{{ __("Form") }}</button>
        </div>
      </div>

      <!-- Job detail pane -->
      <div class="sc-detail" v-if="jobDetail">
        <div class="sc-toolbar">
          <div class="sc-toolbar-left">
            <span class="sc-panel-title">{{ jobDetail.name }}</span>
            <span :class="statusClass(jobDetail.status)">{{ jobDetail.status }}</span>
            <span class="sc-panel-count">{{ jobDetail.progress || 0 }}%</span>
          </div>
          <div class="sc-toolbar-right">
            <button class="sc-btn sc-btn-ghost sc-btn-xs" @click="refreshJobDetail">{{ __("Poll") }}</button>
          </div>
        </div>
        <pre class="sc-pre">{{ jobDetail.output || jobDetail.error_log || __("No output yet…") }}</pre>
      </div>
    </div>

    <!-- ══════ SERVERS ══════ -->
    <div v-if="tab==='servers'" class="sc-panel">
      <div class="sc-toolbar">
        <span class="sc-panel-title">{{ __("Servers") }}</span>
        <span class="sc-panel-count">{{ servers.length }}</span>
      </div>

      <div v-if="!servers.length" class="sc-empty">
        <div class="sc-empty-icon">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#8892a4" stroke-width="1.5"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
        </div>
        <div class="sc-empty-title">{{ __("No servers") }}</div>
        <p>{{ __("Register a server to begin provisioning.") }}</p>
      </div>

      <div class="sc-row" v-for="row in servers" :key="row.name">
        <div class="sc-row-body">
          <div class="sc-row-header">
            <span class="sc-row-title">{{ row.title || row.name }}</span>
            <span :class="statusClass(row.health || row.status)">{{ row.health || row.status }}</span>
            <span v-if="row.is_default" style="font-size:.72rem;padding:2px 8px;border-radius:20px;background:rgba(124,92,252,.15);color:#7c5cfc;font-weight:600;">Default</span>
          </div>
          <div class="sc-metrics">
            <div class="sc-metric">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
              CPU {{ row.cpu_used_percent || 0 }}%
              <div class="sc-metric-bar"><span :class="metricBarClass(row.cpu_used_percent||0)" :style="{width: Math.min(row.cpu_used_percent||0,100)+'%'}"></span></div>
            </div>
            <div class="sc-metric" v-if="row.ram_used_mb">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><line x1="6" y1="4" x2="6" y2="20"/><line x1="10" y1="4" x2="10" y2="20"/><line x1="14" y1="4" x2="14" y2="20"/><line x1="18" y1="4" x2="18" y2="20"/></svg>
              RAM {{ Math.round((row.ram_used_mb||0)/1024*10)/10 }} GB
            </div>
            <div class="sc-metric">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
              {{ row.active_sites || 0 }} sites
            </div>
            <div class="sc-metric">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
              {{ row.ip_address || "—" }}
            </div>
          </div>
        </div>
        <div class="sc-btn-row" @click.stop>
          <button class="sc-btn sc-btn-ghost sc-btn-xs" @click="openDoc('Space Server', row.name)">{{ __("Open") }}</button>
          <button class="sc-btn sc-btn-ghost sc-btn-xs" @click="serverAction(row.name, 'test_connection')">{{ __("Test") }}</button>
          <button class="sc-btn sc-btn-ghost sc-btn-xs" @click="serverAction(row.name, 'refresh_statistics')">{{ __("Stats") }}</button>
        </div>
      </div>
    </div>

    <!-- ══════ PLANS & BILLING ══════ -->
    <div v-if="tab==='billing'">

      <!-- Plans grid -->
      <div class="sc-panel" style="margin-bottom:20px">
        <div class="sc-toolbar">
          <div class="sc-toolbar-left">
            <span class="sc-panel-title">{{ __("Plans") }}</span>
            <span class="sc-panel-count">{{ plans.length }}</span>
          </div>
        </div>

        <div v-if="!plans.length" class="sc-empty">
          <div class="sc-empty-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#8892a4" stroke-width="1.5"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
          </div>
          <div class="sc-empty-title">{{ __("No plans configured") }}</div>
        </div>

        <div class="sc-plans-grid">
          <div class="sc-plan-card" v-for="p in plans" :key="p.name" @click="openDoc('Space Plan', p.name)">
            <div class="sc-plan-name">{{ p.title || p.name }}</div>
            <div class="sc-plan-price">
              {{ p.mock_price || ("$" + (p.monthly_price||0)) }}
              <span v-if="!p.mock_price">/ mo</span>
            </div>
            <ul class="sc-plan-features">
              <li class="sc-plan-feature" v-if="p.storage_mb">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                {{ p.storage_mb }} MB disk
              </li>
              <li class="sc-plan-feature" v-if="p.cpu_limit">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                {{ p.cpu_limit }} CPU
              </li>
              <li class="sc-plan-feature" v-if="p.ram_mb">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                {{ Math.round(p.ram_mb/1024*10)/10 }} GB RAM
              </li>
            </ul>
          </div>
        </div>
      </div>

      <!-- Subscriptions -->
      <div class="sc-panel">
        <div class="sc-toolbar">
          <div class="sc-toolbar-left">
            <span class="sc-panel-title">{{ __("Subscriptions") }}</span>
            <span class="sc-panel-count">{{ subscriptions.length }}</span>
          </div>
        </div>

        <div v-if="!subscriptions.length" class="sc-empty">
          <div class="sc-empty-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#8892a4" stroke-width="1.5"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>
          </div>
          <div class="sc-empty-title">{{ __("No subscriptions") }}</div>
        </div>

        <div class="sc-row" v-for="s in subscriptions" :key="s.name" @click="openDoc('Space Subscription', s.name)">
          <div class="sc-row-body">
            <div class="sc-row-header">
              <span class="sc-row-title">{{ s.customer }}</span>
              <span :class="statusClass(s.status)">{{ s.status }}</span>
            </div>
            <div class="sc-row-meta">
              <span>{{ s.plan }}</span>
              <span class="dot">·</span>
              <span>{{ s.payment_status }}</span>
              <span class="dot" v-if="s.end_date">·</span>
              <span v-if="s.end_date">{{ __("Ends") }} {{ s.end_date }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

  </div><!-- /sc-content -->
</div><!-- /sc-page -->
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
