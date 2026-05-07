---
name: controller-backup
description: "Backup and restore of a Wiren Board controller via MCP — collect an archive with configs, data, and package lists; restore after firmware flash or on a new controller."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# controller-backup (MCP)

Backup and restore of a WB controller via MCP tools — collect an archive with configs, data, and package lists; deliver to the user; restore after firmware flash or on a new controller. Load this on "make a backup", "controller backup", "save the controller", "send me a backup", "backup before update", "rollback after firmware", "restore from backup", "transfer settings".

**This is NOT a diagnostic archive.** If the user asks for a "diagnostic archive", "logs for support", "wb-diag-collect" — that's `/troubleshooting`. A backup is the full controller restore process (packages, configs, data, RESTORE.md), takes minutes.

**THERE IS NO BACKUP UTILITY ON THE CONTROLLER.** No `wb-backup`, `wbctl backup`, `backup.sh` exists — don't make them up. The backup is assembled in 3 phases below.

**Backup = tar.gz archive** with files, configs, package lists. All files go to `/mnt/data/ai/wb-ai-integration/backups/`. Don't scatter across `/tmp`, `/root`, `/mnt/data/backups`.

## Tool routing

| Intent | Tool |
|--------|------|
| Controller audit (packages, services, custom files) | `wb_audit` |
| State snapshot for verification after restore | `wb_state_save` |
| Compare current state against snapshot | `wb_state_diff` |
| Run a long tar in background | `wb_ssh_exec_async` → `wb_job_status` / `wb_job_tail` |
| Read arbitrary command (short checks) | `wb_ssh_exec` |
| Write RESTORE.md / small files | `wb_write_file` |
| Read a file from the controller (≤64 KB) | `wb_read_file` |
| Download archive to local disk | outside MCP — `scp root@<host>:<path> ./` |

## Checklist — print after each step

**THE BACKUP IS NOT READY** until ALL steps pass. After each step completes, print the checklist and **immediately move to the next unfinished step**. Don't stop, don't ask the user — go through to the end and deliver the archive.

```
Backup progress:
[done] Phase 1: audit and report
[...] Phase 2.1: core archive (metadata + configs)
[ ] Phase 2.2: audit-files (custom files per audit)
[ ] Phase 2.3: Docker volumes (if any)
[ ] Phase 3.1: RESTORE.md
[ ] Phase 3.2: final packaging
[ ] Phase 3.3: delivery to user
```

Skip steps that aren't needed (e.g. Docker volumes if no Docker), but mark them `[skip]`. **Don't print "backup ready" until all steps are complete or skipped.**

## Phase 1 — audit and plan (model's first response)

### Step 1: audit

`wb_audit sn=<SN>` — returns structured:
- `fw` — firmware version
- `release` — release (RELEASE_NAME, SUITE, TARGET)
- `manual` — manually installed packages
- `installed` — all installed packages
- `enabled` — enabled services
- `units` — custom systemd units in `/etc/systemd/system`
- `cron` — cron jobs
- `opt`, `localbin`, `localsbin` — contents of custom directories
- `symlinks` — WB config symlinks
- `mntdata` — user directories in `/mnt/data/` with sizes
- `dpkg` — modified packaged files (`dpkg --verify`)

### Step 1b: state snapshot

`wb_state_save sn=<SN>` — saves a JSON snapshot (key fields: `fwVersion`, `manualPackages`, `enabledUnits`) to `/mnt/data/ai/wb-ai-integration/snapshots/snapshot-<TS>.json` for later verification via `wb_state_diff`.

### Step 2: report on deviations from stock

In your message to the user, print **deviations from a typical controller** — this is a useful artifact in itself:
- Extra installed packages (`manual` minus stock) — list with versions
- Enabled services beyond stock (`enabled` minus standard WB services)
- Custom files and scripts (`opt`, `localbin`, `localsbin`, `units`) — with paths
- Modified configs (`dpkg` section) — which exactly
- User directories in `/mnt/data/` (`mntdata`) — with sizes
- Docker — installed or not, how many volumes/containers

