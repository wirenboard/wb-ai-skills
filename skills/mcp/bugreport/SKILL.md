---
name: bugreport
description: Compose a bug report for Wiren Board support via MCP — data collection, diagnostic archive, formatting.
allowed-tools: Bash Read Write WebFetch
---

# bugreport (MCP)

Compose a bug report for Wiren Board support via MCP tools.

## Principle

Collect as much as possible yourself via MCP tools (`wb_probe`, `wb_audit`, `wb_failed`, `wb_logs`); ask the user as little as possible. The list in step 4 is a **fallback** for items auto-diagnosis didn't cover.

**Before changing anything** on a production controller to test a hypothesis — `wb_state_save` (short snapshot, see `/controller-backup`).

## Tool routing

| Intent | Tool |
|--------|------|
| HW + firmware version + release | `wb_probe` |
| Audit: packages, services, custom files | `wb_audit` |
| Metrics: load, RAM, disk | `wb_metrics` |
| List of failed units | `wb_failed` |
| Logs of a specific service | `wb_logs` |
| Error journal (priority=err for a period) | `wb_ssh_exec` `journalctl -p err --since "1 hour ago" --no-pager` |
| Snapshot "before bug" (if reproduces after action) | `wb_state_save` |
| State diff | `wb_state_diff` |
| Diagnostic archive collection (`wb-diag-collect`, minutes) | `wb_ssh_exec_async` |

## Procedure

### 1. Collect controller passport

- `wb_probe sn=<SN>` — SN, hostname, release, kernel, fw, uptime.
- `wb_metrics sn=<SN>` — disk, load, memory.
- `wb_failed sn=<SN>` — failed services.
- `wb_ssh_exec sn=<SN> cmd='journalctl -p err --since "1 hour ago" --no-pager'` — errors for the last hour.

If the problem is with a specific service:
```
wb_ssh_exec sn=<SN> cmd='systemctl status <unit> --no-pager'
wb_logs sn=<SN> unit=<unit> lines=100
```

Kernel mismatch (frequent cause of post-update problems): `wb_ssh_exec sn=<SN> cmd='echo "running: $(uname -r)"; dpkg -l "linux-image-wb*" | grep ^ii'`. Or just `wb_audit` — it will flag the discrepancy.

Package drift and custom files: `wb_audit sn=<SN>`.

### 2. Collect a diagnostic archive (if needed)

`wb-diag-collect <prefix>` accepts a **filename prefix**, not a directory. The actual file lands in the **parent directory of the prefix** under the name `<prefix>_<SN>_<TS>.zip`.

```
wb_ssh_exec sn=<SN> cmd='mkdir -p /mnt/data/ai/wb-ai-skills'
wb_ssh_exec_async sn=<SN> cmd='wb-diag-collect /mnt/data/ai/wb-ai-skills/diag'
```

Wait for completion (`wb_job_status job_id=<id>` → `exited`). Find the actual filename:

```
wb_ssh_exec sn=<SN> cmd='ls -t /mnt/data/ai/wb-ai-skills/diag_*.zip 2>/dev/null | head -1'
```

Download **only the latest** archive with local `scp` (it's hundreds of KB — `wb_read_file` will fail on the 64 KB limit):

```bash
scp root@wirenboard-<SN>.local:<full path from ls> /tmp/<SN>-bugreport-$(date +%Y-%m-%d).zip
```

Don't do `scp ...:/.../diag*.zip ./` — the glob expands on the remote side and downloads all old archives.

**What the diag archive covers:**
- `last_logs.log` / `last_logs.previous-boot.log` — journal of current and previous boot.
- `dmesg.log` / `dmesg.previous-boot.log` — kernel ring buffer.
- `service/<unit>.service.log` — journal for each **WB service** (mosquitto, wb-mqtt-*, wb-rules, wb-device-manager, etc.).
- `etc/`, `usr/lib/`, `static/` — configs, versions, revision description.
- `dpkg_l.log`, `df_h.log`, `free.log`, `ps_aux.log`, NetworkManager configs, eMMC EXT_CSD.

**What's NOT in the archive** (collect separately):
- Non-WB systemd units (`fstrim.service`, custom `*.service`).
- Docker container logs (`nodered`, `zigbee2mqtt`-in-Docker, etc.).
- Long-period priority filtering (over a week/month).
- MQTT state snapshots.

**Targeted collection of what's missing from the archive:**

```
# Full journal of a non-WB unit (specify unit):
wb_logs sn=<SN> unit=<unit> lines=500
# Or if a long period with filter is needed:
wb_ssh_exec sn=<SN> cmd='journalctl -u <unit> --no-pager --since "1 month ago"'

# Docker container logs:
wb_ssh_exec sn=<SN> cmd='docker logs --tail 1000 --timestamps <container>'

# All errors for a week:
wb_ssh_exec sn=<SN> cmd='journalctl -p err --since "7 days ago" --no-pager'

# MQTT state snapshot (for device-related bugs):
wb_mqtt_devices sn=<SN>
wb_mqtt_list sn=<SN> prefix=zigbee2mqtt/bridge/
```

Attach to the bug report **the archive + extra collected logs** under clear names.

**When the archive isn't needed:** for a failed systemd unit, `wb_logs unit=<unit>` + `wb_ssh_exec` `systemctl status <unit>; systemctl cat <unit>` is often enough. A hundreds-of-KB archive is eMMC load; collect if support asks or if the cause isn't localized within 5 minutes.

### 3. Describe the problem

You already know what happened from the dialog context. Describe it yourself, don't ask again.

### 4. Ask only what **cannot** be learned from the controller

This list is a fallback. First check yourself via tools.

- **Severity** and context: production or test bench.
- **Physical wiring** (bus photo, PSU type — if the issue is hardware).
- **What they see in the browser/screen** (screenshot — if UI issue).
- **Reproducibility** — if not obvious from log timestamps.
- **What was already tried** as a workaround.
- **Desired outcome**: package fix / temporary workaround / can they reboot in the evening.
- **Where the response should go**: ticket to support@wirenboard.com / forum / Telegram.

Ask in a single list.

### 5. Format the bug report

Template:

```
**Subject:** <SN> — <short symptom in one line>

1. **Hardware** — SN, release (`wb-XXXX`/target), kernel, fw, versions of relevant packages (e.g. `util-linux`, `wb-mqtt-serial`), uptime, what's connected (from `wb_probe`+`wb_audit`+`wb_mqtt_devices`), severity.
2. **Actions** — what was done (or "normal operation without intervention").
3. **Expected** — what should have happened.
4. **Actual** — what happened, with `journalctl`/`systemctl status` quotes. Absolute timestamps.
5. **Reproducibility** — yes/no, how often, periodicity (for systemd timers — failure dates).
6. **Minimal configuration** — can extras be disabled.
7. **What was already tried** — workarounds.
8. **Desired outcome** — package fix / override unit / FIT build change.
9. **Diagnostics** — diag archive name (if any) and SHA-256, deviations from stock (`wb_audit`), `wb_state_diff` if a snapshot exists.
```

Show to the user for review.

## Related skills

- `/troubleshooting` — general diagnostics (kernel mismatch, disk, failed units).
- `/troubleshooting-serial` — if symptom involves Modbus/RS-485 (debug session + scan, not a diag archive).
- `/controller-backup` — safety snapshot before any changes to `/etc/*`.
- `/controller-update` — recon without upgrade, to check "would a fresh package fix it".
- `/wiren-board` — master with mDNS warm-up and general SSH etiquette.
