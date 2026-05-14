# Phase 3 — delivery, and restore workflow

Wait for all Phase 2 steps to finish (core + audit-files + docker volumes if any).

## 3.1 RESTORE.md

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

## 3.2 Pack into a single file

```bash
ssh root@<HOST> 'wb-cli --json job run backup-pack "cd /mnt/data/ai/wb-ai-skills/backups && tar czf backup-<TS>.tar.gz <TS>/ && du -sh backup-<TS>.tar.gz"'
```

## 3.3 Check size and deliver

```bash
ssh root@<HOST> "stat -c%s /mnt/data/ai/wb-ai-skills/backups/backup-<TS>.tar.gz"
```

- < 200 MB → download:
  ```bash
  scp root@<HOST>:/mnt/data/ai/wb-ai-skills/backups/backup-<TS>.tar.gz ./
  ```
- > 200 MB → suggest the user copy it themselves via scp

## 3.4 Final report

- Which extra packages need installing during restore — list specific names
- What was saved (specific paths)
- What was NOT saved — warn:
  - `/mnt/data/.docker/` (Docker daemon's internal storage: images, layers) — restored via `docker pull` / `docker compose pull`
  - Large DBs (InfluxDB) — `influxd backup` manually
  - Node-RED `node_modules` — restored via `npm install`

## Restore workflow (from an existing backup)

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
