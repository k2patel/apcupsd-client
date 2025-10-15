# APC UPS Dashboard

A lightweight FastAPI + Redis based dashboard for multiple APC UPS devices using the `apcaccess` CLI (apcupsd Network Information Server mode). Shows real-time metrics, lightweight charts, and maintains 7 days of historical snapshots.

## Features
- Multiple UPS managed dynamically (stored in Redis; add/update/delete via API/UI)
- Polling via `apcaccess` CLI against apcupsd NIS (default port 3551)
- Connection test: TCP port reachability (no protocol parsing)
- Real-time dashboard (Server Sent Events) updating key metrics
- 7-day retention of snapshots in Redis lists
- Simple Chart.js load percentage sparkline
- Docker & docker-compose deployment (image bundles apcupsd + apcaccess)
- SMTP alerting (high load, low battery %, on battery, low runtime) with cooldown

## Configuration

Configuration is persisted in Redis (key `ups:config:json`). Use the web UI or the REST API to manage UPS entries and SMTP settings. A legacy `config/ups.yaml` (or path set via `UPS_CONFIG_PATH`) is imported once on first startup if Redis has no configuration; after migration the file is no longer written or read.

UPS fields:
- name (unique)
- host (apcupsd server hostname / IP)
- port (default 3551)
- interval_seconds (polling interval)
- Optional alert thresholds: alert_loadpct_high, alert_bcharge_low, alert_on_battery, alert_runtime_low_minutes

SMTP fields (optional): host, port, username, password (or env `SMTP_PASSWORD`), use_tls, use_ssl, from_addr, to_addrs[], subject_prefix.

Environment secret: set `SMTP_PASSWORD` instead of storing cleartext.

Alert suppression: identical alert per UPS suppressed for 30 minutes (cooldown).

### apcupsd Server Requirements
Your remote APC UPS hosts must be running `apcupsd` with the Network Information Server (NIS) enabled. Typical steps (on Linux):

1. Install apcupsd (example for Debian/Ubuntu):
  ```bash
  sudo apt-get install apcupsd
  ```
2. Edit `/etc/apcupsd/apcupsd.conf` and confirm at least:
  ```
  UPSTYPE usb            # or 'net' / 'snmp' depending on your setup
  DEVICE                 # usually blank for USB
  NISIP 0.0.0.0          # listen on all interfaces (restrict in firewalled env)
  NISPORT 3551           # must match the configured port (default 3551)
  NETSERVER on           # enable network server
  # Optional: restrict access (recommended)
  ACCESS 192.168.1.0/24  # Only allow your monitoring subnet (supported on some builds)
  ```
3. Restart service:
  ```bash
  sudo systemctl restart apcupsd
  ```
4. Test locally:
  ```bash
  apcaccess status
  nc -vz <server-ip> 3551
  ```

If you receive connectivity errors in logs:
 - Verify `NETSERVER on` is set.
 - Check host firewall (e.g., `ufw allow 3551/tcp`).
 - Confirm the port is correct and reachable from the container network.
 - Test manually:
  ```bash
  nc -vz <server-ip> 3551
  apcaccess -h <server-ip>:3551 status
  ```

### Connection Testing Logic
Simplified: only a raw TCP connect test. If the port is reachable it's reported as success. Polling uses the `apcaccess` CLI for data collection.

## Run (docker-compose)
```bash
docker compose up --build
```
Visit http://localhost:8000

### Persistence

Configuration and historical metrics live in Redis. The provided `docker-compose.yml` now mounts a named volume (`redis-data`) at `/data` inside the Redis container and enables Append Only File (AOF) with `--appendonly yes`.

Data will persist across `docker compose down` / `up` cycles as long as you do NOT remove the volume. To explicitly remove all persisted configuration and history you must prune the volume:

```bash
docker compose down
docker volume rm apcupsd-client_redis-data  # volume name may be prefixed by folder/project
```

If you had been losing configuration previously, ensure you pulled the updated compose file and that the `redis` service includes:

```yaml
  redis:
    volumes:
      - redis-data:/data
    command: ["redis-server", "--appendonly", "yes", "--appendfsync", "everysec"]
```

You can inspect Redis persistence files locally by running:

```bash
docker compose exec redis ls -lh /data
```

If you want to enforce periodic RDB snapshots as well, you can leave default save settings (remove the `--save ""` override). The current configuration uses AOF every second for a balance of durability and write performance.

## Data Storage
Redis stores:
- Latest snapshot hash: `ups:snap:<name>`
- History list (JSON {ts,data}): `ups:hist:<name>`
- Per-minute watts averages: `ups:watts:permin:<name>`
- Energy (watt-seconds) daily totals: `ups:energy:<name>:YYYYMMDD`
- Events list: `ups:event:list:<name>`
- Recent alerts: `ups:alerts:recent:<name>`
- Voltage deviation samples: `ups:volt:dev:samples:<name>`

A pruning task runs hourly removing entries older than 7 days.

## Extending
- Add more charts: query `/api/ups/<name>/history`
- Add gauges: integrate a JS gauge lib in `dashboard.html`
- Alerts: create background task checking thresholds

## License
MIT

## Security & Hardening Notes
| Area | Current | Recommendation |
|------|---------|---------------|
| Authentication | None (open dashboard) | Add reverse proxy auth or FastAPI auth if exposed beyond LAN |
| Config Storage | Redis (JSON) | Protect Redis with auth / network policy |
| Network to apcupsd | Plain TCP | Use network segmentation / firewall; protocol has no encryption |
| Redis | No auth configured | Enable AUTH / TLS if crossing trust boundaries |
| Input Validation | Pydantic for config schema | Add stricter hostname/IP validation if multi-tenant |
| Dependency Versions | Pinned | Review periodically for CVEs |
| Logging | Polling errors logged | Avoid logging secrets; sanitize future additions |

### Additional Notes
- Legacy YAML migration (one-time) to Redis; file no longer updated afterward.
- Dynamic poller reconciles tasks on config change (no restart needed).
- Alert cooldown prevents email flood.
- AOF-based Redis persistence keeps configuration across container rebuilds.

### Suggested Future Enhancements
- Optional Basic Auth / OIDC for web UI.
- Rate limiting on config mutation endpoints.
- CSRF protection if cookies/session auth added later.
- Health endpoint (`/healthz`) returning Redis + config status.
- Structured logging (JSON) for production observability.
