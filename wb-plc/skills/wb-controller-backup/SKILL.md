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

### Step 1: collect data — controller audit

The audit is performed by a single SSH script that gathers all controller state data:

```bash
ssh root@<HOST> 'echo "===WB-AUDIT===fw"; cat /etc/wb-fw-version 2>/dev/null || true; echo "===WB-AUDIT===release"; cat /usr/lib/wb-release 2>/dev/null || true; echo "===WB-AUDIT===manual"; apt-mark showmanual 2>/dev/null | sort; echo "===WB-AUDIT===installed"; dpkg-query -W -f="\${Package}\n" 2>/dev/null | sort; echo "===WB-AUDIT===enabled"; systemctl list-unit-files --state=enabled --no-legend 2>/dev/null | awk "{print \$1}" | sort; echo "===WB-AUDIT===units"; find /etc/systemd/system -maxdepth 2 -name "*.service" -type f 2>/dev/null | sort; echo "===WB-AUDIT===cron"; for d in /etc/cron.d /etc/cron.hourly /etc/cron.daily /etc/cron.weekly /var/spool/cron/crontabs; do ls -A "$d" 2>/dev/null | grep -v "^\.placeholder$" | sed "s|^|$d/|"; done; echo "===WB-AUDIT===opt"; ls -A /opt 2>/dev/null; echo "===WB-AUDIT===localbin"; ls -A /usr/local/bin 2>/dev/null; echo "===WB-AUDIT===localsbin"; ls -A /usr/local/sbin 2>/dev/null; echo "===WB-AUDIT===symlinks"; for p in /etc/wb-rules /etc/wb-rules-modules /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.d; do echo "$p|$(readlink -f $p 2>/dev/null)"; done; echo "===WB-AUDIT===mntdata"; shopt -s nullglob dotglob; for d in /mnt/data/*/; do case "$(basename "$d")" in etc|var|root|snapshots|backups|uploads|.docker|ai|.wb-restore|.wb-update|lost+found) continue;; *) du -sh "$d" 2>/dev/null;; esac; done; shopt -u dotglob; echo "===WB-AUDIT===dpkg"; dpkg --verify 2>/dev/null | grep -v -E "/usr/share/(doc|locale|man|lintian|gtk-doc|gnome|info|help)"; echo "===WB-AUDIT===end"'
```

Output sections breakdown:
- `fw` — firmware version
- `release` — release (RELEASE_NAME, SUITE, TARGET)
- `manual` — manually installed packages
- `installed` — all installed packages
- `enabled` — enabled services
- `units` — custom systemd units in `/etc/systemd/system`
- `cron` — cron jobs
- `opt` — contents of `/opt`
- `localbin` — contents of `/usr/local/bin`
- `localsbin` — contents of `/usr/local/sbin`
- `symlinks` — WB config symlinks
- `mntdata` — user directories under `/mnt/data/` with sizes
- `dpkg` — modified package files (dpkg --verify)

### Step 1b: snapshot for verification after restore

Save a controller state snapshot via wb-cli:

```bash
ssh root@<HOST> wb-cli --json snapshot save --label backup-pre
```

This saves a JSON snapshot to `/mnt/data/ai/wb-cli/snapshots/backup-pre.json` with controller identity, failed units, etc. After restore, compare with `wb-cli snapshot diff <path>`.

Use the manual method only if wb-cli is not installed:

```bash
ssh root@<HOST> 'mkdir -p /mnt/data/ai/wb-ai-skills/snapshots'
```

```bash
ssh root@<HOST> 'cat > /mnt/data/ai/wb-ai-skills/snapshots/snapshot-$(date +%Y-%m-%dT%H-%M-%S).json << SNAPEOF
{
  "_comment": "Controller snapshot for backup verification",
  "takenAt": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
  "fwVersion": "'"$(cat /etc/wb-fw-version 2>/dev/null)"'",
  "manualPackages": '"$(apt-mark showmanual 2>/dev/null | sort | jq -Rsc 'split("\n") | map(select(. != ""))')"',
  "enabledUnits": '"$(systemctl list-unit-files --state=enabled --no-legend 2>/dev/null | awk "{print \$1}" | sort | jq -Rsc 'split("\n") | map(select(. != ""))')"'
}
SNAPEOF
echo "Snapshot saved: $(ls -t /mnt/data/ai/wb-ai-skills/snapshots/snapshot-*.json 2>/dev/null | head -1)"'
```