Don't dump raw output — structure it humanely. This is the first part of the response the user sees.

### Step 3: list of paths for the archive and immediately start phase 2

Based on audit results, compile a **complete list of paths** for the archive. Sources:

| Audit field | What to do with it |
|-------------|--------------------|
| `opt`, `localbin`, `localsbin` (custom files) | Add each path to the list |
| `units` (custom systemd units) | Add unit files. Read `ExecStart=` — if the script isn't from a package, add it too |
| `dpkg` (modified configs) | Add each modified config |
| `mntdata` (user directories) | These are **user projects** (not Docker storage!). Add each directory, show size |
| Extra non-stock packages | `wb_ssh_exec` `dpkg -L <pkg> | grep -E '^/(etc|var/lib|opt|srv)'` — add found paths |
| Enabled services beyond stock | Don't archive — they're already in `services-enabled.list` |

**Size heuristic — without confirmations:**
- Directory < 100 MB → include.
- Directory 100 MB – 1 GB → include, but **warn in the message** "such-and-such directory is N MB — included in archive".
- Directory > 1 GB or named Docker volumes with DBs → **skip**, list in the message as "not in archive, request separately if needed".
- Total archive limit ~2 GB. If heuristic exceeds — cut the largest first.

In a single user message: deviations report + "including in archive: ...; skipping as too large: ...". **Don't wait for a reply** — go straight to phase 2.

## Phase 2 — archive build

**All steps drop files into a single directory on the controller.** In phase 3 the entire directory is packed into a single archive — no manual merging needed.

### Step 1: metadata and core configs

Run via `wb_ssh_exec_async` (background job). Don't try via synchronous `wb_ssh_exec` — timeout.

```
wb_ssh_exec_async sn=<SN> cmd='set -e; TS=$(date +%Y%m%d-%H%M%S); B=/mnt/data/ai/wb-ai-integration/backups/$TS; mkdir -p $B; cat /etc/wb-fw-version > $B/fw-version 2>/dev/null || true; cp /usr/lib/wb-release $B/wb-release 2>/dev/null || true; apt-mark showmanual > $B/packages-manual.list; dpkg-query -W -f="\${Package}=\${Version}\n" > $B/packages-all.list; systemctl list-unit-files --state=enabled --no-legend | awk "{print \$1}" > $B/services-enabled.list; find /etc -maxdepth 3 -type l -exec sh -c "T=\$(readlink -f \"\$1\"); case \"\$T\" in /mnt/data/*) echo \"\$1 -> \$T\";; esac" _ {} \; > $B/symlinks-etc.list; tar czf $B/core.tar.gz -C / --warning=no-file-changed --ignore-failed-read mnt/data/etc etc/wb-rules etc/wb-mqtt-serial.conf etc/wb-mqtt-serial.conf.d etc/network etc/hostname etc/resolv.conf etc/ntp.conf etc/chrony 2>/dev/null || true; find / /mnt/data -xdev \( -path /mnt/data/.docker -o -path /mnt/data/var/lib/containerd \) -prune -o \( -name "docker-compose.y*ml" -o -name "compose.y*ml" \) -print 2>/dev/null | tar czf $B/compose-files.tar.gz -T - 2>/dev/null || true; SNAP=$(ls -t /mnt/data/ai/wb-ai-integration/snapshots/snapshot-*.json 2>/dev/null | head -1); [ -n "$SNAP" ] && cp "$SNAP" $B/state-snapshot.json; echo BACKUP_DIR=$B; du -sh $B $B/*'
```

`wb_job_tail job_id=<id>` — track progress. From the final output take `BACKUP_DIR=...` (e.g. `/mnt/data/ai/wb-ai-integration/backups/20260419-224500`). **Substitute this specific path in all subsequent steps** — the `$B` variable doesn't persist across new invocations.

### Step 2: data per audit results

