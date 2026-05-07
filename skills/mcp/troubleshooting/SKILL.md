---
name: troubleshooting
description: "General problem diagnostics on a Wiren Board controller via MCP. Failed services, low disk space, kernel mismatch, Docker, iptables, diagnostic archive. NOT for serial/Modbus — use troubleshooting-serial for that."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# troubleshooting (MCP)

General problem diagnostics on a Wiren Board controller via `wb_*` MCP tools. Load this when the user says: "doesn't work", "fix it", "broken", "error", "won't start", "service crashed", "problem with...", "collect diagnostics", "diagnostic archive", "logs and state" — and it's NOT about serial/Modbus (for serial use `/troubleshooting-serial`).

Don't confuse with backup (`/controller-backup`). A diagnostic archive is for analysis and support, not for restore. It's collected by `wb-diag-collect` and includes: configs from `/etc`, service logs (wb*, mosquitto, NetworkManager, etc.), output of diagnostic commands (df, ps, ip, dpkg, etc.).

## Tool routing

| Intent | Tool |
|--------|------|
| Metrics (load, RAM, disk) | `wb_metrics` |
| List of failed units | `wb_failed` |
| Logs of a specific service (`journalctl -u`) | `wb_logs` |
| Audit: packages, services, custom files | `wb_audit` |
| Arbitrary diagnostic command (short) | `wb_ssh_exec` |
| Long (`wb-diag-collect`, `apt-get`) | `wb_ssh_exec_async` → `wb_job_tail` |
| Read `/etc/resolv.conf`, `/etc/wb-mqtt-*` | `wb_read_file` |
| Is MQTT alive? | `wb_mqtt_list` (if it returns topics — broker is alive) |

## First steps — always

Before fixing — figure out the cause. Don't fix symptoms.

### 0. Documentation — MANDATORY

**Before any fix** do `WebFetch` on the page of the problematic component in the WB wiki. For example: Docker — `WebFetch('https://wiki.wirenboard.com/wiki/Docker')`, Modbus — `WebFetch('https://wiki.wirenboard.com/wiki/Modbus')`, Home Assistant — `WebFetch('https://wiki.wirenboard.com/wiki/Home_Assistant')`. Look for "Known issues", "Troubleshooting", "Limitations" sections. If a solution is there — apply it, don't invent your own.

### 1. Kernel mismatch

**The most frequent cause of post-update problems.** Check first:

```
wb_ssh_exec sn=<SN> cmd='echo "running: $(uname -r)"; dpkg -l "linux-image-wb*" 2>/dev/null | grep ^ii | awk "{print \"installed:\", \$3}"'
```

If versions don't match — the controller is running on the old kernel. Kernel modules (br_netfilter, iptable_nat, can, i2c, etc.) won't load, Docker/iptables/network may not work. **The only solution is reboot.** Don't try to bypass via modprobe/iptables-legacy — useless under kernel mismatch.

`wb_audit` will also flag the kernel version mismatch.

### 2. Disk space

`wb_metrics` returns current free space on `/` and `/mnt/data`. Rootfs < 100 MB — critical: apt doesn't work, logs aren't written, services fail. Cleanup via `wb_ssh_exec_async` `cmd='apt clean; journalctl --vacuum-time=3d; rm -rf /tmp/*'`.

### 3. Failed services

`wb_failed` — list of failed units. For each, both status and logs are needed (status gives exit code, Result, ExecMainStatus — short summary; the journal — details):

```
wb_ssh_exec sn=<SN> cmd='systemctl status <unit> --no-pager'
wb_logs sn=<SN> unit=<unit> lines=50
```

`systemctl status` for a failed unit returns exit code 3 — that's **normal** (a systemctl status code), not an ssh error. `wb_ssh_exec` will return `code: 3` in the result.

### 4. Error journal

```
wb_ssh_exec sn=<SN> cmd='journalctl -p err --since "1 hour ago" --no-pager'
```

