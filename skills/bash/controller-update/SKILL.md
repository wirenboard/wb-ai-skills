---
name: controller-update
description: WB package upgrades (apt upgrade) and release switching (wb-release -t). Recon, HITL, verify.
allowed-tools: Bash Read Write WebFetch
---

# controller-update

Upgrading WB controller packages and switching between releases via `apt` and `wb-release -t`.

**FIT firmware flash is NOT run** (wb-fw-update, swupdate) — only via the controller's web UI.

## Recon — always first

```bash
# Step 1: current state + kernel mismatch (mismatch is a frequent cause of issues after upgrade; see /troubleshooting)
ssh root@<HOST> 'echo === RELEASE ===; wb-release 2>&1; echo === KERNEL ===; echo "running: $(uname -r)"; dpkg -l "linux-image-wb*" 2>/dev/null | grep ^ii | awk "{print \"installed:\", \$3}"; echo === DISK ===; df -h / /mnt/data | awk "NR==1 || /\/$|\/mnt\/data/"; echo === UPTIME ===; uptime'

# Step 2: refresh apt cache (synchronous is OK — apt-get update takes 2-5 sec, don't confuse with apt upgrade)
ssh root@<HOST> 'apt-get update 2>&1 | tail -20; echo ===; apt list --upgradable 2>/dev/null'
```

Don't truncate `apt list` — wb packages are at the end of the alphabet.

**Free space on `/`:**
- `>= 1 GB` — fine for an upgrade of any size.
- `500 MB — 1 GB` — borderline; for a large upgrade (95+ packages or one with linux-image) clean up first: `apt-get clean; journalctl --vacuum-time=3d`.
- `< 500 MB` — critical, the upgrade may not complete. Free up space first.

**Kernel mismatch:** if running and installed differ **before** the upgrade — reboot first, then recon again. After the upgrade of a new `linux-image-wb*` the mismatch will appear naturally, and a reboot will be needed afterwards.

**Counting "N upgradable, M wb-*"** for the report in Scenario C:
```bash
ssh root@<HOST> 'apt list --upgradable 2>/dev/null | tail -n +2 | sort -u | wc -l; apt list --upgradable 2>/dev/null | tail -n +2 | grep -cE "^(wb-|task-wirenboard|task-wb|libwbmqtt|frpc|knxd|telegraf-wb|u-boot-wb|linux-image-wb)"'
```
`sort -u` removes multiarch duplicates (`pkg/x.y.z arm64` and `pkg/x.y.z armhf` are one package in two architectures, count it as one). The wb-* prefix filter is a heuristic; refine for the specific list.

### Major-version risks

After step 2, eyeball the list: **major upgrades** require a separate decision and don't go in the general flow.

| Package | When major | What to do |
|-------|----------------|-----------|
| `docker-ce`, `containerd.io`, `docker-compose-plugin` | major change (28→29, 1→2, 2→5) | Daemon restart + breaking changes in compose schema. Read changelog, agree with the user, do as a separate upgrade after the regular one |
| `u-boot-wb*` | major change (2021→2025) | On WB the package usually contains a FIT image, doesn't flash itself. But check the changelog — there may be new environment requirements |
| `linux-image-wb*` | any change | Reboot needed, kernel mismatch until reboot |
| `wb-rules`, `wb-mqtt-serial` with a >5 minor version jump | large gap (e.g. 2.180 → 2.224) | Read release notes — config formats may change |

Highlight this to the user in the recon response — don't run `apt upgrade` silently over major version jumps.

## Scenario A: package upgrade

Triggers: "upgrade packages", "apt upgrade", "are there updates?"

1. Show the user the upgradable list. **Wait for confirmation.**
2. Run:
```bash
ssh root@<HOST> 'systemd-run --unit=wb-ai-upgrade --collect bash -c "DEBIAN_FRONTEND=noninteractive apt-get -y upgrade"'
```
3. Watch: `ssh root@<HOST> 'systemctl status wb-ai-upgrade; journalctl -u wb-ai-upgrade --no-pager | tail -30'`
4. **Check kept-back.** If some packages are held back — offer `dist-upgrade` (showing what will happen: `apt-get -s dist-upgrade | grep -E '^(Inst|Remv)'`). **Wait for confirmation.**
5. If the kernel was upgraded (`linux-image`) — warn: "A reboot is required for the new kernel." Wait for confirmation, then `ssh root@<HOST> 'systemctl reboot'`.
6. Verify: `systemctl --failed`, `journalctl -u wb-rules -n 20 --no-pager`

