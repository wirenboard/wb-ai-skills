---
name: wb-controller-backup
description: "Backup and restore of a Wiren Board controller — collect a tar.gz with configs, /etc, data, package lists, network settings. Use when user wants to save controller state, prepare for firmware flash or controller replacement, transfer settings, restore after factory reset, roll back. NOT for diagnostic archive (that's wb-troubleshooting)."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# controller-backup

## CRITICAL RULES

> **NEVER call `wb-cli` without `--json` from an agent.**
> Human-mode output is unparseable; always use:
> `wb-cli --json <command>`
> This applies to every call including help: `wb-cli --json <group> --help`.

Backup and restore of a WB controller — collect an archive with configs, data and package lists; hand it to the user; restore after a firmware flash or on a new controller. Load this on "make a backup", "controller backup", "save the controller", "send me the backup", "backup before update", "roll back after firmware flash", "restore from backup", "transfer settings".

**This is NOT a diagnostic archive.** If the user asks for a "diagnostic archive", "logs for support", "wb-diag-collect" — that's the `wb-troubleshooting` skill, not backup. Backup is the full controller restore process (packages, configs, data, RESTORE.md), takes minutes.

**THERE IS NO BACKUP UTILITY ON THE CONTROLLER.** There is no `wb-backup`, `wbctl backup`, `backup.sh` — don't make these up. The backup is built in 3 phases below. `wb-cli snapshot save` captures a quick state snapshot (identity + failed units), but it is NOT a full backup — it's only for pre/post verification.

**Backup = tar.gz archive** with files, configs, package lists.

**All files go to `/mnt/data/ai/wb-ai-skills/backups/`.** Don't scatter them across `/tmp`, `/root`, `/mnt/data/backups`.

**HOST variable:** in all examples below `<HOST>` means `wirenboard-<SN>.local`, where `<SN>` is the controller serial number (e.g. `wirenboard-AABBCCDD.local`). Substitute the real address.

## Checklist — print after each step

**THE BACKUP IS NOT READY** until ALL steps are done. After completing each step, print the checklist and **immediately move to the next unfinished step**. Don't stop, don't ask the user — go all the way and send the archive.

```
Backup progress:
[done] Phase 1.0: audit and report
[ ] Phase 1b: state-snapshot (for verification after restore)
[ ] Phase 2.1: core archive (metadata + configs)
[ ] Phase 2.2: audit-files (custom files per audit)
[ ] Phase 2.3: Docker volumes (if any)
[ ] Phase 3.1: RESTORE.md
[ ] Phase 3.2: final packaging
[ ] Phase 3.3: delivery to user
```

Skip steps that aren't needed (e.g. Docker volumes if there's no Docker), but mark them `[skip]`. **Don't say "backup ready" until all steps are done or skipped.**

## Phase 1 — audit and plan (the model's first response)

Phase 1 produces a single audit script invocation that gathers all controller state (firmware, packages, services, custom files, modified configs, user directories), a verification snapshot via `wb-cli snapshot save --label backup-pre`, a "differences from stock" report for the user, and a complete path list for Phase 2.

**Don't wait for the user's reply between Phase 1 and Phase 2.** Show the report, then go straight into Phase 2.

For the exact audit script, output field breakdown, snapshot fallback, and audit-field → action table — see **`references/audit.md`**.

## Phase 2 — building the archive