```
wb_ssh_exec_async sn=<SN> cmd='tar czf <BACKUP_DIR>/audit-files.tar.gz --warning=no-file-changed --ignore-failed-read <paths from audit> 2>/dev/null || true; du -sh <BACKUP_DIR>/audit-files.tar.gz'
```

Substitute **specific paths** from step 3 of phase 1:
- Custom files: `/opt/my-app/`, `/usr/local/bin/my-script.sh`
- Custom systemd units: `/etc/systemd/system/my-service.service`
- Modified configs: `/etc/mosquitto/mosquitto.conf`
- User directories: `/mnt/data/picoclow-docker/` — these are user projects, back up!
- Configs of extra packages: paths from `dpkg -L`
- Configs of known packages (table below): `/mnt/data/root/zigbee2mqtt`, `/etc/mosquitto`, `/etc/nginx`, `/var/lib/grafana/grafana.db`, `/etc/influxdb`, `/root/.node-red/flows*.json`, `/root/.node-red/settings.js`, `/mnt/data/etc/docker`, `/etc/cron.d`

### Step 3: named Docker volumes (if Docker is installed)

If extra packages include `docker-ce`:

```
wb_ssh_exec sn=<SN> cmd='docker volume ls -q 2>/dev/null'
```

If volumes with data exist:

```
wb_ssh_exec_async sn=<SN> cmd='for v in $(docker volume ls -q); do docker run --rm -v $v:/data alpine tar czf - /data > <BACKUP_DIR>/docker-volume-$v.tar.gz 2>/dev/null; done; ls -lh <BACKUP_DIR>/docker-volume-*.tar.gz 2>/dev/null'
```

## Phase 3 — delivery (after ALL jobs complete)

Wait for all phase 2 steps to complete (`wb_job_status` → `exited`).

### 1. RESTORE.md