## Scenario B: switch release (stable↔testing)

Triggers: "switch to testing", "change suite"

**Only for stable↔testing. Upgrade to a new stable goes through apt upgrade (scenario A).**

1. Find out the exact target release name: `WebFetch https://wirenboard.com/wiki/WB_Software_Releases`
2. Make a backup: `/controller-backup`
3. **Wait for confirmation** with the target release specified.
4. Run:
```bash
ssh root@<HOST> 'systemd-run --unit=wb-ai-release --collect bash -c "wb-release -y -t <target>"'
```
5. SSH may temporarily drop (network restart). The process keeps running (`systemd-run --collect`). Wait and retry the check.
6. After: `wb-release`, `apt list --upgradable`, `systemctl --failed`

## Scenario C: just check for updates

Recon commands above. No upgrade. Report: current release, N upgradable, of which M are wb-*.

## Scenario D: factory reset

⚠️ **Destructive. Wipes EVERYTHING:** configs, user data, custom packages, Docker images, rules, templates. After reset the SSH host key changes, the root password reverts to factory (`wirenboard`). A custom root SSH key disappears — `ssh-copy-id` again.

Software path — `/usr/bin/wb-factoryreset`:

1. **Backup is mandatory**: invoke `/controller-backup` fully, download the archive locally. After reset you can't restore anything without it. **`/mnt/data/` is wiped completely** — including `/mnt/data/ai/` (snapshots, diag logs, backups). Download everything needed locally before the reset.

2. **User confirmation** — explicitly double-check, citing the loss of data and SSH key. Don't run on ambiguous wording ("clean the controller", "reset").

3. **Run**:
   ```bash
   ssh root@<HOST> '/usr/bin/wb-factoryreset --force'
   ```
   Without `--force` the script interactively requires typing `factoryreset` — `--force` skips the prompt. Internally it:
   - checks `firmware-compatible: fit-factory-reset` (whether firmware supports it),
   - creates the flag `/mnt/data/.wb-update/wb_use_factory_fit.flag`,
   - waits ~60 sec for `wb-watch-update` to initiate the FIT flash from `/mnt/data/.wb-restore/factoryreset.fit` and reboot.

4. **The SSH session will drop** during the flash. The controller is unreachable for 2-5 minutes.

5. **After boot** the controller is in factory state. Hostname stays the same (depends on SN), but the host key is new. Root password is `wirenboard`. Auth is back to password — distribute the key via `ssh-copy-id` if needed.

6. **Restore** — via `RESTORE.md` from the backup (see `/controller-backup` restore scenario).

**If firmware doesn't support factory reset** — `wb-factoryreset` complains "not supported by this firmware". That's an old firmware; factory reset can only be done by reflashing via web UI / Recovery USB.

## Pitfalls

- **`apt-get update`** takes 2-5 seconds (just refreshes indices) — synchronous over ssh is OK. **`apt-get upgrade` / `dist-upgrade` / `wb-release -t`** are long-running, via `systemd-run --collect`. Don't confuse them.
- `wb-release -t` without `-y` — hangs waiting for stdin.
- Skipping a backup before changing release — custom configs may break.
- Reboot in the middle of `apt upgrade` — breaks dpkg.
- After release switch, not checking `systemctl --failed`.
- Silently ignoring a major upgrade (Docker, containerd, u-boot, linux-image) — the user must decide on breaking changes.
- Not accounting for multiarch — `apt list --upgradable | wc -l` counts arm64 and armhf variants of one package as two. Use `sort -u` (see recon).

## Documentation

- Releases: <https://github.com/wirenboard/wb-releases/blob/master/README.md>
- Wiki: <https://wirenboard.com/wiki/WB_Software_Releases>
- Update: <https://wirenboard.com/wiki/Wirenboard_Update>
