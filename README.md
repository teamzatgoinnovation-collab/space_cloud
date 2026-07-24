# Space Cloud

Hosting vertical for the Space control-plane framework (`space`).

Install on `space.zatgo.online` after `space`:

```bash
bench get-app <space_cloud-git> --branch main
bench --site space.zatgo.online install-app space_cloud
bench --site space.zatgo.online migrate
```

Provides Server / Site / Deployment Job DocTypes, Docker Bench provider, and portal APIs (`space.api.v1` shims remain for compatibility).
