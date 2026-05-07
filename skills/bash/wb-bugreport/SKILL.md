---
name: wb-bugreport
description: Composing a bug report for Wiren Board support — data collection, diag archive, formatting.
allowed-tools: Bash Read Write WebFetch
---

# bugreport

Composing a bug report for Wiren Board support.

## Principle

Collect as much as possible yourself via the `/wb-troubleshooting`, `/wb-troubleshooting-serial`, `/wiren-board` skills and the mDNS warm-up from the master skill; ask as little as possible. The list in step 4 is a **fallback** for cases when self-diagnostics didn't yield an answer for a specific item.

**Before changing anything** on a production controller to test a hypothesis — `/wb-controller-backup` (a short snapshot via step 1b).

## Order

### 1. Collect the controller passport

State snapshot (single SSH call, save the output to a file — useful for the template):

```bash
ssh root@<HOST> 'echo "=== HW ==="; cat /var/lib/wirenboard/short_sn.conf 2>/dev/null; cat /usr/lib/wb-release 2>/dev/null; echo "Kernel: $(uname -r)"; echo "FW: $(cat /etc/wb-fw-version 2>/dev/null)"; echo "Uptime:"; uptime; echo "=== DISK ==="; df -h / /mnt/data; echo "=== FAILED ==="; systemctl --failed --no-pager; echo "=== ERRORS (last hour) ==="; journalctl -p err --since "1 hour ago" --no-pager' | tee /tmp/wb-snapshot-<SN>-$(date +%Y%m%d).txt
```

For a specific failed service:
```bash
ssh root@<HOST> "systemctl status <unit> --no-pager; journalctl -u <unit> --since '1 day ago' --no-pager"
```

Kernel mismatch (a frequent cause of issues after upgrade — see `/wb-troubleshooting`):
```bash
ssh root@<HOST> 'echo "running: $(uname -r)"; dpkg -l "linux-image-wb*" 2>/dev/null | grep ^ii'
```

### 2. Collect the diagnostic archive

`wb-diag-collect <prefix>` accepts a **filename prefix**, not a directory. The actual file lands in the **parent directory of the prefix** under the name `<prefix>_<SN>_<TS>.zip`.

```bash
# Collect (background task, ~30-60 sec):
ssh root@<HOST> 'mkdir -p /mnt/data/ai/wb-ai-skills && systemd-run --unit=wb-ai-diag --collect bash -c "wb-diag-collect /mnt/data/ai/wb-ai-skills/diag"'

# Wait for completion and find the actual name of the latest archive:
LATEST=$(ssh root@<HOST> 'ls -t /mnt/data/ai/wb-ai-skills/diag_*.zip 2>/dev/null | head -1')
echo "diag archive: $LATEST"

# Download **only the latest** under a clear name:
scp root@<HOST>:"$LATEST" "/tmp/$(basename $LATEST .zip)-bugreport.zip"
```

Without `LATEST` the glob `diag*.zip` will be expanded on the remote side and download **all** old archives — on A25NDEMJ there are usually 5-6 of them.

**What the diag archive covers:**
- `last_logs.log` / `last_logs.previous-boot.log` — full journal of the current and previous boot.
- `dmesg.log` / `dmesg.previous-boot.log` — kernel ring buffer.
- `service/<unit>.service.log` — journal for each **WB service** (mosquitto, wb-mqtt-*, wb-rules, wb-device-manager, wb-cloud-agent, etc.).
- `etc/`, `usr/lib/`, `static/` — configs, versions, revision description.
- `dpkg_l.log`, `df_h.log`, `free.log`, `ps_aux.log`, `nmcli.log`, dmesgs, NetworkManager configs, eMMC EXT_CSD.

**What is NOT in the archive** (collect separately and attach to the bug report):
- Non-WB systemd units (`fstrim.service`, `apt-daily.service`, custom `*.service`) — their journals aren't in the archive.
- Docker container logs (`nodered`, `zigbee2mqtt`-in-Docker, etc.).
- Long-period priority-filtered samples (a week/month) — `last_logs` only covers the current boot.
- MQTT state snapshots (`mosquitto_sub /devices/+/meta/name`, `bridge/state`).