Without `--since` journals can go back days/weeks. Choose the period by context (`'10 minutes ago'`, `'today'`, `'1 hour ago'`). `wb_logs` itself accepts `unit`/`lines`/`priority`, but a time window is more reliable via direct `journalctl --since` through `wb_ssh_exec`.

### 5. Load and memory

`wb_metrics` returns load and memory. Load > 4 on WB — overload. Who eats CPU:

```
wb_ssh_exec sn=<SN> cmd='top -bn1 | head -20'
```

## Typical problems

| Symptom | First step |
|---------|-----------|
| Service won't start after update | Kernel mismatch → reboot |
| Docker doesn't start, iptables errors | Kernel mismatch first. If kernel OK — iptables-legacy fix (see below) |
| modprobe: module not found | Kernel mismatch → reboot |
| apt doesn't work, dpkg lock | `wb_ssh_exec` `fuser /var/lib/dpkg/lock-frontend` — who holds it. Zombie from interrupted apt: `wb_ssh_exec_async` `dpkg --configure -a` |
| Service crashes in a loop | `wb_logs unit=<unit> lines=100` — find the cause, don't restart blindly |
| `fstrim.service` failed, `status=64/USAGE` | An `/etc/fstab` entry points to a physically absent partition (typically `/mnt/sdcard` without SD). `fstrim --listed-in /etc/fstab` fails before reaching the rest. Check `wb_ssh_exec` `mount; ls /dev/mmcblk1*`. Cure: remove the line from fstab or drop-in with `ExecStart=/sbin/fstrim --fstab --quiet-unsupported` |
| No network | `wb_ssh_exec` `ip addr; nmcli; ping -c2 8.8.8.8`; `wb_read_file` `/etc/resolv.conf` |
| MQTT doesn't work | `wb_ssh_exec` `systemctl is-active mosquitto`; `wb_mqtt_list` |
| Web UI doesn't open | `wb_ssh_exec` `systemctl is-active nginx wb-mqtt-homeui` |

## Docker and iptables

If Docker doesn't start with errors like `Chain 'MASQUERADE' does not exist`, `DOCKER-ISOLATION-STAGE`, `Failed to Setup IP tables` — and kernel mismatch is excluded:

1. Switch iptables to legacy (with confirmation):

   ```
   wb_ssh_exec sn=<SN> cmd='update-alternatives --set iptables /usr/sbin/iptables-legacy && update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy'
   ```

2. Create the missing NAT rule:

   ```
   wb_ssh_exec sn=<SN> cmd='iptables -w10 -t nat -I POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE'
   ```

3. Restart Docker:

   ```
   wb_ssh_exec sn=<SN> cmd='systemctl restart docker && systemctl is-active docker'
   ```

If that didn't help — reboot (`wb_ssh_exec` `reboot`, wait for disconnect, then `wb_probe`).

More: <https://wiki.wirenboard.com/wiki/Docker>.

## Diagnostic archive

**Collect ONLY in two cases:**
1. The user explicitly asks for "send diag archive" / "diagnostic archive".
2. A bug report is being composed (`/bugreport`) — the archive is mandatory as an attachment.

In all other cases (diagnostics, root-cause search, fixing) — **don't create the archive**, work with logs directly via `wb_logs`.

Collection takes 30-60 seconds:

```
wb_ssh_exec_async sn=<SN> cmd='wb-diag-collect /tmp/diag'
```

`wb-diag-collect` takes the argument as a **prefix** and appends `_SN_DATE.zip`. Find the actual name after completion:

```
wb_job_status job_id=<id>     # wait for exited
wb_ssh_exec sn=<SN> cmd='ls -1 /tmp/diag*.zip | tail -1'
```

Download the archive via local `scp` (outside MCP) or `wb_read_file` if the archive fits in 64 KB (usually not — it's tens of MB, use scp):

```bash
scp root@wirenboard-<SN>.local:<path> ./
```

## Principle

Diagnose → read documentation → explain the cause → propose a solution → wait for confirmation. Don't fix blindly.
