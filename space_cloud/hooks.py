"""Frappe hooks for Space Cloud — hosting vertical on Space core."""

app_name = "space_cloud"
app_title = "Space Cloud"
app_publisher = "ZatGo Innovation"
app_description = "ERPNext site hosting, provisioning, and infrastructure on Space"
app_email = "engineering@zatgo.local"
app_license = "mit"
app_version = "0.1.0"

required_apps = ["space"]

after_install = "space_cloud.install.after_install"
after_migrate = "space_cloud.install.after_migrate"

add_to_apps_screen = [
	{
		"name": "space_cloud",
		"title": "Space Cloud",
		"route": "/app/cloud-manager",
	}
]

# Register with Space core hooks contract
space_provider_types = {
	"docker_bench": "space_cloud.providers.docker_bench_provider.DockerBenchProvider",
}

space_resource_types = {
	"site": "space_cloud.resources.site_resource",
}

space_job_handlers = {
	"create_site": "space_cloud.jobs.provision.run_create_site",
	"suspend_site": "space_cloud.jobs.lifecycle.run_suspend_site",
	"resume_site": "space_cloud.jobs.lifecycle.run_resume_site",
	"delete_site": "space_cloud.jobs.lifecycle.run_delete_site",
}

space_dashboard_cards = [
	"Space Total Servers",
	"Space Total Sites",
	"Space Active Sites",
	"Space Failed Jobs",
	"Space Running Jobs",
]

space_api_namespaces = [
	"space_cloud.api.v1",
	"space_cloud.api.v2",
	"space_cloud.api.v3",
	"space_cloud.api.v4",
]

scheduler_events = {
	"hourly": [
		"space_cloud.jobs.monitoring.refresh_all_health",
		"space_cloud.jobs.marketplace.process_update_queue",
		"space_cloud.services.infrastructure.heartbeat_all",
		"space_cloud.services.infrastructure.evaluate_alerts",
		"space_cloud.jobs.infrastructure.process_migration_queue",
	],
	"daily": [
		"space_cloud.jobs.ssl.check_ssl_all",
		"space_cloud.jobs.backup.cleanup_old_backups",
		"space_cloud.jobs.backup.enqueue_scheduled_backups",
		"space_cloud.jobs.monitoring.refresh_all_health",
		"space_cloud.services.infrastructure.forecast_capacity",
		"space_cloud.services.infrastructure.auto_heal",
		"space_cloud.jobs.infrastructure.process_maintenance_windows",
	],
}