**Targeted collection of what's missing from the archive:**
```bash
# Full journal of a failed non-WB unit (specify `-u <unit>`):
ssh root@<HOST> "journalctl -u <unit> --no-pager --since '1 month ago'" > /tmp/<unit>.log

# Docker container logs (for nodered/Z2M-in-Docker bug reports):
ssh root@<HOST> "docker logs --tail 1000 --timestamps <container>" 2>&1 > /tmp/<container>.log

# All errors over a week with a filter:
ssh root@<HOST> "journalctl -p err --since '7 days ago' --no-pager" > /tmp/errors-7d.log

# MQTT state snapshot (for device-related bugs):
ssh root@<HOST> "mosquitto_sub -F '%t\t%p' -t '/devices/+/meta/name' -W 5" > /tmp/mqtt-devices.txt
```

Attach to the bug report **the archive + additionally collected logs** under clear names so support doesn't have to search.

**When the archive isn't needed:** for a failed systemd unit, `journalctl -u <unit> --no-pager` + `systemctl status <unit>` + `systemctl cat <unit>` is often enough (e.g. our `fstrim.service` case). An archive of hundreds of KB is load on eMMC; collect it if support asks, or if the cause isn't localized within 5 minutes via step 1.

### 3. Describe the problem

From the dialog context you already know what happened. Describe it yourself, don't ask again.

### 4. Ask only what **cannot** be learned from the controller

This list is a fallback, for items not resolved by step 1. First check yourself via the skills (`/wiren-board`, `/wb-troubleshooting`).

- **Severity** and context: production or test bench, currently affecting users or not.
- **Physical connection** (if it's a hardware issue — bus photo, schematic, PSU type).
- **What is shown in the browser/on the screen** (if it's a UI issue — screenshot).
- **Reproducibility** — if not visible from log timestamps.
- **What was already tried** as a workaround (users often stay quiet on this; ask explicitly).
- **Desired outcome**: package fix / temporary workaround / can it be rebooted in the evening.
- **Where the response goes**: ticket to support@wirenboard.com / forum / Telegram chat.

Ask in a single list, not one question at a time.

### 5. Compose the bug report

Template:

```
**Subject:** <SN> — <short symptom in one line>

1. **Hardware** — SN, release (`wb-XXXX`/target), kernel, fw, versions of relevant packages (e.g. `util-linux`, `wb-mqtt-serial`), uptime, what is connected (Modbus devices, Z2M, Docker projects), severity.
2. **Actions** — what was done (or "normal operation without intervention").
3. **Expected** — what should have happened.
4. **Actual** — what happened, with quotes from `journalctl`/`systemctl status`. Use absolute timestamps.
5. **Reproducibility** — yes/no, how often, periodicity (for systemd timers — failure dates).
6. **Minimum configuration** — can extras be turned off to isolate the issue.
7. **What was already tried** — workarounds (if any).
8. **Desired outcome** — package fix, override unit, FIT image change.
9. **Diagnostics** — diag archive name (if any) and its SHA-256, links to logs.
```

Show it to the user for review.

## Related skills

- `/wb-troubleshooting` — general diagnostics (kernel mismatch, disk, failed units, error journal) — part of step 1 duplicates its commands; if you dig deeper, jump straight there.
- `/wb-troubleshooting-serial` — if the symptom is about Modbus/RS-485 (CRC, timeout) — that's where the debug session lives, no `wb-diag-collect` needed.
- `/wb-controller-backup` — mandatory safety snapshot before any changes to `/etc/*` for hypothesis testing.
- `/wb-controller-update` — if the hypothesis is "a fresh package would fix it", check via recon from `/wb-controller-update` (without running an actual upgrade).
- `/wiren-board` — master skill; if the first ssh command fails with `Could not resolve hostname`, mDNS warm-up is there (`echo "$(timeout 5 avahi-browse -arp 2>/dev/null)"`).