`wb_write_file sn=<SN> path=<BACKUP_DIR>/RESTORE.md content=<instructions>`. Content — based on actual audit data. **Mandatory** sections (don't skip any):

1. **Packages** — list ALL extra packages from the audit. For Docker — via `wb-docker-manager.sh`. For others — `apt install <pkg1> <pkg2> ...`. Order: dependencies first, then dependents. **This section is critical** — without packages, configs are useless.
2. **Files** — what to extract and where (`tar xzf core.tar.gz -C /`, `tar xzf audit-files.tar.gz -C /`).
3. **Symlinks** — which to restore (from `symlinks-etc.list`).
4. **Services** — which to enable (`systemctl enable ...`) — per the list of extra enabled services from the audit.
5. **Manual steps** — what can't be automated (Docker images: `docker compose pull`, DBs, node_modules).
6. **Verification** — `wb_state_diff` against `state-snapshot.json`.

Write specific paths, package names, and commands — not `$variables` and not `<placeholder>`.

### 2. Pack into a single file

```
wb_ssh_exec_async sn=<SN> cmd='cd /mnt/data/ai/wb-ai-integration/backups && tar czf backup-<TS>.tar.gz <TS>/ && du -sh backup-<TS>.tar.gz'
```

### 3. Check size and deliver

```
wb_ssh_exec sn=<SN> cmd='stat -c%s /mnt/data/ai/wb-ai-integration/backups/backup-<TS>.tar.gz'
```

- < 200 MB → user downloads locally:
  ```bash
  scp root@wirenboard-<SN>.local:/mnt/data/ai/wb-ai-integration/backups/backup-<TS>.tar.gz ./
  ```
- > 200 MB → tell the user to copy via `scp` themselves (don't pull through MCP — `wb_read_file` is limited to 64 KB).

### 4. Final report

- Which extra packages need to be installed during restore — list specific names.
- What's saved (specific paths).
- What is NOT saved — warn:
  - `/mnt/data/.docker/` (Docker daemon's internal storage: images, layers) — restored via `docker pull` / `docker compose pull`.
  - Large DBs (InfluxDB) — `influxd backup` manually.
  - Node-RED `node_modules` — restored via `npm install`.

## Docker: what to back up, what not

**Don't confuse user projects with Docker storage!**

| What | Where | Back up? | How |
|------|-------|----------|-----|
| compose files | in projects (`/mnt/data/<project>/`) | YES | tar as is |
| bind-mount data | in projects | YES | tar as is |
| named volumes | `docker volume ls` | YES, if data exists | `docker run --rm -v vol:/d alpine tar czf - /d > vol.tar.gz` |
| Docker daemon (`/mnt/data/.docker/`) | internal storage | NO | images via `docker pull`, restored from compose |
| Daemon config | `/mnt/data/etc/docker/` | YES | already in core archive |

Example: `/mnt/data/picoclow-docker/` (82 MB) is a **user project** with compose, configs, and data. It MUST be backed up entirely. But `/mnt/data/.docker/` is image layers, backing them up makes no sense.

## Known packages — what's in the archive, what to warn about

| Package | What's in the archive | What to warn |
|---------|-----------------------|--------------|
| `docker-ce` | `/mnt/data/etc/docker/`, compose files, projects from `mntdata` | `/mnt/data/.docker/` is NOT in the archive. Docker is installed via `wb-docker-manager.sh`. Named volumes — separate |
| `zigbee2mqtt` | `/mnt/data/root/zigbee2mqtt/` | -- |
| `nodered` | `flows*.json`, `settings.js` | `node_modules` restored via `npm install` |
| `mosquitto` | `/etc/mosquitto/` | -- |
| `influxdb` | `/etc/influxdb/` | DB via `influxd backup`, not tar |
| `grafana` | `/var/lib/grafana/grafana.db`, `/etc/grafana/` | -- |
| `nginx` | `/etc/nginx/` | Certificates `/etc/letsencrypt/` — separately |

## What survives FIT, what doesn't

FIT rewrites rootfs, does NOT touch `/mnt/data/`.

| Survives | Wiped |
|----------|-------|
| `/mnt/data/` entirely | `/usr/local/bin/`, `/opt/`, `/srv/` |
| Configs symlinked into `/mnt/data/etc/` | `/etc/cron.d/<custom>`, `/etc/systemd/system/<custom>` |
| Network/time from web UI | apt packages outside stock |

## Restore

1. Find the backup: `wb_ssh_exec` `ls -lt /mnt/data/ai/wb-ai-integration/backups/`. The backup survives FIT. Or the user uploads the file with local `scp ./backup-<TS>.tar.gz root@wirenboard-<SN>.local:/mnt/data/ai/wb-ai-integration/backups/`.
2. Read RESTORE.md: `wb_read_file sn=<SN> path=/mnt/data/ai/wb-ai-integration/backups/<TS>/RESTORE.md`.
3. Execute step by step with user confirmation. Packages — via `wb_ssh_exec_async`.
4. Verification: `wb_state_diff sn=<SN> snapshot=<BACKUP_DIR>/state-snapshot.json` — what differs from the "before" state.

## Gotchas

- Inventing `wb-backup`, `wbctl backup`, `backup.sh` — they don't exist.
- Don't change the core script. But the audit-tar (step 2 of phase 2) — must be built from audit data, don't skip findings.
- Stopping at the snapshot — that's NOT a backup. Continue to phase 2.
- Running tar via synchronous `wb_ssh_exec` — timeout. Only `wb_ssh_exec_async`.
- Backing up `/etc` or `/mnt/data` entirely — huge and useless.
- Staying silent about `/mnt/data/.docker/` — warn that it's not in the archive.
- Dumping raw audit output — show a categorized report.
- Scattering files across `/tmp`, `/root`, `/mnt/data/backups` — everything in `/mnt/data/ai/wb-ai-integration/backups/`.
- Skipping modified configs or custom systemd units — they're also needed in the archive.

## Documentation

- FIT update: <https://wirenboard.com/wiki/Wirenboard_Firmware_Update>
- Data partition: <https://wirenboard.com/wiki/Data_Partition>
