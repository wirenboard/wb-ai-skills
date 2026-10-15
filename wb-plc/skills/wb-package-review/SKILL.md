---
name: wb-package-review
description: "Review a ready-made .deb for Wiren Board controllers — usually a third-party integration or driver — before it is recommended, shipped or installed in the field: unpack and explain how it works, check it against wb-python-service-template and the WB lintian profile, find which WB releases (wb6/wb7/wb8, bullseye/trixie) satisfy its Depends, run install → reboot → purge on a test controller, measure idle CPU, and write a short findings message for the package author. Use when someone hands over a .deb and asks 'посмотри пакет', 'как он работает', 'проверь по шаблону', 'встанет ли на wb6/wb7/wb8', 'review this package', 'is this safe to install'. NOT for writing your own package (wb-dev) and NOT for diagnosing a broken controller (wb-troubleshooting)."
allowed-tools: Bash Read Write WebFetch
---

# wb-package-review — review a .deb before it goes onto WB controllers

For engineers, support and integrators who receive a finished `.deb` (often from a partner) and
need a defensible answer to "how does it work, does it follow WB conventions, where will it
install, and what does it cost the controller". The output is a short findings message for the
author plus the evidence behind each line.

## Quick Start

1. **Unpack, don't install:** `dpkg-deb -I pkg.deb; dpkg-deb -R pkg.deb ./pkg/` — read `control`,
   maintainer scripts, `conffiles`, units, everything under `/etc`, then the code. Read the
   package's own docs in `usr/share/doc/` too: authors often record the controller, release and
   package versions they tested on — compare with your stand before drawing conclusions.
2. **Explain the architecture first** (what talks to the bus, what publishes MQTT, what listens on
   a port, what it adds to nginx/systemd/wb-configs) — reviewers and the user need this before
   any verdict.
3. **Static conformance** against `wirenboard/wb-python-service-template` →
   `references/conformance-checklist.md`.
4. **Lintian** with the WB profile from `wirenboard/codestyle` (Docker, no install on the host).
5. **Release matrix:** compare `Depends` with
   `https://raw.githubusercontent.com/wirenboard/wb-releases/master/releases.yaml` for every
   `wbN/<debian>` target; check the Python syntax floor with `ast.parse(..., feature_version=...)`.
6. **Stand run** on a dedicated test controller: install → import/`--version` → services →
   reboot → `wb_move` → purge → autoremove → cleanup, plus a 60–120 s idle CPU measurement →
   `references/stand-run.md`.
7. **Independent check:** hand the claims to a fresh subagent with only the unpacked tree and
   ask it to refute them with `file:line` evidence. Fold back what survives.
8. **Write the message** (template below) — short, numbered, no adjectives, each point with the
   fix.

## Hard rules — never violate without explicit user OK

- **Test controller only.** Never install a reviewed package on a production or customer
  controller. Default package configs are usually inert, but maintainer scripts still run as
  root and may reload nginx or touch `wb-mqtt-serial.conf`.
- **Don't let the package talk to a real bus** unless the user asks: keep its config disabled /
  without ports. The review is about packaging and cost, not about driving someone's devices.
- **Back up before changing the release or Debian version** of the stand (`wb-controller-backup`
  skill). Going bullseye → trixie is one-way except by factory reset.
- **Reboot, release upgrade, purge — ask first** on any controller someone else may use.

## Process notes per phase

**Architecture.** Look for: which process opens the serial port (own driver vs
`wb-mqtt-serial` RPC `port/Load`, `device/SetPoll`), which MQTT devices it publishes, Last Will,
listening sockets and how they are exposed, timers, state dirs, what `postinst` enables and
starts. A web UI proxied through an own `/etc/nginx/includes/default.wb.d/*.conf` bypasses the
homeui login; the supported way is a homeui **service gate** — a package drop-in
`/usr/share/wb-mqtt-homeui/gates.d/<name>.json` (`internalPort`, `externalPort`, `role`,
`menu.title`) applied with `wb-homeui-gates apply`, which renders an `auth_request`-protected
nginx server on the external port and an «Интеграции» menu item. How-to:
<https://github.com/wirenboard/homeui/blob/master/docs/wb-service-gate-howto.md>; reference
package: <https://github.com/wirenboard/wb-node-red>. Gates need `wb-mqtt-homeui >= 2.241.0` —
look up in `releases.yaml` which releases ship it (at the time of writing: wb-2609 and later)
and say so in the findings. A plain menu link without a gate is a JSON drop-in in
`/usr/share/wb-mqtt-homeui/custom-menu/` (homeui README, "Custom menu").

**Release matrix.** `releases.yaml` keys are `wbN/<debian>` per release; the newest stable may
exist for one Debian only. A versioned dependency on a WB package (e.g. `wb-mqtt-serial (>= X)`)
silently excludes older releases — list exactly which releases satisfy it. `Architecture: all`
with pure Python is not arch-specific, but the Debian of each release decides Python and
library versions (bullseye: Python 3.9, jsonschema 3.2; trixie: Python 3.13, jsonschema 4.x).

**Idle cost.** Measure, don't infer: per-unit `CPUUsageNSec` deltas over a fixed window, and
`Consumed …s CPU time` lines for oneshot services fired by timers. Then profile the hot path
(`python3 -m cProfile -s cumtime …`). Re-measure after a release/Debian change — dependency
versions move the numbers.

