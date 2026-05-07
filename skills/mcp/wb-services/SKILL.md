---
name: wb-services
description: Managing systemd services and timers on a Wiren Board controller via MCP. Override-conf, drop-ins, custom units and timers, enable/disable/mask. NOT for diagnostics (for diagnostics see `/wb-troubleshooting`).
allowed-tools: Bash Read Write WebFetch
---

# services (MCP)

systemd on a WB controller via the MCP tool `wb_systemd_unit` + `wb_write_file` for override-conf and custom units.

Load this when: "make a service from my script", "add a backup timer", "unmask `<unit>`", "make an override on ExecStart", "after package restart my override is gone", "timer doesn't fire".

**Don't confuse with `/wb-troubleshooting`** (failed services, kernel mismatch, journal) and `/wb-controller-update` (apt upgrade).

## Tool routing

| Intent | Tool |
|--------|------|
| Unit status (parsed) | `wb_systemd_unit unit=<u>` (action=status by default) |
| Unit contents with all drop-ins | `wb_systemd_unit unit=<u> action=cat` |
| Unit dependencies | `wb_systemd_unit unit=<u> action=list-deps` |
| Start / stop / restart / reload | `wb_systemd_unit unit=<u> action=start|stop|restart|reload` |
| Enable / disable autostart | `wb_systemd_unit unit=<u> action=enable|disable` |
| Mask (forbid start) | `wb_systemd_unit unit=<u> action=mask|unmask` |
| Unit logs | `wb_logs unit=<u>` (with `since`/`grep` if needed) |
| Write override.conf or custom unit | `wb_write_file path=/etc/systemd/system/<unit>.service.d/override.conf` or `/etc/systemd/system/<unit>.service` |
| `daemon-reload` after editing .service/.timer | `wb_ssh_exec` `systemctl daemon-reload` |
| List of timers and next firings | `wb_ssh_exec` `systemctl list-timers --no-pager` |

## Scenario: override on a packaged unit

1. `wb_systemd_unit unit=<u> action=cat` — see current .service and existing drop-ins.
2. `wb_write_file path=/etc/systemd/system/<u>.service.d/override.conf` — drop-in.
3. `wb_ssh_exec` `systemctl daemon-reload`.
4. `wb_systemd_unit unit=<u> action=restart`.
5. `wb_systemd_unit unit=<u>` — status, verify ExecStart/Restart applied.

**Resetting a directive from the main file** — re-declaring with an empty line:

```ini
[Service]
ExecStart=
ExecStart=/usr/local/bin/my-wrapped-service
```

Without `ExecStart=` (empty) systemd appends a new one to the old.

## Scenario: create a service from a script

1. `wb_write_file path=/usr/local/bin/<name>.sh content=<bash>` + `wb_ssh_exec chmod 0755 ...`.
2. `wb_write_file path=/etc/systemd/system/<name>.service content=<unit>`.
3. `wb_ssh_exec` `systemctl daemon-reload`.
4. `wb_systemd_unit unit=<name> action=start` — verify.
5. `wb_systemd_unit unit=<name>` — status.

**Minimal oneshot service template under a timer:**

```ini
[Unit]
Description=My periodic task
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/my-task.sh
StandardOutput=journal
StandardError=journal
```

## Scenario: timer

1. `wb_write_file path=/etc/systemd/system/<name>.timer content=<timer>`.
2. `wb_ssh_exec` `systemctl daemon-reload`.
3. `wb_systemd_unit unit=<name>.timer action=enable` (then `action=start` or directly via `wb_ssh_exec` `systemctl enable --now <name>.timer`).
4. `wb_ssh_exec` `systemctl list-timers <name>.timer --no-pager` — see `NEXT`.

**Timer template:**

```ini
[Unit]
Description=Run my-task every hour

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=2min

[Install]
WantedBy=timers.target
```

`Persistent=true` — catches up the run if the controller was off.

## wb-rules cron vs systemd timer

| Case | Choose |
|------|--------|
| Condition depends on MQTT state, dev[], other rules | `/wb-rules` cron(...) or setInterval |
| Plain shell script on a schedule | systemd timer (this skill) |
| Backup / sync / monitoring (not bound to the bus) | systemd timer |
| Reaction to control change or bus event | `/wb-rules` whenChanged |

## Gotchas

- **Editing `/lib/systemd/system/<u>.service` directly** — overwritten by apt. Only drop-in in `/etc/systemd/system/<u>.service.d/`.
- **`ExecStart=` in drop-in without reset** — empty line before the new one is mandatory.
- **Forgot `systemctl daemon-reload`** — systemd doesn't see changes.
- **`enable` without `--now`** — unit activates only after reboot. Do `wb_systemd_unit action=enable` + `action=start` separately, or `wb_ssh_exec` `systemctl enable --now <u>`.
- **Type=oneshot without `RemainAfterExit=yes`** — after successful run "inactive (dead)". Fine for a timer, not for a long-running unit.
- **Custom unit without `[Install]`** — `enable` fails with "No installation information found".
- **mask, forgot `unmask`** — won't start later.
- **Custom units in `/etc/systemd/system/`** don't survive FIT firmware. For backup — `/wb-controller-backup` (the "Custom systemd units" section).

## Related skills

- `/wb-troubleshooting` — diagnostics of failed units, kernel mismatch.
- `/wb-rules` — automation reacting to MQTT.
- `/wb-controller-backup` — saving custom units before FIT.

Details (override syntax, full examples, OnCalendar) — bash-flavor twin `/wb-services` (same skill name, bash flavor).

## Documentation

- systemd unit: <https://www.freedesktop.org/software/systemd/man/systemd.unit.html>
- systemd timer: <https://www.freedesktop.org/software/systemd/man/systemd.timer.html>
- OnCalendar: <https://www.freedesktop.org/software/systemd/man/systemd.time.html>
