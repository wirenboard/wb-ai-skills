# Phase 2 — building the archive

**All steps put files into one directory on the controller.** In Phase 3, the whole directory is packed into a single archive — no need to merge by hand.

> Note: core-tar includes `mnt/data/etc` recursively — so `/mnt/data/etc/docker/`, `/mnt/data/etc/wb-mqtt-serial.conf` (via symlink), etc. are **already there**. Don't duplicate them in audit-files-tar.

## Step 1: metadata and core configs

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

## Step 2: data based on audit results

```bash
ssh root@<HOST> 'wb-cli --json job run backup-audit "tar czf <BACKUP_DIR>/audit-files.tar.gz --warning=no-file-changed --ignore-failed-read <paths from audit> 2>/dev/null || true; du -sh <BACKUP_DIR>/audit-files.tar.gz"'
```

Substitute **specific paths** from Phase 1 step 3:

- Custom files: `/opt/my-app/`, `/usr/local/bin/my-script.sh`
- Custom systemd units: `/etc/systemd/system/my-service.service`
- Modified configs: `/etc/mosquitto/mosquitto.conf`
- User directories: `/mnt/data/picoclow-docker/` — these are user projects, back up!
- Configs of extra packages: paths from `dpkg -L`
- Configs of known packages (table below): `/mnt/data/root/zigbee2mqtt`, `/etc/mosquitto`, `/etc/nginx`, `/var/lib/grafana/grafana.db`, `/etc/influxdb`, `/root/.node-red/flows*.json`, `/root/.node-red/settings.js`, `/mnt/data/etc/docker`, `/etc/cron.d`

## Step 3: named Docker volumes (if Docker is present)

If `docker-ce` is among the extra packages:

```bash
ssh root@<HOST> "docker volume ls -q 2>/dev/null"
```

If there are volumes with data:

```bash
ssh root@<HOST> 'wb-cli --json job run backup-docker "for v in \$(docker volume ls -q); do docker run --rm -v \$v:/data alpine tar czf - /data > <BACKUP_DIR>/docker-volume-\$v.tar.gz 2>/dev/null; done; ls -lh <BACKUP_DIR>/docker-volume-*.tar.gz 2>/dev/null"'
```

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