### Step 2: report on differences from stock

In the user-facing message, present **differences from a stock controller** — this is a useful artifact in itself:
- Additionally installed packages (`manual` minus stock) — list with versions
- Enabled services beyond stock (`enabled` minus standard WB services)
- Custom files and scripts (`opt`, `localbin`, `localsbin`, `units`) — with paths
- Modified configs (`dpkg` section) — which exactly
- User directories under `/mnt/data/` (`mntdata`) — with sizes
- Docker — installed or not, how many volumes/containers

Don't dump raw output — structure it like a human would. This is the first part of the response the user sees.

### Step 3: build the path list and immediately start phase 2

Based on audit results, build a **complete path list** for the archive. Sources:

| Audit field | What to do with it |
|---|---|
| `opt`, `localbin`, `localsbin` (custom files) | Add each path to the list |
| `units` (custom systemd units) | Add unit files. Read `ExecStart=` — if the script isn't from a package, add it too |
| `dpkg` (modified configs) | Add each modified config |
| `mntdata` (user directories) | These are **user projects** (not Docker storage!). Add each directory, show the size |
| Extra packages not from stock | `ssh root@<HOST> "dpkg -L <pkg> | grep -E '^/(etc|var/lib|opt|srv)'"` — add the found paths |
| Enabled services beyond stock | Don't archive — they get recorded in `services-enabled.list` automatically |

**Size heuristic — without confirmations:**
- Dir < 100 MB -> include.
- Dir 100 MB - 1 GB -> include, but **warn in the message** "such-and-such directory is N MB — will go into the archive".
- Dir > 1 GB or named Docker volumes with DBs -> **skip**, list in the message as "not in the archive, request separately if needed".
- Total final archive limit ~2 GB. If the heuristic exceeds that — trim the largest first.

In one message to the user: difference report + "including in the archive: ...; skipping as too large: ...". **Don't wait for a reply** — proceed straight to phase 2.

## Phase 2 — building the archive

**All steps put files into one directory on the controller.** In phase 3, the whole directory is packed into a single archive — no need to merge by hand.

> Note: core-tar includes `mnt/data/etc` recursively — so `/mnt/data/etc/docker/`, `/mnt/data/etc/wb-mqtt-serial.conf` (via symlink), etc. are **already there**. Don't duplicate them in audit-files-tar.

### Step 1: metadata and core configs

Run THIS script as a background job. Don't invent your own script for this part.

```bash
ssh root@<HOST> 'wb-cli --json job run backup-core "set -e; TS=\$(date +%Y%m%d-%H%M%S); B=/mnt/data/ai/wb-ai-skills/backups/\$TS; mkdir -p \$B; cat /etc/wb-fw-version > \$B/fw-version 2>/dev/null || true; cp /usr/lib/wb-release \$B/wb-release 2>/dev/null || true; apt-mark showmanual > \$B/packages-manual.list; dpkg-query -W -f='"'"'\${Package}=\${Version}\n'"'"' > \$B/packages-all.list; systemctl list-unit-files --state=enabled --no-legend | awk '"'"'{print \$1}'"'"' > \$B/services-enabled.list; find /etc -maxdepth 3 -type l -exec sh -c '"'"'T=\$(readlink -f \"\$1\"); case \"\$T\" in /mnt/data/*) echo \"\$1 -> \$T\";; esac'"'"' _ {} \\; > \$B/symlinks-etc.list; tar czf \$B/core.tar.gz -C / --warning=no-file-changed --ignore-failed-read mnt/data/etc etc/wb-rules etc/wb-mqtt-serial.conf etc/wb-mqtt-serial.conf.d etc/network etc/hostname etc/resolv.conf etc/ntp.conf etc/chrony 2>/dev/null || true; find / /mnt/data -xdev \\( -path /mnt/data/.docker -o -path /mnt/data/var/lib/containerd \\) -prune -o \\( -name '"'"'docker-compose.y*ml'"'"' -o -name '"'"'compose.y*ml'"'"' \\) -print 2>/dev/null | tar czf \$B/compose-files.tar.gz -T - 2>/dev/null || true; SNAP=\$(ls -t /mnt/data/ai/wb-cli/snapshots/*.json /mnt/data/ai/wb-ai-skills/snapshots/snapshot-*.json 2>/dev/null | head -1); [ -n \"\$SNAP\" ] && cp \"\$SNAP\" \$B/state-snapshot.json; echo BACKUP_DIR=\$B; du -sh \$B \$B/*"'
```

