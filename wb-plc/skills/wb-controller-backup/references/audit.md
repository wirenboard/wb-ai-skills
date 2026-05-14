# Phase 1 — audit and plan

Phase 1 collects all controller state and builds the path list for Phase 2. **Don't wait for the user's reply between Phase 1 and Phase 2** — show the report, then go straight into Phase 2.

## Step 1: collect data — controller audit

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

## Step 1b: snapshot for verification after restore

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

## Step 2: report on differences from stock

In the user-facing message, present **differences from a stock controller** — this is a useful artifact in itself:

- Additionally installed packages (`manual` minus stock) — list with versions
- Enabled services beyond stock (`enabled` minus standard WB services)
- Custom files and scripts (`opt`, `localbin`, `localsbin`, `units`) — with paths
- Modified configs (`dpkg` section) — which exactly
- User directories under `/mnt/data/` (`mntdata`) — with sizes
- Docker — installed or not, how many volumes/containers

Don't dump raw output — structure it like a human would. This is the first part of the response the user sees.

## Step 3: build the path list and immediately start Phase 2

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

- Dir < 100 MB → include.
- Dir 100 MB – 1 GB → include, but **warn in the message** "such-and-such directory is N MB — will go into the archive".
- Dir > 1 GB or named Docker volumes with DBs → **skip**, list in the message as "not in the archive, request separately if needed".
- Total final archive limit ~2 GB. If the heuristic exceeds that — trim the largest first.

In one message to the user: difference report + "including in the archive: ...; skipping as too large: ...". **Don't wait for a reply** — proceed straight to Phase 2.
