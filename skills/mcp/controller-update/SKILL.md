---
name: controller-update
description: WB package updates (apt upgrade) and release switching (wb-release -t) via MCP. Recon, HITL, verify.
allowed-tools: Bash Read Write WebFetch
---

# controller-update (MCP)

WB controller package updates and release transitions via `apt` and `wb-release -t`. All long commands — via `wb_ssh_exec_async`. Synchronous `wb_ssh_exec` will timeout, breaking apt mid-transaction.

**Do NOT run FIT firmware** (wb-fw-update, swupdate) — only via the controller's web UI.

## Tool routing

| Intent | Tool |
|--------|------|
| Current release / firmware version | `wb_probe` or `wb_ssh_exec` `wb-release` |
| Free space and load | `wb_metrics` |
| List of upgradable packages | `wb_ssh_exec` `apt list --upgradable` (after `apt-get update`) |
| `apt-get update`, `apt-get upgrade`, `apt-get dist-upgrade` | `wb_ssh_exec_async` |
| `wb-release -t <release>` (release switch) | `wb_ssh_exec_async` |
| Job progress | `wb_job_tail` |
| Job status | `wb_job_status` |
| Cancel (only before the critical install phase) | `wb_job_cancel` |
| State snapshot "before" | `wb_state_save` |
| Diff after update | `wb_state_diff` |
| Failed units after | `wb_failed` |
| Logs of key services after | `wb_logs` |
| Backup before release switch | skill `/controller-backup` |

## Recon — always first

```
wb_ssh_exec sn=<SN> cmd='echo === RELEASE ===; wb-release 2>&1; echo === KERNEL ===; echo "running: $(uname -r)"; dpkg -l "linux-image-wb*" | grep ^ii | awk "{print \"installed:\", \$3}"'
wb_metrics sn=<SN>                               # load, RAM, disk
wb_ssh_exec sn=<SN> cmd='apt-get update 2>&1 | tail -20'    # synchronous OK — apt update takes 2-5 sec
wb_ssh_exec sn=<SN> cmd='apt list --upgradable 2>/dev/null'
```

Don't truncate `apt list` output — wb packages are at the end of the alphabet.

**Free space on `/`:** `>= 1 GB` is normal; `500 MB – 1 GB` for a large upgrade requires `wb_ssh_exec` `apt-get clean; journalctl --vacuum-time=3d`; `< 500 MB` is critical — free up.

**Kernel mismatch before upgrade** = reboot first, then redo recon (see `/troubleshooting`).

`wb_state_save sn=<SN>` — "before" state snapshot, for later `wb_state_diff`.

**Counting "N upgradable, M wb-*":**
```
wb_ssh_exec sn=<SN> cmd='apt list --upgradable 2>/dev/null | tail -n +2 | sort -u | wc -l; apt list --upgradable 2>/dev/null | tail -n +2 | grep -cE "^(wb-|task-wirenboard|task-wb|libwbmqtt|frpc|knxd|telegraf-wb|u-boot-wb|linux-image-wb)"'
```
`sort -u` removes multiarch duplicates (one package in arm64+armhf is one package).

### Major-version risks

After recon, find major upgrades and highlight to the user — they don't go into the general flow:

| Package | When major | Action |
|---------|------------|--------|
| `docker-ce`, `containerd.io`, `docker-compose-plugin` | major change | Separate upgrade after the regular one, after compose-files review |
| `u-boot-wb*` | major change | Read package changelog, coordinate |
| `linux-image-wb*` | any | Reboot after upgrade is mandatory, warn in advance |
| `wb-rules`, `wb-mqtt-serial` with a jump >5 minor | large gap | Read release notes — config formats may change |

## Scenario A: package update

Triggers: "update packages", "apt upgrade", "are there updates?"

1. Show the user the upgradable list. **Wait for confirmation.**
2. Run:

   ```
   wb_ssh_exec_async sn=<SN> cmd='DEBIAN_FRONTEND=noninteractive apt-get -y upgrade'
   ```

3. Monitor via `wb_job_tail job_id=<id>`.
4. **Check kept-back.** If some packages remain — propose `dist-upgrade` (showing what will happen):

   ```
   wb_ssh_exec_async sn=<SN> cmd='apt-get -s dist-upgrade | grep -E "^(Inst|Remv)"'
   ```

   **Wait for confirmation.**