`wb-cli job run` wraps `systemd-run` — it returns a JSON with the `unit` name and `log` path.

Check the job status and tail the log:
```bash
ssh root@<HOST> wb-cli --json job status <unit>
ssh root@<HOST> wb-cli --json job tail <unit>
```

Wait for the job to finish (blocks up to 5 minutes):
```bash
ssh root@<HOST> wb-cli --json job wait <unit>
```

From the job log, take the path `BACKUP_DIR=...` — for example `/mnt/data/ai/wb-ai-skills/backups/20260419-224500`. **Substitute this exact path in all subsequent steps.** Don't write `$B` in following commands — the variable does not persist between calls!

### Step 2: data based on audit results

```bash
ssh root@<HOST> 'wb-cli --json job run backup-audit "tar czf <BACKUP_DIR>/audit-files.tar.gz --warning=no-file-changed --ignore-failed-read <paths from audit> 2>/dev/null || true; du -sh <BACKUP_DIR>/audit-files.tar.gz"'
```

Substitute **specific paths** from phase 1 step 3:
- Custom files: `/opt/my-app/`, `/usr/local/bin/my-script.sh`
- Custom systemd units: `/etc/systemd/system/my-service.service`
- Modified configs: `/etc/mosquitto/mosquitto.conf`
- User directories: `/mnt/data/picoclow-docker/` — these are user projects, back up!
- Configs of extra packages: paths from `dpkg -L`
- Configs of known packages (table below): `/mnt/data/root/zigbee2mqtt`, `/etc/mosquitto`, `/etc/nginx`, `/var/lib/grafana/grafana.db`, `/etc/influxdb`, `/root/.node-red/flows*.json`, `/root/.node-red/settings.js`, `/mnt/data/etc/docker`, `/etc/cron.d`

### Step 3: named Docker volumes (if Docker is present)

If `docker-ce` is among the extra packages:
```bash
ssh root@<HOST> "docker volume ls -q 2>/dev/null"
```
If there are volumes with data:
```bash
ssh root@<HOST> 'wb-cli --json job run backup-docker "for v in \$(docker volume ls -q); do docker run --rm -v \$v:/data alpine tar czf - /data > <BACKUP_DIR>/docker-volume-\$v.tar.gz 2>/dev/null; done; ls -lh <BACKUP_DIR>/docker-volume-*.tar.gz 2>/dev/null"'
```

## Phase 3 — delivery (after ALL tasks complete)

Wait for all phase 2 steps to finish (core + audit-files + docker volumes if any).

### 1. RESTORE.md

Generate and save the restore instructions:
```bash
echo '<RESTORE.md content>' | ssh root@<HOST> 'cat > <BACKUP_DIR>/RESTORE.md'
```