Phase 2 puts files into one directory on the controller (chosen by `BACKUP_DIR=...` from the core job's log). In Phase 3 the whole directory is packed into a single archive — no manual merging.

Three steps:

1. **Core archive** — metadata, package lists, `mnt/data/etc` (recursively), key `/etc/*` configs, compose files, state-snapshot. Run as a `wb-cli --json job run backup-core` background job; **don't invent your own core script**.
2. **Audit-files archive** — paths from Phase 1's path list (custom files, units, modified configs, user directories, configs of extra packages).
3. **Docker volumes** (only if `docker-ce` is installed and volumes have data).

> Note: core-tar already includes `/mnt/data/etc` recursively — so `/mnt/data/etc/docker/`, `/mnt/data/etc/wb-mqtt-serial.conf` (via symlink), etc. are already there. Don't duplicate in audit-files.

For the exact scripts, `wb-cli job` lifecycle commands, and known-packages table — see **`references/phase2-archive.md`**.

## Phase 3 — delivery (after ALL tasks complete)

Wait for all Phase 2 steps to finish (core + audit-files + docker volumes if any). Then:

1. Generate `RESTORE.md` with the mandatory sections (Packages / Files / Symlinks / Services / Manual steps / Verification), with specific paths and package names — not placeholders.
2. Pack the directory into a single `backup-<TS>.tar.gz` via `wb-cli --json job run backup-pack`.
3. Check size — < 200 MB → download via `scp`; > 200 MB → ask the user to copy it themselves.
4. Final report: which extra packages need installing on restore, what was saved, what was NOT saved (`/mnt/data/.docker/`, large DBs, node_modules).

For the RESTORE.md template, packing/delivery commands, and the restore workflow (use when the user runs an existing backup) — see **`references/restore.md`**.

## Docker: what to back up, what not

**Don't confuse user projects with Docker storage!**

| What | Where | Back up? | How |
|---|---|---|---|
| compose files | inside projects (`/mnt/data/<project>/`) | YES | tar as is |
| bind-mount data | inside projects | YES | tar as is |
| named volumes | `docker volume ls` | YES, if it has data | `docker run --rm -v vol:/d alpine tar czf - /d > vol.tar.gz` |
| Docker daemon (`/mnt/data/.docker/`) | internal storage | NO | images via `docker pull`, restored from compose |
| Daemon config | `/mnt/data/etc/docker/` | YES | already in core archive |

Example: `/mnt/data/picoclow-docker/` (82 MB) — that's a **user project** with compose, configs and data. Back it up entirely. And `/mnt/data/.docker/` is image layers — backing those up makes no sense.

## What survives FIT, what doesn't

FIT overwrites rootfs, does NOT touch `/mnt/data/`.

| Survives | Wiped |
|---|---|
| `/mnt/data/` entirely | `/usr/local/bin/`, `/opt/`, `/srv/` |
| Configs symlinked into `/mnt/data/etc/` | `/etc/cron.d/<custom>`, `/etc/systemd/system/<custom>` |
| Network/time from web UI | apt packages outside stock |

## Restore (from an existing backup)

See **`references/restore.md`** for the full workflow — find backup → read RESTORE.md → execute step by step → verify via `state-snapshot.json` / `wb-cli snapshot diff`.

## Pitfalls

- Inventing `wb-backup`, `wbctl backup`, `backup.sh` — they don't exist.
- The core script can't be modified. But audit-tar (phase 2 step 2) — must be built based on audit data, don't skip findings.
- Stopping at the snapshot — that's NOT a backup. Continue to phase 2.
- Running tar in plain ssh — timeout. Only via `wb-cli job run` (or raw `systemd-run`).
- Backing up all of `/etc` or `/mnt/data` — huge and pointless.
- Staying silent about `/mnt/data/.docker/` — warn that it's not in the archive.
- Dumping raw audit output — show a categorized report.
- Scattering files across `/tmp`, `/root`, `/mnt/data/backups` — everything in `/mnt/data/ai/wb-ai-skills/backups/`.
- Skipping modified configs or custom systemd units — they also need to be in the archive.

## What the agent does NOT do

- **Invent backup utilities.** There is no `wb-backup`, `wbctl backup`, `backup.sh` — use the 3-phase flow.
- **Stop after the snapshot.** A `wb-cli snapshot save` is verification material, NOT a backup. Continue to Phase 2.
- **Run `tar` in plain SSH.** Long-running ops use `wb-cli --json job run` (or raw `systemd-run`) — plain SSH times out mid-archive.
- **Back up `/mnt/data/.docker/`.** That's Docker daemon storage (images, layers); restored via `docker compose pull`. Backing it up wastes 2-10 GB.
- **Dump raw audit output to the user.** Always categorize: extra packages / custom files / modified configs / user dirs / Docker.
- **Modify the core-tar script.** It captures `/mnt/data/etc` recursively and the required `/etc/*` paths; ad-hoc edits break restore.
- **Scatter files across `/tmp`, `/root`, `/mnt/data/backups`.** Everything goes under `/mnt/data/ai/wb-ai-skills/backups/`.

## When to ask the user

- Total archive size after the heuristic exceeds **2 GB** — surface the size breakdown and ask which directories to trim.
- The audit lists a package the agent doesn't recognize — ask which paths to capture (config locations are package-specific).
- Restore: about to overwrite existing files in `/etc` from `audit-files.tar.gz` — confirm the user wants those overwritten (their current customizations may be different).
- Restore: the user wants "back to as it was" but the controller currently has additional customizations not in the backup — clarify whether to wipe-and-restore or merge.
- A package in the audit is installed via Docker (e.g. zigbee2mqtt in `/mnt/data`) but also has a deb installed — clarify which one to back up.

## Documentation

- FIT update: <https://wirenboard.com/wiki/Wirenboard_Firmware_Update>
- Data partition: <https://wirenboard.com/wiki/Data_Partition>
