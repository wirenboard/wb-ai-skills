---
name: wb-troubleshooting
description: "General Wiren Board controller diagnostics — failed systemd services, low disk space, kernel/firmware mismatch, Docker, iptables, diagnostic archive (wb-diag-collect), boot issues, web UI inaccessible. Use when user says controller is broken, not working, service down, asks for logs for support, or needs a diagnostic archive. NOT for serial/Modbus (use wb-serial), NOT for network-only issues (use wb-network)."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# troubleshooting

## CRITICAL RULES

> **NEVER call `wb-cli` without `--json` from an agent.**
> Human-mode output is unparseable; always use:
> `wb-cli --json <command>`
> This applies to every call including help: `wb-cli --json <group> --help`.

General diagnostics for issues on a Wiren Board controller. Load this when the user says: "doesn't work", "fix it", "broken", "error", "won't start", "service crashed", "issue with...", "collect diagnostics", "diagnostic archive", "logs and state" — and it's NOT about serial/Modbus (for serial there's `wb-serial` skill).

Don't confuse with backup (`wb-controller-backup`). The diagnostic archive is for analysis and support, not for restore. Collected by the `wb-diag-collect` utility and includes: configs from `/etc`, service logs (wb*, mosquitto, NetworkManager, etc.), output of diagnostic commands (df, ps, ip, dpkg, etc.).

**HOST variable:** in all examples below `<HOST>` means `wirenboard-<SN>.local`, where `<SN>` is the serial number (e.g. `wirenboard-AABBCCDD.local`). Substitute the real address.

## First steps — always

Before fixing — figure out the cause. Don't fix symptoms.

### 0. Quick health check

```bash
ssh root@<HOST> wb-cli --json audit
```

This runs automated checks (failed units, controller identity). If wb-cli is not installed, proceed with manual steps below.

### 0a. Documentation — MANDATORY

**Before any fix** use `WebFetch` on the wiki page of the problem component. For example: Docker — `WebFetch('https://wiki.wirenboard.com/wiki/Docker')`, Modbus — `WebFetch('https://wiki.wirenboard.com/wiki/Modbus')`, Home Assistant — `WebFetch('https://wiki.wirenboard.com/wiki/Home_Assistant')`. Look for "Known issues", "Troubleshooting", "Limitations" sections. If a solution is there — apply it, don't invent your own.

### 1. Kernel mismatch

**The most common cause of issues after upgrade.** Check first:

```bash
ssh root@<HOST> 'echo "running: $(uname -r)"; dpkg -l "linux-image-wb*" 2>/dev/null | grep ^ii | awk "{print \"installed:\", \$3}"'
```

If versions don't match — the controller is on the old kernel. Kernel modules (br_netfilter, iptable_nat, can, i2c, etc.) won't load, Docker/iptables/network may not work. **The only fix is a reboot.** Don't try to work around via modprobe/iptables-legacy — useless under kernel mismatch.

### 2. Disk space

```bash
ssh root@<HOST> "df -h / /mnt/data"
```

`use% > 95%` or free space `< 100 MB` (on a typical 2 GB rootfs) is critical: apt doesn't work, logs aren't written, services crash. Look at percent used, not absolute values — `/` size depends on platform (wb6 — 2 GB, wb7/wb8 — 2 GB, on old builds you can encounter ~700 MB). Cleanup: `apt clean; journalctl --vacuum-time=3d; rm -rf /tmp/*`.

### 3. Failed services

```bash
ssh root@<HOST> "systemctl --failed --no-pager"
```

For each failed unit — two queries (together they give the full picture):
```bash
ssh root@<HOST> "systemctl status <unit> --no-pager"        # exit code, Result, ExecMainStatus — short summary
ssh root@<HOST> "journalctl -u <unit> -n 50 --no-pager"    # detailed logs with the failure cause
```

`systemctl status` for a failed unit itself returns exit code 3 — that's **normal** (systemctl status code, not an ssh error). When automating, don't confuse it with a real connection error.

### 4. Error journal

```bash
ssh root@<HOST> "journalctl -p err --since '1 hour ago' --no-pager"
```

Without `--since`, `journalctl` returns N latest lines regardless of age — they may be week-old errors. Pick the period by context (`'10 minutes ago'`, `'today'`, `'1 hour ago'`).

### 5. Load and memory

```bash
ssh root@<HOST> "uptime; free -h"
```

Load > 4 on WB — overloaded.
```bash
ssh root@<HOST> "top -bn1 | head -20"
```
Shows who's eating CPU.

## Typical issues

| Symptom | First step |
|---|---|
| Service won't start after upgrade | Kernel mismatch -> reboot |
| Docker won't start, iptables errors | First kernel mismatch. If kernel OK — iptables-legacy fix (see below) |
| modprobe: module not found | Kernel mismatch -> reboot |
| apt doesn't work, dpkg lock | `fuser /var/lib/dpkg/lock-frontend` — who holds it. Zombie from interrupted apt: `dpkg --configure -a` |
| Service crashes in a loop | `journalctl -u <unit> -n 100` — look for the cause, don't restart blindly |
| `fstrim.service` failed, `status=64/USAGE` | An entry in `/etc/fstab` points to a physically absent partition (typically `/mnt/sdcard` without an inserted SD). `fstrim --listed-in /etc/fstab` fails before reaching other mount points. Check `mount` and `ls /dev/mmcblk1*`. Cure: remove the line from fstab or drop-in with `ExecStart=/sbin/fstrim --fstab --quiet-unsupported` |
| No network | `ip addr`, `nmcli`, `ping 8.8.8.8`, `cat /etc/resolv.conf` |
| MQTT doesn't work | `systemctl is-active mosquitto`, `wb-cli --json audit` |
| Web UI doesn't open | `systemctl is-active nginx wb-mqtt-homeui` |

## Docker and iptables

If Docker won't start with errors like `Chain 'MASQUERADE' does not exist`, `DOCKER-ISOLATION-STAGE`, `Failed to Setup IP tables` — and kernel mismatch is ruled out:

1. Switch iptables to legacy:
```bash
ssh root@<HOST> "update-alternatives --set iptables /usr/sbin/iptables-legacy && update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy"
```

2. Create the missing NAT rule:
```bash
ssh root@<HOST> "iptables -w10 -t nat -I POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE"
```

3. Restart Docker:
```bash
ssh root@<HOST> "systemctl restart docker && systemctl is-active docker"
```

If that didn't help — reboot:
```bash
ssh root@<HOST> "reboot"
```

More: <https://wiki.wirenboard.com/wiki/Docker>.

## Diagnostic archive

**Collect ONLY in two cases:**
1. The user explicitly asks "send the diag archive" / "diagnostic archive"
2. Composing a bug report — the archive is mandatory as an attachment together with issue-specific logs

In all other cases (diagnosis, root cause, fix) — **don't create the archive**, work with logs directly via SSH.

Collection takes 30-60 seconds, run as a background task:
```bash
ssh root@<HOST> 'systemd-run --unit=wb-ai-job-$(cat /dev/urandom | tr -dc a-z0-9 | head -c8) --collect bash -c "wb-diag-collect /tmp/diag"'
```

`wb-diag-collect` takes the argument as a **prefix** and itself appends `_SN_DATE.zip` — the actual name isn't known in advance.

After completion — find the file and download:
```bash
ssh root@<HOST> "ls /tmp/diag*.zip | tail -1"
```
Then copy:
```bash
scp root@<HOST>:<path from ls output> ./
```

## Principle

Diagnose -> read documentation -> explain the cause -> propose a solution -> wait for confirmation. Don't fix blindly.
