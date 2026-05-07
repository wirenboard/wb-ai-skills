---
name: services
description: Managing systemd services and timers on a Wiren Board controller. Creating override-conf, drop-ins, custom units and timers. Enable, disable, mask. NOT for diagnostics (for that use `/troubleshooting`).
allowed-tools: Bash Read Write WebFetch
---

# services

systemd on a Wiren Board controller: managing existing units, creating your own services and timers, override-conf for packaged units.

Load this on: "make a service from my script", "add a backup timer", "unmask `<unit>`", "make an override on ExecStart", "after package restart my override is gone", "timer doesn't fire", "how to make X happen at boot".

**Don't confuse with `/troubleshooting`** (failed services, kernel mismatch, journal) and `/controller-update` (apt upgrade).

## Basic commands

```bash
ssh root@<HOST> 'systemctl is-active <unit>'
ssh root@<HOST> 'systemctl status <unit> --no-pager'
ssh root@<HOST> 'systemctl cat <unit>'                # all .service files and drop-ins actually applied
ssh root@<HOST> 'systemctl show <unit> -p ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths --no-pager'
ssh root@<HOST> 'systemctl list-dependencies <unit> --no-pager'
ssh root@<HOST> 'journalctl -u <unit> -n 50 --no-pager'   # also see `/troubleshooting`
```

`systemctl status` for a failed unit returns exit 3 — that's a **state code, not an ssh error**.

## Override-conf (drop-in) — the right way to modify a packaged unit

Never edit `/lib/systemd/system/<unit>.service` directly — apt overwrites it on upgrade. Use a drop-in:

```bash
ssh root@<HOST> 'mkdir -p /etc/systemd/system/<unit>.service.d'
ssh root@<HOST> 'cat > /etc/systemd/system/<unit>.service.d/override.conf' <<'EOF'
[Service]
Restart=on-failure
RestartSec=10s
EOF
ssh root@<HOST> 'systemctl daemon-reload && systemctl restart <unit>'
```

**To clear a directive from the main file, redeclare it as empty**:

```ini
[Service]
ExecStart=
ExecStart=/usr/local/bin/my-wrapped-service
```

(The first line with empty value resets the old `ExecStart`, the second sets the new one. Without the reset, systemd appends the second to the first.)

Apply and verify: `daemon-reload`, `restart`, `systemctl cat <unit>` (is the drop-in visible), `systemctl show <unit> -p ExecStart`.

### fstrim.service / `status=64/USAGE` example override

```bash
ssh root@<HOST> 'mkdir -p /etc/systemd/system/fstrim.service.d'
ssh root@<HOST> 'cat > /etc/systemd/system/fstrim.service.d/override.conf' <<'EOF'
[Service]
ExecStart=
ExecStart=/sbin/fstrim --fstab --quiet-unsupported
EOF
ssh root@<HOST> 'systemctl daemon-reload && systemctl reset-failed fstrim.service'
```

`--quiet-unsupported` skips physically absent mount points (typical case — `/mnt/sdcard` without an SD card).

## Create your own service from a script

1. **Script** — put in `/usr/local/bin/<name>.sh`, owner root, mode 0755:

```bash
ssh root@<HOST> 'cat > /usr/local/bin/my-task.sh' <<'EOF'
#!/bin/bash
set -e
echo "[$(date -Is)] doing the thing"
# ... work ...
EOF
ssh root@<HOST> 'chmod 0755 /usr/local/bin/my-task.sh'
```

2. **Unit** — `/etc/systemd/system/<name>.service`:

```bash
ssh root@<HOST> 'cat > /etc/systemd/system/my-task.service' <<'EOF'
[Unit]
Description=My periodic task
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/my-task.sh
StandardOutput=journal
StandardError=journal
EOF
ssh root@<HOST> 'systemctl daemon-reload'
```

`Type=oneshot` — for one-shot tasks (typical case under a timer). For long-running services — `Type=simple` (default) or `Type=notify` (if the binary supports sd_notify).

3. **Run manually for verification**:

```bash
ssh root@<HOST> 'systemctl start my-task && systemctl status my-task --no-pager -n 20'
```

## Create a timer

A timer is a separate unit `<name>.timer` that runs the same-named `<name>.service` (or another via `Unit=`).

