---
name: wiren-board
description: Managing Wiren Board controllers via SSH/MQTT. Load this for any work with WB controllers.
allowed-tools: Bash Read Write Grep Glob WebFetch WebSearch
---

# wiren-board

Master skill for working with Wiren Board controllers from the Claude Code CLI. All operations go through Bash: SSH, mosquitto_sub, mosquitto_pub, avahi-browse, scp. Load this on any mention of WB controllers, MQTT topics, devices on the bus, automation rules, hardware configuration.

## Discovering controllers

### mDNS discovery

Wiren Board controllers announce via mDNS but **not on `_http._tcp`** (a common misconception — they don't publish a web service on port 80). Current firmwares publish `_workstation._tcp`. To make the recipe survive a service-type change — scan all service types and filter by name:

```bash
echo "$(timeout 5 avahi-browse -arp 2>/dev/null)" | awk -F';' '$1=="=" && $3=="IPv4" && $7 ~ /^wirenboard-/ {print $7, $8}' | sort -u
```

Flags: `-a` — all service types, `-r` — resolve (names + addresses), `-p` — parsable. **Without `-t`**, because `-t` exits as soon as the avahi cache is empty: on a cold first run the daemon hasn't received mDNS replies yet and `-t` cuts the scan in milliseconds before announcements arrive. `timeout 5` reliably gives avahi 5 seconds to gather replies regardless of cache state.

`echo "$(...)"` (instead of a direct pipe `timeout 5 avahi-browse ... | awk ...`) is mandatory. On SIGTERM from `timeout`, lines in the pipe buffer between `avahi-browse` and `awk` are lost, and the recipe gives empty output. Command substitution `$(...)` waits for full process completion and captures everything written to stdout before the signal.

avahi fields: `$1` — `=` for resolved entries (`+` = found but not resolved), `$3` — IPv4/IPv6 (filter to v4 for readability — IPv6 link-local `fe80::*` is useless for SSH from another host), `$7` — FQDN `wirenboard-<SN>.local`, `$8` — IP. `sort -u` removes duplicates from parallel IPv4/IPv6 announcements of one host.

Output: `wirenboard-A25NDEMJ.local 192.168.1.100`.

If the first run is empty — retry after 2-3 seconds (avahi may not have received replies yet, especially if the daemon just started or the interface came up recently).

If `avahi-browse` returns nothing — check daemon liveness and interfaces:

```bash
systemctl is-active avahi-daemon
# Which service types are visible at all (if only local — multicast is blocked on the network):
avahi-browse -t -a 2>/dev/null | awk '{print $5}' | sort -u
```

Resolving a specific name works around browse — global `nsswitch` via `mdns4_minimal`:

```bash
ping -c1 -W2 wirenboard-A25NDEMJ.local 2>/dev/null     # resolves and pings
getent hosts wirenboard-A25NDEMJ.local                 # NB: NSS doesn't always pick up .local — if empty, ping/ssh may still resolve via avahi-resolve
```

If the SN is known in advance, browse isn't required — go straight to `ssh root@wirenboard-<SN>.local`.

### Serial number format

- SN is alphanumeric, like `A25NDEMJ` (length may vary).
- Hostname: `wirenboard-<sn>.local` (e.g. `wirenboard-A25NDEMJ.local`).
- Get the SN from the controller manually:

```bash
ssh root@<ip> cat /var/lib/wirenboard/short_sn.conf
# or via MQTT:
ssh root@<ip> "mosquitto_sub -t '/devices/system/controls/Short SN' -C 1 -W 3"
```

### Determining firmware version

```bash
ssh root@<host> cat /etc/wb-fw-version                                    # timestamp YYYYMMDDHHMM
ssh root@<host> "grep -E '^(RELEASE_NAME|SUITE|TARGET)=' /usr/lib/wb-release"   # key fields
ssh root@<host> cat /usr/lib/wb-release                                   # all of it
```

`/usr/lib/wb-release` is shell notation. You can source it: `eval "$(ssh ... cat /usr/lib/wb-release)"; echo $RELEASE_NAME`. The file may contain extra fields (`REPO_PREFIX`, `FIRMWARE_COMPATIBLE`, etc.) depending on platform and version — don't rely on a fixed line count.

## SSH access

### Basic connection

By default: `ssh root@wirenboard-<sn>.local`, password `wirenboard`.

To avoid interactive prompts on first connect:

```bash
ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 root@wirenboard-<sn>.local '<command>'
```

`accept-new` accepts the host key only if the host isn't yet known (rather than on every connect, like `StrictHostKeyChecking=no`). After the first time, a real key change still raises an error — that's the right behavior.

### Non-interactive authentication (Linux)

So that batch operations don't get stuck on `Permission denied (publickey,password)`, there are two paths:

1. **Deploy the public key once** (recommended for ongoing work):
   ```bash
   ssh-copy-id -o StrictHostKeyChecking=accept-new root@wirenboard-<sn>.local
   ```
   After this, all `ssh root@wirenboard-<sn>.local` go without a password.

2. **`sshpass` for one-off sessions** (if you can't deploy a key — e.g. diagnosing on someone else's controller):
   ```bash
   sudo apt install -y sshpass     # one-time
   sshpass -p wirenboard ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 root@<host> '<command>'
   ```
   Password on stock firmware is `wirenboard`. Don't put it in scripts; pass via env (`SSHPASS=wirenboard sshpass -e ssh ...`) if needed.

### mDNS cache expires per-name

Avahi caches `wirenboard-<sn>.local` resolution for a limited time. After a pause between sessions, `ssh root@wirenboard-A25NDEMJ.local` may fail with `Could not resolve hostname`, even though `ping wirenboard-A25NDEMJ.local` resolves. Cure — a one-time discovery run (see above) before a series of SSH ops; it re-resolves **all** controllers in the cache. Alternative — use IPs.

### Short commands

Run directly:

```bash
ssh root@<host> 'systemctl is-active wb-mqtt-serial'
ssh root@<host> 'cat /etc/wb-mqtt-serial.conf'
ssh root@<host> 'df -h / /mnt/data'
```

### Long commands (apt, tar, builds)

For commands that may run longer than the SSH timeout, use nohup:

```bash
ssh root@<host> 'nohup bash -c "apt-get update && apt-get -y install <pkg>" > /tmp/wb-job.log 2>&1 &'
# After some time check the result:
ssh root@<host> cat /tmp/wb-job.log
```

### Background tasks via systemd

For tasks that must survive an SSH disconnect. **The best pattern is script-file + systemd `StandardOutput=append:`**: the command goes into a script file, systemd writes stdout/stderr to the log itself. No tricks with `bash -c '{ …; } > LOG 2>&1'` (where `;` redirected only the last command of the chain).

```bash
ID=$(head -c4 /dev/urandom | od -An -tx1 | tr -d ' ')
DIR=/mnt/data/ai/wb-ai-skills/jobs
ssh root@<host> bash -s <<EOF
mkdir -p $DIR
cat > $DIR/$ID.sh <<'JOB'
#!/bin/bash
set -o pipefail
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y install docker-ce
JOB
chmod +x $DIR/$ID.sh
date +%s > $DIR/$ID.started
systemd-run --unit=wb-ai-job-$ID --collect --quiet \\
  -p StandardOutput=append:$DIR/$ID.log \\
  -p StandardError=append:$DIR/$ID.log \\
  -p WorkingDirectory=/root \\
  /bin/bash $DIR/$ID.sh
EOF
echo "jobId=$ID"
```

Status check:

```bash
ssh root@<host> 'systemctl is-active wb-ai-job-<id>; systemctl show wb-ai-job-<id> -p Result,ExecMainStatus --no-pager; tail -30 /mnt/data/ai/wb-ai-skills/jobs/<id>.log'
```

Cancel:

```bash
ssh root@<host> 'systemctl stop wb-ai-job-<id>'
```

## MQTT operations (via SSH)

All MQTT operations are done via SSH on the controller, where the local Mosquitto runs.

### Reading a retained value

```bash
ssh root@<host> "mosquitto_sub -t '/devices/wb-mr6c_7/controls/K1' -C 1 -W 5"
```

Flags: `-C 1` — receive one message and exit, `-W 5` — 5-second timeout (won't hang if there's no retained value).

### Writing a value

```bash
ssh root@<host> "mosquitto_pub -t '/devices/wb-mr6c_7/controls/K1/on' -m '1'"
```

**Important:** to control a control, publish to `<topic>/on`, not to `<topic>` itself — otherwise the value is overwritten by the driver.

### Listing devices and topics

```bash
# Names of all devices
ssh root@<host> "mosquitto_sub -t '/devices/+/meta/name' -C 100 -W 3"

# All controls of a specific device
ssh root@<host> "mosquitto_sub -t '/devices/wb-mr6c_7/controls/+' -C 100 -W 3"

# Control type
ssh root@<host> "mosquitto_sub -t '/devices/wb-mr6c_7/controls/K1/meta/type' -C 1 -W 5"

# All retained topics with TAB separator between topic and payload (reliable parsing)
ssh root@<host> "mosquitto_sub -F '%t\\t%p' -t '/devices/#' -C 500 -W 5"
```

**Names with spaces.** Device and control names may contain spaces (`CPU Temperature`, `Board Temperature`, `Input 0`, `Input 0 counter` on WB-MR6C). Therefore:

- When parsing `mosquitto_sub` output, **don't use `-v`** (separator is space) and **don't split by `[/ ]`**. Use `mosquitto_sub -F '%t\t%p'` and `awk -F'\t'`.
- Topic in quotes: `mosquitto_sub -t '/devices/wb-mr6c_2/controls/Input 0' -C 1` — single quotes protect the space.
- In RPC and JSON — use names verbatim: `["wb-mr6c_2", "Input 0 counter"]`, no quotes/escape.

### MQTT RPC — calling controller services

RPC over MQTT is the main way to manage Wiren Board services (Modbus configuration, rules, config editor). Pattern:

```bash
ssh root@<host> bash -c '
  ID=$(cat /dev/urandom | tr -dc a-z0-9 | head -c8)
  mosquitto_sub -t "/rpc/v1/<service>/<method>/${ID}/reply" -C 1 -W 15 &
  SUB_PID=$!
  sleep 0.3
  mosquitto_pub -t "/rpc/v1/<service>/<method>/${ID}" -m '"'"'{"id":"'"'"'"$ID"'"'"'","params":<params_json>}'"'"'
  wait $SUB_PID
'
```

**How it works:**

1. A unique request ID is generated
2. Subscription to the reply topic `/rpc/v1/<service>/<method>/<ID>/reply` starts in the background
3. 0.3 s pause so the subscription has time to establish
4. Publishing the request to `/rpc/v1/<service>/<method>/<ID>` with JSON body `{"id":"<ID>","params":...}`
5. `wait` waits for the reply (timeout set by `-W`)

**Quote escaping:** Note `'"'"'` — that's the way to insert a single quote inside a single-quoted bash string. The construct `'"'"'` means: close single quote, open double quote, insert single quote, close double quote, open single quote again.

### Available RPC services

#### wb-mqtt-serial — Modbus/RS-485 driver

| Method | Purpose | Example params |
|---|---|---|
| `config/Load` | Current driver config + full **types** list (templates with `hw[].signature`) | `{}` |
| `device/LoadConfig` | **Firmware parameters** of a device (`fw`, `model`, `parameters`). Does **NOT** return channel list | `{"device_id":"wb-mr6c_138"}` or `{"path":"/dev/ttyRS485-1","baud_rate":9600,"parity":"N","data_bits":8,"stop_bits":2,"slave_id":138,"device_type":"WB-MR6C"}` |
| `device/Probe` | Check device presence on the bus | `{"path":"/dev/ttyRS485-1","baud_rate":9600,"slave_id":138}` |
| `ports/Load` | List of available ports | `{}` |

**Bus scanning — via `wb-device-manager`, not `wb-mqtt-serial/port/Scan`.** The old `port/Scan` silently misses live WB devices (observed on WB-MAP6S). The new interface is async with retained state:

| Method | Purpose | params |
|---|---|---|
| `wb-device-manager / bus-scan / Start` | Start scanning | `{"scan_type":"extended","preserve_old_results":false,"port":{"path":"/dev/ttyRS485-1","baud_rate":115200,"parity":"N","data_bits":8,"stop_bits":2}}` |
| `wb-device-manager / bus-scan / Stop` | Interrupt | `{}` |
| Progress/result | retained `/wb-device-manager/state` | `{"scanning":bool,"progress":0..100,"devices":[...]}` |

`scan_type:"extended"` = Fast Modbus (WB+Onokom, seconds). `scan_type:"standard"` = regular Modbus (slower, sees third-party).

> The list of **channels** of a device (with `enabled:false` channels) on current firmwares is **not returned** by any RPC method. Read the template file directly: `cat /usr/share/wb-mqtt-serial/templates/config-<device.id>.json`. The `templates/GetTemplate` method is declared but in wb-2602/wb-2507 times out — don't use.

Example — load wb-mqtt-serial config:

```bash
ssh root@<host> bash -c '
  ID=$(cat /dev/urandom | tr -dc a-z0-9 | head -c8)
  mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/config/Load/${ID}/reply" -C 1 -W 15 &
  SUB_PID=$!
  sleep 0.3
  mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/config/Load/${ID}" -m '"'"'{"id":"'"'"'"$ID"'"'"'","params":{}}'"'"'
  wait $SUB_PID
'
```

Example — port scan (via wb-device-manager, async):

```bash
# 1. Start the scan (Start doesn't wait for completion, progress is via retained state)
ssh root@<host> bash -c '
  ID=$(cat /dev/urandom | tr -dc a-z0-9 | head -c8)
  mosquitto_sub -t "/rpc/v1/wb-device-manager/bus-scan/Start/${ID}/reply" -C 1 -W 10 &
  SUB_PID=$!
  sleep 0.3
  mosquitto_pub -t "/rpc/v1/wb-device-manager/bus-scan/Start/${ID}" -m '"'"'{"id":1,"params":{"scan_type":"extended","preserve_old_results":false,"port":{"path":"/dev/ttyRS485-1","baud_rate":115200,"parity":"N","data_bits":8,"stop_bits":2}}}'"'"'
  wait $SUB_PID
'

# 2. Wait for scanning:false (polling retained state)
ssh root@<host> 'for i in $(seq 1 60); do
  s=$(mosquitto_sub -t /wb-device-manager/state -C 1 -W 2)
  echo "$s" | jq -r ".scanning, .progress" | xargs echo
  echo "$s" | jq -e ".scanning == false" >/dev/null && break
  sleep 2
done'

# 3. Pull devices from state
ssh root@<host> 'mosquitto_sub -t /wb-device-manager/state -C 1 -W 3 | jq ".devices"'
```

**Don't use `wb-mqtt-serial/port/Scan`** — it silently misses live WB devices (observed on WB-MAP6S). Only `wb-device-manager/bus-scan/Start` (see above).

#### confed — config editor

| Method | Purpose | Example params |
|---|---|---|
| `Editor/Load` | Load a config | `{"path":"/etc/wb-mqtt-serial.conf"}` |
| `Editor/Save` | Save a config (with validation and service restart) | `{"path":"/etc/wb-mqtt-serial.conf","content":"<full JSON>"}` |

**Use `confed/Editor/Save` instead of writing config files directly** — it validates JSON and atomically restarts the dependent service. Direct write of broken JSON can stop bus polling.

#### wbrules — rules engine

| Method | Purpose | Example params |
|---|---|---|
| `Editor/List` | List of rule files with `{enabled, virtualPath, rules, devices, timers}` | `{}` |
| `Editor/Load` | Read a rule file | `{"path":"wb-la-climate.js"}` |
| `Editor/Save` | Save a rule (JS validation + reload) | `{"path":"wb-la-climate.js","content":"<JS code>"}` |
| `Editor/Remove` | Delete a rule file | `{"path":"wb-la-climate.js"}` → `{"result":true}` |
| `Editor/ChangeState` | Disable (`<name>.js` → `<name>.js.disabled`) or enable a whole file | `{"path":"wb-la-climate.js","enabled":false}` (re-enable via `enabled:true` is unreliable — see the `wb-rules` skill) |
| `Editor/Rename` | Rename a file (untested) | `{...}` |

Example — list rules:

```bash
ssh root@<host> bash -c '
  ID=$(cat /dev/urandom | tr -dc a-z0-9 | head -c8)
  mosquitto_sub -t "/rpc/v1/wbrules/Editor/List/${ID}/reply" -C 1 -W 15 &
  SUB_PID=$!
  sleep 0.3
  mosquitto_pub -t "/rpc/v1/wbrules/Editor/List/${ID}" -m '"'"'{"id":"'"'"'"$ID"'"'"'","params":{}}'"'"'
  wait $SUB_PID
'
```

## File operations

### Read a file from the controller

```bash
ssh root@<host> cat /etc/wb-mqtt-serial.conf
```

### Write a file to the controller

```bash
echo 'file content' | ssh root@<host> 'cat > /path/to/file'
```

For multi-line content:

```bash
ssh root@<host> 'cat > /etc/wb-rules/my-rule.js' << 'REMOTEFILE'
defineRule("my-rule", {
  whenChanged: "wb-gpio/A1_OUT",
  then: function(newValue) {
    dev["wb-mr6c_7/K1"] = !!newValue;
  }
});
REMOTEFILE
```

### Download a file from the controller to the local machine

```bash
scp root@<host>:/path/to/file ./local-file
```

### Upload a file to the controller

```bash
scp ./local-file root@<host>:/path/to/file
```

### Working with directories

```bash
# Download a directory recursively
scp -r root@<host>:/etc/wb-rules ./wb-rules-backup

# Upload a directory
scp -r ./configs root@<host>:/mnt/data/
```

## Safety rules

### FORBIDDEN

- **Don't run a FIT firmware flash** (`wb-fw-update`, `swupdate`, `wb-run-update`, `fit-update`) — flashing only via the controller's web UI. FIT overwrites rootfs entirely; an error can brick the controller.
- **`wb-factoryreset` — only with explicit user confirmation and a mandatory backup before.** Wipes all user data (configs, rules, templates, Docker images), root password reverts to `wirenboard`, custom SSH keys disappear. Full scenario — in `/controller-update` (Scenario D). Don't run on ambiguous wording ("clean up", "reset").

### Backup before editing configs — MANDATORY

Before changing any configuration file:

```bash
ssh root@<host> 'cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)'
```

Examples of configs requiring a backup: `wb-mqtt-serial.conf`, `wb-hardware.conf`, files in `/etc/network/`, `/etc/mosquitto/`, `/etc/wb-rules/`.

### RPC instead of direct file editing

For the following configs use RPC, not direct write:

| Config | RPC service | Why |
|---|---|---|
| `/etc/wb-mqtt-serial.conf` | `confed/Editor/Save` | JSON validation + atomic driver restart |
| Rules `/etc/wb-rules/*.js` | `wbrules/Editor/Save` | JS validation + hot reload |
| `/etc/wb-hardware.conf` | `confed/Editor/Save` | Validation + apply without reboot |

### User confirmation

**Ask for confirmation before:**
- Destructive operations: `rm`, `reboot`, `dpkg --remove`, `apt-get purge`
- Restarting critical services: `systemctl restart wb-mqtt-serial`, `systemctl restart mosquitto`
- Changing network configuration (you can lose access)
- Stopping Docker containers

**WITHOUT confirmation (do immediately):**
- Diagnostics and reading: `cat`, `journalctl`, `systemctl status`, `mosquitto_sub`, `df`, `ip addr`
- Reading MQTT topics
- Bus scanning
- Viewing logs

### Logs — only fresh

After restarting a service, look only at fresh logs, not the whole journal:

```bash
ssh root@<host> 'journalctl -u wb-mqtt-serial --since "1 min ago" --no-pager'
```

For long journals:

```bash
ssh root@<host> 'journalctl -u <service> -n 50 --no-pager'
```

## Typical diagnostic commands

```bash
# Failed services
ssh root@<host> 'systemctl --failed --no-pager'

# Disk space
ssh root@<host> 'df -h / /mnt/data'

# Load and memory
ssh root@<host> 'uptime; free -h'

# Errors in the journal
ssh root@<host> 'journalctl -p err -n 50 --no-pager'

# Kernel mismatch (a frequent cause of issues after upgrade)
ssh root@<host> 'echo "running: $(uname -r)"; dpkg -l linux-image-wb* 2>/dev/null | grep ^ii | awk "{print \"installed:\", \$3}"'

# List of serial ports
ssh root@<host> 'ls /dev/ttyRS485-* /dev/ttyMOD* 2>/dev/null'

# Check the MQTT broker
ssh root@<host> 'systemctl is-active mosquitto && mosquitto_sub -t "/devices/+/meta/name" -C 5 -W 3'
```

## Skills

Available skills for specific tasks — invoke `/skill-name` when the task falls into their area:

| Skill | Area |
|---|---|
| `/wb-mqtt-serial` | Configuring Modbus devices via RPC, enabling/disabling channels, adding devices |
| `/serial-templates` | Creating custom Modbus templates (when there's no built-in one) |
| `/wb-rules` | JavaScript automation rules (defineRule, virtual devices, timers, cron) |
| `/scenarios` | Declarative web UI scenarios (devicesControl, lightControl, thermostat, schedule) |
| `/notifications` | Telegram/Email/SMS from rules (`Notify.*`), `alarms.conf` |
| `/troubleshooting` | General diagnostics: failed services, disk space, kernel mismatch, Docker |
| `/troubleshooting-serial` | RS-485/Modbus: CRC errors, timeouts, signal issues, OWON |
| `/services` | systemd: override-conf, drop-ins, custom units/timers, mask/unmask |
| `/network` | NetworkManager + wb-connection-manager: ethernet/wifi/4G/OpenVPN, failover |
| `/wb-cloud` | Wiren Board Cloud agent: activation, status, unbinding |
| `/mqtt-broker` | mosquitto admin: users, ACLs, bridges, TLS |
| `/controller-backup` | Full controller backup: configs, packages, data, Docker volumes |
| `/controller-update` | Firmware and package updates |
| `/hardware-modules` | Expansion modules (MOD1-MOD4): Zigbee, CAN, RS-485, relay |
| `/software-install` | Software installation: Docker, Zigbee2MQTT, Home Assistant, Node-RED, Grafana |
| `/zigbee` | Zigbee devices: pairing, control, groups, OTA |
| `/history` | Historical data, charts, export |
| `/diagrams` | Mermaid diagrams to visualize logic |
| `/documentation-search` | Searching the Wiren Board wiki and GitHub repos |
| `/bugreport` | Composing a bug report with a diagnostic archive |

## Working principles

1. **Diagnose first, act second.** Before changing anything — understand the current state. Read the config, check the logs, look at MQTT topics.

2. **Don't guess topic names — verify via mosquitto_sub.** Device and control names depend on the specific controller's configuration. Always first (format `topic\tpayload` — TAB separator is more reliable than `-v`, names may have spaces):
   ```bash
   ssh root@<host> "mosquitto_sub -F '%t\\t%p' -t '/devices/+/meta/name' -C 50 -W 3"
   ```

3. **Don't ask "do you want to" — do it.** The user will stop you if needed. Exception — destructive operations (see safety rules above).

4. **Act autonomously.** Verify facts via SSH, don't ask "is X installed?" or "what's your IP?" — find out yourself:
   ```bash
   ssh root@<host> 'dpkg -l | grep docker'
   ssh root@<host> 'ip addr show'
   ```

5. **Templates and configs — from the controller, not from the internet.** On the hardware is the current version matching the installed firmware. Don't download templates from GitHub — use RPC `device/LoadConfig` or `templates/GetTemplate`.

6. **Documentation — before fixing.** For typical tasks (Docker, Zigbee, Home Assistant) first read the corresponding wiki page via WebFetch: `https://wiki.wirenboard.com/wiki/<topic>`.
