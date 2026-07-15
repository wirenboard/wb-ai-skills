# Worked case: Zigbee outage after a release upgrade

A field ticket: "after updating to release X, zigbee2mqtt periodically dies and stays dead until
reboot." Used here as a **template** for the wb-rca method, plus a set of reusable mosquitto/systemd
facts. Names/IPs are placeholders — substitute the real stand.

## The proven chain (symptom → trigger → root)

```
[catalyst: a client emitting MQTT v5 packets WITH properties]        ← THE REGRESSION
   → mosquitto bug #3192: memory-COUNTER leak (RSS stays flat)       [present in old & new mosquitto]
   → counter climbs to WB config memory_limit 100M                    [active for years, not new]
   → broker refuses clients ("... disconnected due to out of memory") [safety valve, not a crash]
   → continued v5-property traffic while pegged → mosquitto self-exits (non-clean)   ← trigger
   → systemd: mosquitto inactive → zigbee2mqtt has BindsTo=mosquitto  → z2m killed by SIGTERM
   → Restart=always does NOT revive it (dependency teardown = success) → Zigbee dead until reboot
```

## How each link was proved (and what got refuted)

| Claim | Method | Verdict |
|---|---|---|
| z2m dies via `BindsTo`, not OOM | copy the real unit, `kill -9` mosquitto, watch teardown | 🟢 proved |
| clean `systemctl restart mosquitto` is survived | restart, z2m stays up | 🟢 proved |
| `memory_limit` crashes the broker | isolated broker, flood past limit | 🟢 **refuted** — it disconnects clients, stays up |
| WB config `30limits.conf` changed → regression | git commits API on the file | 🟢 **refuted** — unchanged since 2024 |
| `include_dir`/`fix_mosquitto.sh` activated the limit | read the commit **diff** (both +/−) | 🟢 **refuted** — a *move* (−postinst/+script), limit was always active |
| mosquitto 2.0.11→2.0.20 jump is the regression | A/B both binaries, **v5 + properties** | 🟢 **refuted** — both leak identically (bug is old) |
| bug #3192 is the leak | upstream changelog + fix commit `property__free` `free()`→`mosquitto__free()`; reproduced counter+RSS | 🟢 confirmed |
| pegged counter + v5 traffic → broker exits | isolated broker, low limit, peg, hammer v5 | 🟢 proved (self-exit, no clean shutdown, no segfault/OOM-kill) |
| which catalyst client is new in release X | — | 🔴 needs pre/post version diff / reporter data |

Note the two false roots that *only* die under experiment: "memory_limit crashes it" and
"the include_dir commit activated the limit." Both are seductive from a log or a one-sided diff.

## Reusable facts

### systemd dependency teardown (WB packaged units)
- `BindsTo=<dep>`: if `<dep>` goes inactive (crash/unclean exit), systemd **stops** this unit too,
  with SIGTERM, recorded as a clean stop → `Restart=` won't bring it back.
- `BindsTo` propagates *stop* but not *start* — after `<dep>` recovers, the bound unit stays down.
- A clean `systemctl restart <dep>` is typically survived (restart is coalesced/propagated); only an
  independent unclean death triggers the fatal teardown. Test both paths.
- The `.deb`-shipped unit can differ from a manual install script — read the shipped one
  (`dpkg-deb -x <pkg>.deb …` or `systemctl cat`). Manual `install.sh` may lack the `BindsTo` the deb adds.

### mosquitto memory
- `memory_limit N` (WB sets `100000000` in `/usr/share/wb-configs/mosquitto/30limits.conf`, together
  with `max_queued_messages 0` = unlimited queue): a soft cap. On hit → `Client … disconnected due to
  out of memory`, broker **stays alive**. It is a safety valve, not the cause of a crash.
- Bug **#3192** (fixed upstream **2.0.21**, commit `015fe3d68784`): `property__free()` used raw
  `free()` instead of `mosquitto__free()` → the tracked-memory **counter** is never decremented when
  freeing MQTT-property structures. Any **MQTT v5 packet carrying properties** leaks the counter.
  Symptom: `$SYS/broker/heap/current` rises steadily while RSS (`/proc/<pid>/status`) stays flat;
  eventually the counter reaches `memory_limit` and the broker starts refusing clients — and under
  continued v5 load can self-exit. **Fix: mosquitto ≥ 2.0.21.**
- Read the counter vs real memory separately:
  `mosquitto_sub -t '$SYS/broker/heap/current' -C 1` (counter) vs
  `awk '/VmRSS/{print $2}' /proc/<pid>/status` (real RSS).

## Repro snippets (isolated brokers, safe on a stand)

```bash
# --- A/B an old vs new mosquitto on spare ports ---
apt-get download mosquitto=<oldver>            # e.g. from debian-security
dpkg-deb -x mosquitto_<oldver>_*.deb /tmp/mqold
printf 'listener 1998\nallow_anonymous true\npersistence false\nmemory_limit 0\nsys_interval 1\n' >/tmp/ab.conf
/tmp/mqold/usr/sbin/mosquitto -c /tmp/ab.conf &     # old on 1998
# (repeat with /usr/sbin/mosquitto on 1997 for the new version)

# --- exercise the v5-property leak path (counter grows, RSS flat) ---
mosquitto_pub -p 1998 -V 5 -D CONNECT user-property a b -D PUBLISH user-property c d -t l/x -m hi

# --- prove BindsTo teardown with a faithful copy of the real unit ---
# ExecStart replaced by a keep-alive stub so only the dependency behaviour is under test:
#   [Unit] After=network.target <dep>.service / BindsTo=<dep>.service
#   [Service] ExecStart=/bin/sh -c 'while :; do sleep 5; done' / Restart=always
kill -9 "$(systemctl show <dep> -p MainPID --value)"    # unclean death → watch the bound unit die & stay dead
```

**Cleanup after any repro:** `pkill -f 'mosquitto -c /tmp'`; remove test units + `daemon-reload`;
`rm` downloaded debs / extracted dirs / temp confs; confirm the system service is healthy
(`systemctl is-active mosquitto`, `$SYS` heap sane).