The content is based on actual audit data. **Mandatory** sections (don't skip any):

1. **Packages** — list ALL extra packages from the audit. For Docker — via `wb-docker-manager.sh`. For the rest — `apt install <pkg1> <pkg2> ...`. Order: dependencies first, dependents next. **This section is critical** — without packages, configs are useless.
2. **Files** — what to extract and where (`tar xzf core.tar.gz -C /`, `tar xzf audit-files.tar.gz -C /`)
3. **Symlinks** — which to restore (from `symlinks-etc.list`)
4. **Services** — which to enable (`systemctl enable ...`) — by the list of additionally enabled services from the audit
5. **Manual steps** — what can't be automated (Docker images: `docker compose pull`, DBs, node_modules)
6. **Verification** — compare current state with `state-snapshot.json`

Write specific paths, package names and commands — not `$variables` and not `<placeholder>`.

### 2. Pack into a single file

```bash
ssh root@<HOST> 'wb-cli --json job run backup-pack "cd /mnt/data/ai/wb-ai-skills/backups && tar czf backup-<TS>.tar.gz <TS>/ && du -sh backup-<TS>.tar.gz"'
```

### 3. Check size and deliver

```bash
ssh root@<HOST> "stat -c%s /mnt/data/ai/wb-ai-skills/backups/backup-<TS>.tar.gz"
```
- < 200 MB -> download:
  ```bash
  scp root@<HOST>:/mnt/data/ai/wb-ai-skills/backups/backup-<TS>.tar.gz ./
  ```
- > 200 MB -> suggest the user copy it themselves via scp

### 4. Final report

- Which extra packages need installing during restore — list specific names
- What was saved (specific paths)
- What was NOT saved — warn:
  - `/mnt/data/.docker/` (Docker daemon's internal storage: images, layers) — restored via `docker pull` / `docker compose pull`
  - Large DBs (InfluxDB) — `influxd backup` manually
  - Node-RED `node_modules` — restored via `npm install`

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

## Known packages — what's in the archive, what to warn about

| Package | What's in the archive | What to warn about |
|---|---|---|
| `docker-ce` | `/mnt/data/etc/docker/` (included recursively via `mnt/data/etc` in core-tar), compose files, projects from `mntdata` | `/mnt/data/.docker/` is NOT in the archive. Docker is installed **either** via `wb-docker-manager.sh` from the community repo (if present on a fresh controller: `wget -O /tmp/wb-docker-manager.sh https://raw.githubusercontent.com/wirenboard/wb-community/refs/heads/main/scripts/docker-install/wb-docker-manager.sh && bash /tmp/wb-docker-manager.sh --install`), **or** plain `apt install docker-ce containerd.io docker-ce-cli` if `dpkg-query` shows that's how it was installed. Named volumes — separately via `docker run -v ...` |
| `zigbee2mqtt` | `/mnt/data/root/zigbee2mqtt/` | -- |
| `nodered` | `flows*.json`, `settings.js` | `node_modules` is restored via `npm install` |
| `mosquitto` | `/etc/mosquitto/` | -- |
| `influxdb` | `/etc/influxdb/` | DB via `influxd backup`, not tar |
| `grafana` | `/var/lib/grafana/grafana.db`, `/etc/grafana/` | -- |
| `nginx` | `/etc/nginx/` | Certificates `/etc/letsencrypt/` — separately |

## What survives FIT, what doesn't

FIT overwrites rootfs, does NOT touch `/mnt/data/`.

| Survives | Wiped |
|---|---|
| `/mnt/data/` entirely | `/usr/local/bin/`, `/opt/`, `/srv/` |
| Configs symlinked into `/mnt/data/etc/` | `/etc/cron.d/<custom>`, `/etc/systemd/system/<custom>` |
| Network/time from web UI | apt packages outside stock |

## Restore

1. Find the backup:
   ```bash
   ssh root@<HOST> "ls -lt /mnt/data/ai/wb-ai-skills/backups/"
   ```
   The backup survives FIT. Or the user uploads the file:
   ```bash
   scp ./backup-<TS>.tar.gz root@<HOST>:/mnt/data/ai/wb-ai-skills/backups/
   ```
2. Read RESTORE.md:
   ```bash
   ssh root@<HOST> "cat /mnt/data/ai/wb-ai-skills/backups/<TS>/RESTORE.md"
   ```
3. Execute step by step with user confirmation. Packages — via `wb-cli job run`.
4. Verification: compare current state with `state-snapshot.json` (or `wb-cli snapshot diff <path>`).

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

## Documentation

- FIT update: <https://wirenboard.com/wiki/Wirenboard_Firmware_Update>
- Data partition: <https://wirenboard.com/wiki/Data_Partition>