## Pitfalls

- **`wb-cli job wait` takes the unit name** (`wb-cli-job-<label>-<ts>` from `job run`), not the
  label. With the label it returns at once while apt is still running.
- **Changing the Debian version goes through apt, as documented in the release notes** — read
  the target release's wiki page (`https://wiki.wirenboard.com/wiki/Wb-XXXX`) first. For
  bullseye → trixie: `apt update && apt upgrade` (the release name gets a `-trixie-transition`
  suffix), then `wb-release --update-debian-release`, then reboot. It takes tens of minutes and
  needs free space on rootfs; the exact figures are in the release notes.
- **A FIT staged by `wb-run-update` was seen not to apply** across a Debian change: the
  controller booted the old system and `wb_webupd=1` stayed set in U-Boot. If that happens,
  stop, reset `fw_setenv wb_webupd 0`, delete `/mnt/data/.wb-update/webupd.fit`, and use the
  apt path; the cause is only visible on the debug console.
- **Oneshot + timer + `prerm` stop:** a oneshot killed by SIGTERM on remove/upgrade ends in
  `failed` (no `SuccessExitStatus=SIGTERM`). Whether you catch it is timing — the longer each
  run, the more often. Check `systemctl --failed` after purge and `reset-failed` when cleaning.
- **Validation inside a polling loop** (re-reading config + `jsonschema` against a large schema
  every second or every timer tick) is a common source of idle CPU in Python integrations.
- **Testing a homeui gate:** with no homeui users `/auth/check` lets everyone in, so create a
  temporary admin + user (ask first — while they exist the stand's web UI requires login) to
  see 302-to-login / 401 / 403 / 200. homeui refuses to delete the last admin over the API —
  restore the stand's original user state afterwards.
- **Apps behind a gate:** the gate proxies with `Host $host` (no port), so an app that compares
  `Origin` with `Host` rejects
  every browser POST through the gate with 403; also grep the UI for hard-coded paths (old
  `/<name>/` links) that should become `/open-<gate>`. Extra nginx directives the old include
  carried (`proxy_read_timeout`, `client_max_body_size`) move to `<gate>.nginx.inc` next to the
  gate JSON.
- **A gate is not the whole access control:** requests through the WB cloud tunnel arrive from
  loopback and skip the `role` check (see the gate how-to, "Ограничения"). A service that changes
  controller configuration should keep its own authorization behind the gate — don't advise the
  author to drop it.
- **`apt autoremove` keeps `rc` entries** and may keep packages that something else marked
  manual; report what it removed, purge your own `rc` leftovers only.
- **Lintian in `debian:bullseye` Docker may fail to install** (archived suite); the trixie image
  with the `wirenboard/trixie` profile is the reliable run. Say which profile actually ran.

## Findings message — template

```
Проверили <pkg> <ver> на <model> (<release>/<debian>[, <release2>/<debian2>]) по чек-листу
wb-python-service-template: установка, --version, автозапуск, перезагрузка, wb_move, purge — <итог>.
Lintian (<profile>) — <итог>.

Что поправить:
1. <проблема с цифрой>. <предлагаемое исправление>.
2. ...
N. Мелочи: <через ;>.

Ссылки:
— <компонент>: <ссылка на репозиторий или README>
```

Write it in the author's language; one line per problem plus its fix; numbers from measurements,
not estimates; drop praise and epithets. When a fix depends on a newer WB feature, name the first
release that has it and what the author needs on their test controller. Links: one line per
component, pointing at the repository (its README) rather than deep files.

## References

- `references/conformance-checklist.md` — where the template rules live, plus the checks the
  template doesn't cover (systemd, purge, web UI behind a gate); reach for it in phase 3.
- `references/stand-run.md` — review steps around the template's stand checklist: long jobs,
  lintian, idle CPU, leftovers after purge, Debian upgrade; reach for it in phase 6.

## What the agent does NOT do

- **Report a measurement it did not take.** Code-derived load is a hypothesis until measured on
  the stand; label it so.
- **Use the controller's own clean-up as proof of purge correctness** — inspect the filesystem
  (`/etc`, `/mnt/data/etc`, `/var/lib`, `/var/backups`, units) after purge.
- **Post the findings to the author or a public tracker itself.** It drafts; the user sends.
- **Leave the stand dirty:** package, token/state dirs, staged FIT, `.deb` in `/tmp`, failed units,
  temporary homeui users and test gates.

## When to ask the user

- Which controller is the stand, when discovery finds more than one or the stand looks used
  (Modbus devices on the bus, recent uptime, extra packages such as remote-access agents).
- Before a reboot, purge, release switch or Debian upgrade.
- Whether to test on more than one release/Debian when the newest stable is for a different
  Debian than the stand.
- Whether the package may be enabled against real hardware.
- Before creating temporary homeui users on the stand to test login-protected web parts.

## Documentation

- Template: <https://github.com/wirenboard/wb-python-service-template>
- Lintian profile and codestyle: <https://github.com/wirenboard/codestyle>
- Releases: <https://github.com/wirenboard/wb-releases> (`releases.yaml`)
- Release notes: <https://wiki.wirenboard.com/wiki/Wiren_Board_Software_Releases>
- homeui service gates: <https://github.com/wirenboard/homeui/blob/master/docs/wb-service-gate-howto.md>
- Reference package with a gate: <https://github.com/wirenboard/wb-node-red>
