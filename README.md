# APC UPS Dashboard

A production-ready FastAPI + Redis dashboard for monitoring multiple APC UPS devices via `apcupsd` NIS. Single-admin auth (argon2 + session cookies), CSRF, rate limiting, security headers, SSE live updates, 7-day history, connection-health tracking, battery degradation trends, HTML email alerts with batching and silent-hours, and Prometheus metrics.

## Features

**Monitoring**
- Multiple UPS managed dynamically via UI/REST (stored in Redis)
- Real-time dashboard with SSE, fleet-overview panel, per-UPS state indicators
- 7-day snapshot history, per-minute watts averages, daily energy + cost
- Connection-health tracker — COMMLOST detection after 3× interval, recovery INFO alerts
- Battery-health sampling (1/min) with 7-day trend + decline %
- CSV export (history/events/energy), event log, alert management + ack

**Alerts (email-only)**
- Severity taxonomy: CRITICAL (ONBATT/COMMLOST/RUNTIME_LOW/BCHARGE_LOW), WARNING (LOAD_HIGH/REPLACEBATT/SELFTEST_FAIL/TEMP_HIGH/XFER_BURST/VOLT_DEV), INFO (REACHABLE/LINE_RESTORED)
- Coalesced HTML emails (one per UPS per poll cycle), severity-colored
- 30-min per-message cooldown, silent-hours deferral (CRITICAL always delivered), retries via tenacity
- Test-email button and optional daily summary

**Security & ops**
- Single-admin auth (argon2 password, signed session cookie, double-submit CSRF)
- SSRF host validation (rejects loopback/link-local; private IPs gated by `ALLOW_PRIVATE_IPS`)
- SMTP password **only** from env — never persisted to Redis
- Subprocess timeout on `apcaccess` (10s), rate-limiting on auth/config, security headers + CSP
- Non-root container (UID 10001), pinned `python:3.12.7-slim` multi-stage build
- `/healthz`, `/readyz`, `/metrics` (Prometheus), JSON structured logs with request-ID correlation
- GitHub Actions pipeline runs ruff + pytest before building/publishing the image

## Quick start (docker-compose)

```bash
cp .env.example .env
# Required in production — edit .env:
#   SESSION_SECRET=<run: python -c "import secrets; print(secrets.token_urlsafe(48))">
#   SMTP_PASSWORD=<your SMTP password, if using alerts>
docker compose up --build
```

Open http://localhost:10280 — the app redirects to `/setup` where you create the admin account on first boot. Subsequent visits require login.

## Environment variables

| Var | Required | Default | Notes |
|---|---|---|---|
| `SESSION_SECRET` | yes (prod) | ephemeral | 32+ random bytes, signs session cookies |
| `ADMIN_USERNAME` | no | `admin` | |
| `ADMIN_PASSWORD_HASH` | no | unset | Skip setup wizard by pre-seeding an argon2 hash |
| `REDIS_URL` | no | `redis://redis:6379/0` | Supports `redis://:pw@host:port/db` |
| `SMTP_PASSWORD` | no | unset | Read only from env, never stored |
| `ALLOW_PRIVATE_IPS` | no | `true` | Set false to block RFC1918 UPS hosts |
| `TRUST_PROXY` | no | `false` | Enable Secure cookies + HSTS when behind HTTPS proxy |
| `LOG_LEVEL` | no | `INFO` | DEBUG/INFO/WARNING/ERROR |
| `SESSION_MAX_AGE_SECONDS` | no | `1209600` | 14 days |
| `RATE_LIMIT_ENABLED` | no | `true` | Disable in tests |
| `TZ` | no | `UTC` | |

Generate values:
```bash
# SESSION_SECRET
python -c "import secrets; print(secrets.token_urlsafe(48))"
# ADMIN_PASSWORD_HASH (optional pre-seed)
python -c "from passlib.hash import argon2; print(argon2.hash('mysecret'))"
```

> **Heads-up — `$` escaping in `.env`:** argon2 hashes look like `$argon2id$v=19$m=...$<salt>$<hash>`. Docker Compose treats `$word` as variable substitution in `.env`, so pasting a raw hash produces warnings (`The "argon2id" variable is not set…`) and the container receives a mangled, unverifiable hash — you won't be able to log in. Quoting does **not** help. Either double every `$` (`$$argon2id$$v=19$$m=...`), or skip this variable entirely and use the `/setup` wizard (recommended).

## apcupsd server requirements

Your remote APC UPS hosts must run `apcupsd` with the Network Information Server (NIS) enabled:

1. Install: `sudo apt-get install apcupsd`
2. Edit `/etc/apcupsd/apcupsd.conf`:
   ```
   UPSTYPE usb
   NISIP 0.0.0.0
   NISPORT 3551
   NETSERVER on
   ```
3. Restart: `sudo systemctl restart apcupsd`
4. Test: `apcaccess status` and `nc -vz <server-ip> 3551`

## Development

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# Run tests (uses fakeredis)
pytest tests/

# With coverage
coverage run -m pytest tests/ && coverage report

# Lint
ruff check .

# Local dev server (needs apcaccess binary + REDIS_URL env)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Persistence

Config and history live in Redis via an AOF-backed `redis-data` volume. To wipe state:
```bash
docker compose down && docker volume rm apcupsd-client_redis-data
```

## API (summary)

| Path | Auth | Notes |
|---|---|---|
| `/` (dashboard), `/config`, `/events`, `/alerts`, `/settings` | session | Jinja pages |
| `/login`, `/setup`, `/logout` | open/session | |
| `/healthz`, `/readyz`, `/metrics` | open | Prom metrics on `/metrics` |
| `GET /api/stream` | session | SSE snapshots |
| `GET /api/ups`, `/api/ups/{name}/{status\|history\|events\|energy\|health\|battery_health}` | session | |
| `GET /api/ups/fleet/overview` | session | Aggregate fleet summary |
| `GET /api/ups/{name}/export?format=csv&kind=history\|events\|energy&since_days=N` | session | Streaming CSV |
| `GET /api/events`, `/api/alerts`, `/api/alerts/active` | session | |
| `POST /api/alerts/{id}/ack` | session+CSRF | |
| `GET/POST/PUT/DELETE /api/config/{ups,smtp,ui}/...` | session (+CSRF for writes) | Rate-limited |

## License

MIT
