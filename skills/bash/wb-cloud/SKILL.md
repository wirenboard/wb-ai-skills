---
name: wb-cloud
description: Wiren Board Cloud — `wb-cloud-agent` cloud agent on the controller. Activation, account binding, connection status, unbinding, cloud connectivity diagnostics. Custom cloud backend.
allowed-tools: Bash Read Write WebFetch
---

# wb-cloud

`wb-cloud-agent` is a service on the controller that maintains a tunnel to Wiren Board Cloud (`https://wirenboard.cloud`) for remote access to web UI and API. Each controller has a cryptographic certificate in protected memory (`ATECCx08`) used to sign the activation.

Load this on: "bind controller to cloud", "activate in wirenboard.cloud", "doesn't open via cloud", "unbind from account", "custom cloud backend", "cloud status", "remote access via wirenboard.cloud".

## Architecture

```
Web UI (wirenboard.cloud)
      ↑ (long-poll/websocket)
      │
      ▼
wb-cloud-agent  ──reads──▶  /etc/wb-cloud-agent.conf  (LOG_LEVEL, CLIENT_CERT_ENGINE_KEY, CLOUD_BASE_URL)
      │
      ├── /var/lib/wb-cloud-agent/device_bundle.crt.pem      (device certificate)
      ├── /var/lib/wb-cloud-agent/providers/<provider>/       (per-provider state)
      │
      └── publishes to MQTT:
          /devices/system__wb-cloud-agent__<provider>/controls/status
                                                           /activation_link
                                                           /cloud_base_url
```

Provider — a specific cloud. By default `wirenboard.cloud`. You can run your own — see below.

## Basic commands

```bash
# Service status
ssh root@<HOST> 'systemctl is-active wb-cloud-agent'

# Config
ssh root@<HOST> 'cat /etc/wb-cloud-agent.conf'

# Device certificate (presence)
ssh root@<HOST> 'ls -la /var/lib/wb-cloud-agent/device_bundle.crt.pem'

# Providers (cloud list)
ssh root@<HOST> 'ls /var/lib/wb-cloud-agent/providers/'

# MQTT status (for a specific provider)
ssh root@<HOST> "mosquitto_sub -F '%t\\t%p' -t '/devices/system__wb-cloud-agent__+/controls/+' -W 3"
```

## Activation (binding to an account)

1. Make sure the service is running and there's internet:
   ```bash
   ssh root@<HOST> 'systemctl is-active wb-cloud-agent && curl -s -m5 https://wirenboard.cloud >/dev/null && echo ok'
   ```

2. If `inactive` — start:
   ```bash
   ssh root@<HOST> 'systemctl enable --now wb-cloud-agent'
   ```

3. Get the activation_link:
   ```bash
   ssh root@<HOST> "mosquitto_sub -t '/devices/system__wb-cloud-agent__wirenboard.cloud/controls/activation_link' -C 1 -W 5"
   ```

4. Open the link in a browser, log in to `wirenboard.cloud`, bind to the account.

5. After binding, `status` changes to `active`:
   ```bash
   ssh root@<HOST> "mosquitto_sub -t '/devices/system__wb-cloud-agent__wirenboard.cloud/controls/status' -C 1 -W 5"
   ```

   Possible `status` values:
   - `unknown` — agent just started, hasn't connected yet.
   - `ok` (or `active`) — tunnel established, controller visible from cloud.
   - `not_activated` — certificate is present, but the device isn't bound to an account.
   - `error` — see logs.

## Unbinding / activation reset

```bash
ssh root@<HOST> 'systemctl stop wb-cloud-agent'
ssh root@<HOST> 'rm -rf /var/lib/wb-cloud-agent/providers/wirenboard.cloud/'
ssh root@<HOST> 'systemctl start wb-cloud-agent'
```

After this, the agent issues a new activation_link. The old binding in the wirenboard.cloud account stays but points to nowhere — delete it manually via the cloud's web UI.

## Custom cloud backend

CLOUD_BASE_URL in `/etc/wb-cloud-agent.conf` points to the cloud address. Default is `https://wirenboard.cloud/`. To switch:

```bash
ssh root@<HOST> 'cat > /etc/wb-cloud-agent.conf' <<'EOF'
{
    "LOG_LEVEL": "INFO",
    "CLIENT_CERT_ENGINE_KEY": "ATECCx08:00:02:C0:00",
    "CLOUD_BASE_URL": "https://my.cloud.example/"
}
EOF
ssh root@<HOST> 'systemctl restart wb-cloud-agent'
```

A custom backend must implement an API compatible with `wirenboard.cloud`. This is rare — usually for self-hosted deployments or test benches. The device's ATECC certificate is still signed by Wiren Board, but it can be verified against your CA if you trust the WB root cert.

## Diagnostics: "not connecting to cloud"

1. **Service active?** `systemctl is-active wb-cloud-agent`. `inactive` → `enable --now`.
2. **Certificate present?** `ls /var/lib/wb-cloud-agent/device_bundle.crt.pem`. No — controller isn't a Wiren Board or ATECC is broken.
3. **Internet outbound?** `curl -s -m5 https://wirenboard.cloud >/dev/null && echo ok`. No — see `/wb-network` (failover, DNS).
4. **Logs**: `journalctl -u wb-cloud-agent -n 100 --no-pager`. Typical errors:
   - `connection refused` / `timeout` — network issue.
   - `Certificate verification failed` — wrong date on the controller (`date`), sync NTP.
   - `Authentication failed` — certificate revoked / device removed from cloud DB.
5. **MQTT publishing?** `mosquitto_sub -t '/devices/system__wb-cloud-agent__wirenboard.cloud/controls/status' -C 1 -W 3`. Empty — agent doesn't reach publication, check logs.

## Related skills

- `/wb-network` — if cloud is unreachable due to internet.
- `/wb-services` — `wb-cloud-agent` is a systemd unit, override-conf and mask/unmask are here.
- `/wb-controller-backup` — `/etc/wb-cloud-agent.conf` is already in core-tar; `/var/lib/wb-cloud-agent/providers/` is generally NOT backed up (a new activation gives new providers state, and that's normal).
- `/wb-troubleshooting` — general diagnostics, kernel mismatch, disk space.

## Pitfalls

- **Time is way off** — TLS handshake to cloud will fail. NTP must work (`systemctl is-active ntp` or `systemd-timesyncd`).
- **VPN on the controller with default route** — may break cloud access if VPN server blocks outbound wirenboard.cloud. Check the route: `ip route get $(getent hosts wirenboard.cloud | awk "{print \$1}")`.
- **CLIENT_CERT_ENGINE_KEY** doesn't need manual editing — it's the certificate address in ATECC, factory-set.
- **Deleting controller in cloud web UI without local reset** — local agent will keep hammering with `Authentication failed`. Do local cleanup of providers/ and restart the agent.
- **Activation link is single-use** — if you clicked but didn't finish, the agent generates a new one on the next request/restart.

## Documentation

- WB Cloud: <https://wirenboard.com/wiki/Wiren_Board_Cloud>
- Remote access: <https://wirenboard.com/wiki/Remote_access>