```bash
ssh root@<HOST> 'cat > /etc/systemd/system/my-task.timer' <<'EOF'
[Unit]
Description=Run my-task every hour

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=2min

[Install]
WantedBy=timers.target
EOF
ssh root@<HOST> 'systemctl daemon-reload && systemctl enable --now my-task.timer'
```

- `OnCalendar=hourly` — once per hour (`@hourly` in cron). Full syntax: `OnCalendar=*-*-* 03:00:00` (daily at 03:00), `Mon..Fri 08:00`, `*-*-1 12:00` (1st of the month at 12:00). Verify: `systemd-analyze calendar 'Mon..Fri 08:00'`.
- `Persistent=true` — if the controller was off when the trigger should fire, the timer fires immediately on boot.
- `RandomizedDelaySec` — randomizes start (useful when several controllers hit one server).

`OnBootSec=2min` / `OnUnitActiveSec=10min` are alternatives for "X after boot" / "every X after the previous trigger".

**List timers and next firing**:

```bash
ssh root@<HOST> 'systemctl list-timers --no-pager'
```

## wb-rules cron vs systemd timer

| Case | What to choose |
|--------|--------------|
| Condition depends on MQTT state, dev[], timers and other rules | wb-rules `cron(...)` or `setInterval` (see `/wb-rules`) |
| Simple shell command on a schedule | systemd timer (this skill) |
| Backup, sync, monitoring — task not tied to the bus | systemd timer |
| Need to run a task at boot + then daily | systemd timer (`OnBootSec=` + `OnCalendar=`) |
| React to a control change / bus event | wb-rules `whenChanged` (no cron at all) |

## Enable / disable / mask

```bash
ssh root@<HOST> 'systemctl enable <unit>'      # autostart at boot
ssh root@<HOST> 'systemctl disable <unit>'     # remove from autostart
ssh root@<HOST> 'systemctl mask <unit>'        # forbid start (even by deps) — symlink to /dev/null
ssh root@<HOST> 'systemctl unmask <unit>'      # cancel mask
ssh root@<HOST> 'systemctl reset-failed <unit>'  # clear failed status (without restart)
```

`mask` is stronger than `disable` — it makes the unit "non-existent", even dependent services won't start it. Use it when you need to disable a packaged service that other services would otherwise start (e.g. disable `bluetooth.service` on headless controllers).

## List of enabled units

```bash
ssh root@<HOST> 'systemctl list-unit-files --state=enabled --no-legend | awk "{print \$1}" | sort'
```

To understand "what extra is running" — compare with the typical WB set.

## After a package upgrade

Overrides and custom units in `/etc/systemd/system/` **survive** apt upgrade — the package may change `/lib/systemd/system/<unit>.service`, but the drop-in stays in effect.

If after an upgrade the packaged unit didn't pick up the override — `systemctl daemon-reload && systemctl restart <unit>`.

**Custom units in `/etc/systemd/system/`** do not survive a FIT flash (it overwrites rootfs). For backup — see `/controller-backup`, "Custom systemd units" section.

## Pitfalls

- **Editing `/lib/systemd/system/<unit>.service` directly** — overwritten by apt. Only drop-ins.
- **`ExecStart=` in a drop-in without reset** — appends a second command to the first. First an empty `ExecStart=` line, then the new one.
- **Forgot `daemon-reload`** — systemd doesn't see changes. After any .service/.timer edit.
- **`enable` without `--now`** — unit is enabled but didn't start in this session. `enable --now` or a separate `start`.
- **`OnCalendar` wrong** — verify with `systemd-analyze calendar '<expr>'` before deploying.
- **Type=oneshot without `RemainAfterExit=yes`** — after successful execution the unit is "inactive (dead)", not active. That's normal for a timer, but if you expect to see active — set `RemainAfterExit=yes`.
- **Custom unit without `[Install]` section** — `enable` will fail with "No installation information found".
- **mask without subsequent unmask** — forgotten masks break services on the next upgrade.

## Documentation

- systemd unit syntax: <https://www.freedesktop.org/software/systemd/man/systemd.unit.html>
- systemd timer syntax: <https://www.freedesktop.org/software/systemd/man/systemd.timer.html>
- OnCalendar format: <https://www.freedesktop.org/software/systemd/man/systemd.time.html>
