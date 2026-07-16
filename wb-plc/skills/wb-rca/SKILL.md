---
name: wb-rca
description: "Reproduce a reported Wiren Board problem and PROVE its root cause, then write a defensible bug report. Use whenever someone reports that something is broken, misbehaving, or 'unexpected' and wants it reproduced or explained — plain first-person reports count: 'I have a bug', 'reproduce it', 'it behaves strangely', 'why does this happen', 'broke/stopped after an update', 'dig into this', 'find the root cause', 'is this a regression', 'I need a bug report'. This is the PROVE-why lane — reach for it over wb-troubleshooting (symptom→fix / restore service) whenever the goal is to explain or reproduce rather than only un-break; when the defect is in homeui, pair with wb-webui-test and bring the root cause here."
---

# wb-rca — root-cause investigation of WB problems & regressions

For turning a vague field complaint ("Zigbee отваливается после обновления на 2606") into a
**proven** root cause with a reproducible bug report. Audience: engineers/support doing RCA on WB
controllers, Modbus/MQTT/systemd/firmware issues.

## Quick Start

1. **Treat every reported conclusion as a hypothesis, not a fact** — including support's and other
   engineers' diagnoses. Reproduce and prove yourself.
2. **Get a dedicated test controller** (never prod / never the customer's box). Match its `release_name`
   to the report: `ssh root@<HOST> wb-cli --json info`.
3. **Separate three layers:** *symptom* (what the user sees) → *trigger* (the immediate event) →
   *root* (why the event happens). Each is a separate claim to prove.
4. **Reproduce the trigger** on the stand with the smallest experiment that shows the behaviour.
5. **Ground every causal claim** in a source: git history, upstream changelog/commit, or the package
   internals — not reasoning alone.
6. **A/B to test a regression:** run the old and new versions side by side and compare.
7. **Keep a confidence ledger:** 🟢 proved by experiment · 🟡 from reported data · 🔴 not established.
   Never upgrade 🔴→🟢 by argument; only by evidence.
8. **Leave an artefact** (dossier: method→result→conclusion + sources + repro commands), then **clean
   the stand**.

## The method

### 1. Reproduce (on a test controller)
- Discover + connect: see `wiren-board` skill (mDNS `wirenboard-<SN>.local`, ssh, `wb-cli --json`).
- Recreate the environment from the report: same release, same package versions, same component.
- Build the **minimal** reproduction. Prefer isolated instances (e.g. a second `mosquitto -c` on
  another port) over touching system services — safer and cleaner to reason about.
- Couldn't reproduce? Say so, and base conclusions on logs, marked 🟡 — don't claim a proven fix.

### 2. Split symptom → trigger → root
Ask "what directly caused this?" repeatedly until you hit something you can change. Example from the
`references/` case: z2m dead (symptom) ← mosquitto went inactive (trigger) ← systemd `BindsTo`
teardown + a mosquitto counter-leak bug (roots). Prove each arrow independently.

### 3. Ground claims (don't reason — verify)
- **Config/line age:** GitHub commits API for the exact file
  `.../commits?path=<path>` → is the suspect line old or new?
- **Version behaviour:** upstream changelog + the fix commit diff (which line, which version).
- **Package internals:** `apt-get download <pkg>` → `dpkg-deb -x` / `-e` to read the shipped
  unit file, maintainer scripts, configs — the `.deb` may differ from the manual install path.
- **Reading a "regression" diff:** check **both** `+` and `−`. A block *moved* between files looks
  like an *addition* if you only read the `+` side — a classic false root cause.

### 4. A/B versions to isolate a regression
- Pull the previous version's binary: `apt-get download <pkg>=<oldver>`; run it isolated on a spare
  port; drive the identical scenario against old and new; compare the metric.
- **Exercise the code path that actually triggers the bug** — protocol version, message shape, and
  feature flags matter. An A/B on the wrong path "clears" a guilty version (learned the hard way:
  MQTT v3.1.1 vs v5-with-properties gave opposite verdicts).

### 5. Refute, don't assert
Each hypothesis gets an experiment that could kill it. Report refutations as first-class results
("hypothesis X refuted: …"). A hypothesis that survives a genuine refutation attempt is worth far
more than one merely asserted.

### 6. Close the chain end-to-end
Don't stop at a plausible intermediate ("broker refuses clients"). Drive to the actual failure state
the report shows ("broker process exits"). A gap in the chain is a 🔴, not a 🟢.

### 7. Before/after-fix proof (gold standard)
Reproduce with the buggy version, apply the fix (or run the fixed version), show it's gone. This is
what turns "likely cause" into "proven cause".

## Pitfalls (WB-specific, read the world right)
- **`code=killed, signal=TERM`** in `systemctl status` = systemd **stopped** the unit (dependency /
  `systemctl stop`), **not** the kernel OOM-killer (that sends SIGKILL/9).
- **mosquitto `memory_limit` is a safety valve, not a killer** — on hit it logs `Client … disconnected
  due to out of memory` and drops the client; the broker keeps running. "out of memory" in the log
  ≠ a crash.
- **`$SYS/broker/heap/current` growing while RSS (`/proc/<pid>/status`) stays flat = a memory *counter*
  leak** (tracked-alloc/untracked-free), not real RAM growth. Different failure mode, different fix.
- **systemd `BindsTo=`/`PartOf=` on WB units:** a *clean* `systemctl restart dep` is usually survived
  (systemd coalesces the restart); an *unclean* death of the dep tears the unit down with SIGTERM and
  `Restart=` does **not** revive it (the teardown is recorded as `success`). Check the real unit with
  `systemctl cat` / by extracting it from the `.deb`.
- **Test-controller USB-Wi-Fi drops under fork-storm load** (thousands of rapid client spawns) — use
  wired Ethernet for heavy repros, or throttle the load.
- **`auto-<UUID>` client ids** in mosquitto logs = clients that connected with an empty client_id.

## References
- `references/mqtt-zigbee-outage-case.md` — the worked case (Zigbee outage after a release upgrade):
  the full symptom→trigger→root chain, the mosquitto `#3192` counter-leak, the `BindsTo` teardown,
  and ready-to-reuse mosquitto/systemd facts. Reach for it as a template and for those specific facts.

## What the agent does NOT do
- **Run RCA experiments on production or the customer's controller.** Always a dedicated stand.
- **Accept a support/engineer conclusion as ground truth** without independent reproduction.
- **Claim a root cause reached only by reasoning.** If not reproduced, it stays 🔴 / 🟡.
- **Leave test artefacts behind** — remove test units, isolated brokers, downloaded debs, temp files;
  confirm the system service is healthy afterwards.
- **Silently upgrade confidence** — don't restate a 🔴 as settled once more of the chain is proven
  elsewhere; each link needs its own evidence.

## When to ask the user
- More than one candidate test controller — which stand to use.
- Before any repro step that changes shared/stand state (service restarts, pairing, firmware).
- The true root needs data only the reporter has (their `journalctl`/`dmesg`/pre-upgrade versions) —
  surface exactly what to collect instead of guessing.
- A destructive before/after-fix test (downgrade, package pin) on a controller others use.

## Documentation
- `wiren-board` skill — discovery, ssh, `wb-cli --json` conventions.
- `wb-troubleshooting` — symptom→fix diagnostics; `wb-mqtt-broker`, `wb-zigbee` — component specifics.
- `wb-webui-test` — observe/reproduce a homeui defect in the browser, then bring the root cause here.
