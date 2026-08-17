# Misha Deployment Boundaries

Misha's desktop intelligence, microphone, owner voice profile, and Ollama model
remain on the owner's Mac. Railway hosts only the minimal health service in
`cloud/health_server.py`; it does not run the desktop agent or receive audio.

## Railway build

- Builder: `Dockerfile.railway`
- Start command: `python -m cloud.health_server`
- Health path: `/health`
- Port: Railway-provided `PORT`, defaulting locally to `8080`
- Container user: unprivileged UID `10001`
- Restart policy: on failure, maximum three retries

## Environment schema

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `PORT` | Railway supplies it | `8080` | Health-service listen port |
| `MISHA_REMOTE_CONFIG_ENABLED` | No | `0` | Explicit opt-in for legacy remote config |
| `DATABASE_URL` | No | unset | Optional remote config database; never commit |

The current Railway health container does not copy the desktop source,
requirements, `.env`, local databases, memory, or voice files into the image.

## Acceptance

Production deployment is complete only after the connected GitHub branch is
pushed, Railway reports a successful deployment, and `/health` returns a JSON
payload with `status: "ok"`. Local tests alone do not satisfy that gate.
