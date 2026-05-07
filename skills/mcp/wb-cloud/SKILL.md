---
name: wb-cloud
description: Wiren Board Cloud — `wb-cloud-agent` cloud agent via MCP. Activation, status, unbinding, cloud connectivity diagnostics, custom backend.
allowed-tools: Bash Read Write WebFetch
---

# wb-cloud (MCP)

The Wiren Board cloud agent (`wb-cloud-agent`) via the `wb_cloud_status` MCP tool + associated tools.

Load this when: "bind to cloud", "activate at wirenboard.cloud", "won't open via cloud", "unbind", "custom cloud backend", "cloud status", "remote access".

## Tool routing

| Intent | Tool |
|--------|------|
| Summary status (service, certificate, MQTT controls, providers) | `wb_cloud_status` |
| Service activity | `wb_systemd_unit unit=wb-cloud-agent` |
| Start / stop / restart | `wb_systemd_unit unit=wb-cloud-agent action=start|stop|restart` |
| Enable autostart | `wb_systemd_unit unit=wb-cloud-agent action=enable` |
| Agent logs | `wb_logs unit=wb-cloud-agent` (with `since`/`grep` if needed) |
| Change cloud URL (CLOUD_BASE_URL) | `wb_write_file path=/etc/wb-cloud-agent.conf` |
| Get activation_link (ready URL for the user) | `wb_mqtt_read topic=/devices/system__wb-cloud-agent__<provider>/controls/activation_link` |
| Reset binding | `wb_systemd_unit stop` + `wb_ssh_exec rm -rf /var/lib/wb-cloud-agent/providers/<provider>/` + `wb_systemd_unit start` |

## Scenario: activate (bind to an account)

1. **Summary status**:
   ```
   wb_cloud_status sn=<SN>
   ```
   Check: `serviceActive`, `certPresent`, `providers`, `mqtt.<provider>.status`, `mqtt.<provider>.activation_link`.

2. **If service is inactive** — enable and start:
   ```
   wb_systemd_unit sn=<SN> unit=wb-cloud-agent action=enable
   wb_systemd_unit sn=<SN> unit=wb-cloud-agent action=start
   ```

3. **Take the activation_link** (after start, wait 5-15 sec):
   ```
   wb_mqtt_read sn=<SN> topic=/devices/system__wb-cloud-agent__wirenboard.cloud/controls/activation_link
   ```
   Show the URL to the user — they open it in a browser and bind.

4. **Verify in 30 sec**:
   ```
   wb_cloud_status sn=<SN>
   ```
   `mqtt.wirenboard.cloud.status` should become `ok` (or `active`).

## Scenario: unbind / reset activation

```
wb_systemd_unit sn=<SN> unit=wb-cloud-agent action=stop
wb_ssh_exec sn=<SN> cmd='rm -rf /var/lib/wb-cloud-agent/providers/wirenboard.cloud/'
wb_systemd_unit sn=<SN> unit=wb-cloud-agent action=start
```

After this `wb_cloud_status` will give a new `activation_link` within a minute. Delete the old binding from the wirenboard.cloud account manually.

## Scenario: custom backend

```
wb_write_file sn=<SN> path=/etc/wb-cloud-agent.conf content='{
    "LOG_LEVEL": "INFO",
    "CLIENT_CERT_ENGINE_KEY": "ATECCx08:00:02:C0:00",
    "CLOUD_BASE_URL": "https://my.cloud.example/"
}'
wb_systemd_unit sn=<SN> unit=wb-cloud-agent action=restart
```

This is a rare case — for self-hosted clouds (own API, compatible with wirenboard.cloud).

## Scenario: "doesn't connect to cloud"

1. `wb_cloud_status sn=<SN>` — `serviceActive`, `certPresent`, `mqtt.*.status`.
2. If `serviceActive: false` — `wb_systemd_unit unit=wb-cloud-agent action=start`.
3. If `certPresent: false` — non-WB controller or ATECC broken, escalate to support.
4. `wb_logs unit=wb-cloud-agent lines=50`. Typical errors:
   - `connection refused`/`timeout` → check internet: `wb_network_status pingTarget=wirenboard.cloud` or `wb_ssh_exec curl -s -m5 https://wirenboard.cloud`.
   - `Certificate verification failed` → controller date, NTP. `wb_ssh_exec date; systemctl is-active ntp`.
   - `Authentication failed` → certificate revoked or device removed from cloud DB. Cleanup providers/ + restart.

## Related skills

- `/network` — if cloud is unreachable due to internet.
- `/services` — `wb-cloud-agent` is a systemd unit.
- `/controller-backup` — `/etc/wb-cloud-agent.conf` is already in core-tar.

## Gotchas

- **Time is wrong** — TLS handshake to the cloud will fail. NTP must work.
- **VPN with default route** — can break access to the cloud. `wb_ssh_exec` `ip route get wirenboard.cloud-IP`.
- **`CLIENT_CERT_ENGINE_KEY`** don't change by hand — the certificate address in ATECC is factory-flashed.
- **Removed from Web UI cloud without local reset** — agent keeps banging with `Authentication failed`. Do cleanup providers/ + restart.
- **Activation link is one-shot** — if you didn't finish, the agent generates a new one on restart.

Details (custom backend, providers) — bash-flavor twin `/wb-cloud`.

## Documentation

- WB Cloud: <https://wirenboard.com/wiki/Wiren_Board_Cloud>
- Remote access: <https://wirenboard.com/wiki/Remote_access>