5. If the kernel was updated (`linux-image`) — warn: "A reboot is needed for the new kernel." Wait for confirmation, then:

   ```
   wb_ssh_exec sn=<SN> cmd='systemctl reboot'
   ```

6. Verify: `wb_failed`, `wb_logs unit=wb-rules lines=20`, `wb_state_diff` against the "before" snapshot.

## Scenario B: release switch (stable↔testing)

Triggers: "switch to testing", "change suite".

**Only for stable↔testing. Updating to a new stable — via apt upgrade (scenario A).**

1. Find the exact target release name: `WebFetch https://wirenboard.com/wiki/WB_Software_Releases`.
2. Make a backup: invoke `/controller-backup`.
3. **Wait for confirmation** specifying the target release.
4. Run:

   ```
   wb_ssh_exec_async sn=<SN> cmd='wb-release -y -t <target>'
   ```

5. SSH may briefly drop (network restart). The process keeps running (background job survives the disconnect). `wb_job_status` will be `running`. Wait and retry `wb_probe` / `wb_job_tail`.
6. After: `wb_ssh_exec` `wb-release; apt list --upgradable`, `wb_failed`, `wb_state_diff`.

## Scenario C: just check for updates

Recon commands above. No upgrade. Report: current release, N upgradable, of which M are wb-*.

## Scenario D: factory reset (factory state)

⚠️ **Destructive. Wipes EVERYTHING:** configs, user data, custom packages, Docker images, rules, templates. After reset the controller's SSH host key changes, root password reverts to factory (`wirenboard`). Custom root SSH key is gone — ssh-copy-id again. (The MCP server uses `StrictHostKeyChecking=no`, so after factory reset it will keep connecting without `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!`.)

The programmatic path is `/usr/bin/wb-factoryreset --force`:

1. **Backup is mandatory** (invoke `/controller-backup` in full, download locally):
   ```
   /controller-backup
   ```
   After reset, restoring is possible ONLY from this archive. **`/mnt/data/ai/` is also wiped** — the snapshot from `wb_state_save` will be gone, `wb_state_diff` after reset is impossible. If a diff is needed — download the snapshot file locally before reset (via `wb_read_file` or `scp`).

2. **Explicit user confirmation** — with reference to data loss and custom SSH key loss. Don't run on ambiguous wording.

3. **Run via async** (synchronous wb_ssh_exec will timeout, sleep 60 + reboot):
   ```
   wb_ssh_exec_async sn=<SN> cmd='/usr/bin/wb-factoryreset --force'
   ```

   The script internally:
   - checks `firmware-compatible: fit-factory-reset`,
   - creates flag `/mnt/data/.wb-update/wb_use_factory_fit.flag`,
   - waits ~60 sec until `wb-watch-update` initiates FIT firmware and reboot.

4. **Controller is unreachable for 2-5 minutes.** SSH session drops. After reboot retry `wb_probe sn=<SN>` — until it returns OK.

5. **After boot**: root password is `wirenboard`, host key is new (MCP server accepts, see above), custom keys are gone — `ssh-copy-id` again if needed.

6. **Restore** — per `RESTORE.md` from the backup.

**If the firmware doesn't support factory reset** — `wb-factoryreset` will print "not supported by this firmware". This is old firmware, factory reset is done only via web UI / Recovery USB.

## Gotchas

- **`apt-get update`** takes 2-5 seconds (only refreshes indexes) — `wb_ssh_exec` synchronous is fine. **`apt-get upgrade` / `dist-upgrade` / `wb-release -t`** are long, **only** `wb_ssh_exec_async`. Don't confuse.
- `wb-release -t` without `-y` — hangs waiting for stdin.
- Skipping the backup before release switch — custom configs may break.
- Reboot in the middle of `apt upgrade` — breaks dpkg.
- Not checking `wb_failed` after release switch — you'll miss failed services.
- Ignoring a major upgrade (Docker, containerd, u-boot, linux-image) — the user must decide on breaking changes.
- Not accounting for multiarch — `apt list --upgradable | wc -l` counts arm64 and armhf variants of one package as two. Use `sort -u`.

## Documentation

- Releases: <https://github.com/wirenboard/wb-releases/blob/master/README.md>
- Wiki: <https://wirenboard.com/wiki/WB_Software_Releases>
- Update: <https://wirenboard.com/wiki/Wirenboard_Update>
