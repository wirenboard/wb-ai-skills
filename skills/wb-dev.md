---
name: wb-dev
description: "Writing software or integrations for Wiren Board: custom daemons, protocol bridges (e.g. Zigbee2MQTT → WB MQTT, Modbus → MQTT), MQTT conventions, MQTT-RPC services, wbdev cross-compilation, Debian packaging. NOT for wb-rules JS automation."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# wb-dev — software development for Wiren Board

## When to load this skill

Load when the task involves **writing code** that runs on or talks to a WB controller:

- Custom daemon / service (C++, Python, Go)
- Integration bridge — translating a third-party protocol into the WB MQTT device/control model  
  (e.g. Zigbee2MQTT → `/devices/…/controls/…`, KNX → WB, custom hardware → WB)
- MQTT-RPC service or client
- Debian packaging of any of the above

**Do NOT load** for:
- wb-rules JavaScript automation → use `/wb-rules` instead
- Controller administration (network, broker config) → use the relevant skill

## MQTT representation — mandatory for all integrations

**Every integration or service running on WB must expose its state and any connected devices/sensors as MQTT virtual devices following the WB conventions** (see the [MQTT conventions](#mqtt-conventions) section below).

This is non-negotiable — the web interface, wb-rules automation, and other services on the controller all consume the unified `/devices/…/controls/…` topic space. An integration that talks only to its own internal bus or API without publishing to MQTT is invisible to the rest of the WB ecosystem.

**What to expose:**

| What you have | What to publish |
|---|---|
| Integration service itself | A virtual device with status/version controls, e.g. `/devices/my-integration/controls/status` |
| Connected physical device (sensor, actuator) | A virtual device per unit: `/devices/my-sensor_1/…` |
| Numeric reading (temperature, power, etc.) | A `value` control with `units` set |
| On/off controllable output | A `switch` control (writable, no `readonly`) |
| Service error or connectivity loss | Set `/devices/<id>/meta/error` non-empty (LWT pattern) |

All meta topics (`/devices/<id>/meta`, `/devices/<id>/controls/<id>/meta`) must be published with the **retained** flag on startup.

## Architectures and libc

| Controller | Architecture | libc |
|---|---|---|
| WB8 | arm64 | 2.31 |
| WB6 / WB7 | armhf | 2.31 |
| WB5 and earlier | armel | 2.31 |

Compiling directly on the controller is discouraged (limited RAM). Use cross-compilation via `wbdev`.

## Deployment: Docker vs deb

**Default to Docker** for custom software and integrations. Use a deb package only when the package is small, self-contained, and has no external runtime dependencies.

**Decision rule:**
- Package is small, standalone, pure Python/Go/C++ with deps already in the WB apt repo → **deb is fine**
- Package installs third-party software alongside it (Node.js, additional Python packages, databases, etc.) or that third-party software is already running in Docker → **package everything as Docker from the start**; mixing deb + Docker for the same service adds unnecessary complexity

| | Docker | deb package |
|---|---|---|
| Root partition impact | None | Uses limited root space |
| Survives firmware update | Yes (data in `/mnt/data`) | Config in `/etc` may be reset |
| Dependency management | Bundled in image | Requires WB apt repo |
| When to use | Complex integrations, third-party runtimes, anything co-located with Dockerized software | Small self-contained daemon with only WB-apt deps |

### Docker on WB — critical rules

**Follow the WB wiki, not generic Docker docs:** `WebFetch('https://wiki.wirenboard.com/wiki/Docker')`

- Docker CE is installed via `wb-docker-manager.sh` (not `apt install docker-ce` — that breaks the storage path)
- **All Docker data and compose projects go in `/mnt/data/`** — the larger partition, survives firmware updates
- Compose projects live under `/mnt/data/<project>/docker-compose.yml`
- Never store images or volumes on the root partition

```bash
# Deploy a new service
ssh root@<HOST> 'mkdir -p /mnt/data/my-integration'
scp docker-compose.yml root@<HOST>:/mnt/data/my-integration/
ssh root@<HOST> 'docker compose -f /mnt/data/my-integration/docker-compose.yml up -d'

# Check logs
ssh root@<HOST> 'docker compose -f /mnt/data/my-integration/docker-compose.yml logs -f'
```

For the container to publish to the **local MQTT broker**, use `network_mode: host` in docker-compose — this is the simplest approach on WB and avoids any bridge networking issues. With host networking, `localhost:1883` inside the container reaches the host's mosquitto directly.

```yaml
services:
  my-integration:
    image: my-integration:latest
    network_mode: host
    restart: unless-stopped
```

## wbdev — build environment (for deb packages)

Docker-based cross-compilation tool. All packaging commands run on the developer machine and produce a `.deb`.

```bash
wbdev chroot            # interactive cross-build shell
wbdev make              # invoke make inside the container
wbdev cdeb              # build and package a C++ project
wbdev gdeb              # build and package a Go project
wbdev ndeb              # build an architecture-independent package
```

Install the produced `.deb` on the controller:
```bash
scp package.deb root@<HOST>:/tmp/
ssh root@<HOST> 'apt install -y /tmp/package.deb'
```

`apt install ./file.deb` resolves dependencies automatically. Never run binaries from `/tmp` in production.

## Codestyle: C++

Canonical reference: <https://github.com/wirenboard/codestyle/blob/main/C%2B%2B.ru.md>

Base: [Google C++ Style Guide](https://google.github.io/styleguide/cppguide.html).

**Naming:**
- Classes: `TModbusClient` (T-prefix), base classes end with `Base`: `TModbusClientBase`, interfaces: `IException`
- Methods: `CamelCase` starting with a verb: `GetValue`, `SetEnabled`
- Class fields: start with capital letter
- Local variables: `camelCase` or `snake_case` (never mix in one file)
- Abbreviations keep only first capital: `TMqttClient`
- Macros: avoid; use C++ constructs instead

**Formatting:** use `.clang-format` from <https://github.com/wirenboard/codestyle>. Apply before every commit.

```bash
# Check formatting
find src -name '*.cpp' -o -name '*.h' | xargs clang-format --dry-run --Werror -style=file

# Apply formatting
find src -name '*.cpp' -o -name '*.h' | xargs clang-format -i -style=file
```

## Codestyle: Python

Canonical reference: <https://github.com/wirenboard/codestyle/blob/main/python.ru.md>

Base: PEP8. Key differences:
- Max line length: **110** characters (not 78)
- **Double quotes** for strings: `"string"` (not `'string'`)
- Type annotations required
- Trailing comma after last element in multi-line collections

**Tools — run before every commit:**

```bash
# Install
pip install black isort pylint

# Check (dry-run)
python3 -m black --config pyproject.toml --check --diff $(../codestyle/python/ci/find-python-files)
python3 -m isort --settings-file pyproject.toml --check --diff $(../codestyle/python/ci/find-python-files)
python3 -m pylint $(../codestyle/python/ci/find-python-files)

# Autoformat
python3 -m black --config pyproject.toml $(../codestyle/python/ci/find-python-files)
python3 -m isort --settings-file pyproject.toml $(../codestyle/python/ci/find-python-files)
```

`pyproject.toml` and `find-python-files` are taken from the [codestyle repo](https://github.com/wirenboard/codestyle).

## Codestyle: Go

Canonical reference: <https://github.com/wirenboard/codestyle/blob/main/go.en.md>

```bash
go fmt ./...

# Static analysis
go mod vendor
staticcheck -go 1.13 ./...
```

## MQTT conventions

Full spec: <https://github.com/wirenboard/conventions/blob/main/README.md>

### Topic structure

```
/devices/<device-id>/meta                    — device metadata (JSON, retained)
/devices/<device-id>/meta/error              — device error state / LWT (non-null = error)
/devices/<device-id>/controls/<ctrl-id>      — current control value (retained)
/devices/<device-id>/controls/<ctrl-id>/on   — write target here to set the value
/devices/<device-id>/controls/<ctrl-id>/meta — control metadata (JSON, retained)
```

### Naming (2024+ rules)

- Lowercase, words separated by underscores, no punctuation/special chars
- Device topic: max 4 words + numbers
- Good: `/devices/room_light/meta`
- Bad: `/devices/Room-Light#1/meta`

### Device `/meta` JSON

```json
{
  "driver": "my-driver",
  "title": { "en": "Room Light", "ru": "Освещение комнаты" }
}
```

### Control `/meta` JSON

```jsonc
{
  "type": "switch",           // required — see types below
  "units": "W",              // for type=value only
  "min": 0, "max": 100,
  "precision": 0.1,
  "order": 1,
  "readonly": false,
  "hidden": false,
  "title": { "en": "Lamp", "ru": "Лампа" }
}
```

### Control types

| Type | `meta/type` | Values |
|---|---|---|
| Switch (toggle) | `switch` | `0` / `1` |
| Alarm indicator | `alarm` | `0` / `1` |
| Push button (stateless) | `pushbutton` | `1` (no retained) |
| Range slider | `range` | integer in [min, max] |
| Generic float value | `value` | float, use `units` field |
| Text | `text` | any string |
| RGB color | `rgb` | `"R;G;B"` (0–255 each) |
| Unix timestamp | `unixtime` | integer |

Specific typed controls (`temperature`, `voltage`, etc.) are **deprecated** — use `type: value` + `units` instead.

### Publishing rules

- All `/meta` topics: published with **retained** flag on driver startup
- `/devices/<id>/meta/error` used as **LWT** (Last Will and Testament) — set to non-empty value on connect
- Each device must be published by a **single driver**; no two drivers share the same device ID

### Subscribing

```bash
# Monitor all controls live
mosquitto_sub -t '/devices/+/controls/+' -v

# Write to a control
mosquitto_pub -t '/devices/room_light/controls/lamp/on' -m '1'
```

## MQTT-RPC

Full spec: <https://github.com/wirenboard/mqtt-rpc>

### Topic pattern

```
/rpc/v1/<driver>/<service>/<method>/<client_id>        — send request here
/rpc/v1/<driver>/<service>/<method>/<client_id>/reply  — receive response here
```

`client_id`: unique per request — use UUID v4 or MQTT client ID.

### Request format

```json
{ "id": "1234", "params": { "A": 1, "B": 2 } }
```

`id`: decimal string representation of uint64.

### Success response

```json
{ "id": "1234", "result": 42, "error": null }
```

### Error response

```json
{ "id": "1234", "error": { "message": "divide by zero", "code": -1, "data": "ErrorType" } }
```

**Rules:** strict JSON — no comments, no `Inf`/`NaN` values, all keys in quotes.

### Discover RPC services on a controller

```bash
ssh root@<HOST> "mosquitto_sub -t '/rpc/v1/+/+/+' -v"
```

### Python reference implementation

<https://github.com/wirenboard/python-mqtt-rpc>

## JSON editor (confed) — configuration UI for services

The WB web UI has a **pre-installed JSON editor** (`wb-mqtt-confed` + `homeui`). Any service can get a configuration page in the web interface for free by dropping a JSON Schema file into `/etc/wb-mqtt-confed/schemas/`.

Wiki: <https://wiki.wirenboard.com/wiki/JSON-editor-Wirenboard-Implementation-Features>

### How it works

`wb-mqtt-confed` watches the schemas directory. When the user opens the web UI → "Device configurations", it renders each schema as a form. On save, it writes the config file and restarts the service.

**If the config file is plain JSON** — no conversion scripts needed, confed reads/writes it directly.  
**If the config is a custom format** — provide `toJSON`/`fromJSON` converter scripts.

### Schema file structure

Place the file at `/etc/wb-mqtt-confed/schemas/my-service.schema.json`:

```jsonc
{
  "$schema": "http://json-schema.org/draft-04/schema#",
  "type": "object",
  "title": "My Service Configuration",
  "configFile": {
    "path": "/etc/my-service/config.json",
    "service": "my-service",
    "restartDelayMS": 2000
  },
  "properties": {
    "server_url": {
      "type": "string",
      "title": "Server URL",
      "propertyOrder": 1
    },
    "poll_interval": {
      "type": "integer",
      "title": "Poll interval (s)",
      "default": 30,
      "propertyOrder": 2
    },
    "enabled": {
      "type": "boolean",
      "title": "Enable service",
      "default": true,
      "_format": "checkbox",
      "propertyOrder": 3
    }
  }
}
```

### `configFile` parameters

| Parameter | Required | Description |
|---|---|---|
| `path` | yes | Path to the config file on the controller |
| `service` | no | Service name (or list) to restart after save |
| `toJSON` | no | Command: config file → JSON for homeui (stdin → stdout) |
| `fromJSON` | no | Command: JSON from homeui → config file (stdin → stdout) |
| `restartDelayMS` | no | Delay before service restart in ms |
| `validate` | no | Validate JSON against schema before writing (default: true) |
| `hide` | no | Hide from "Device configurations" page (for internal schemas) |
| `needReload` | no | Reload config from confed after save |

### WB-specific schema extensions

| Extension | Effect |
|---|---|
| `"_format": "checkbox"` | Boolean rendered as checkbox |
| `"_format": "wb-autocomplete"` | Text field with MQTT device autocomplete |
| `"_format": "edWb"` | Dropdown for integer/string via `enum_values` |
| `"headerTemplate"` on array items | Item label in collapsed array row |
| `"propertyOrder"` | Controls field ordering in the form |

### Installing the schema via deb

In your package's `debian/install` (or `debian/<pkg>.install`):
```
debian/my-service.schema.json  etc/wb-mqtt-confed/schemas/
```

After placing the schema file, restart confed to pick it up:
```bash
ssh root@<HOST> 'systemctl restart wb-mqtt-confed'
```

## ATECCx08 hardware security chip

Wiki: <https://wiki.wirenboard.com/wiki/CryptodevATECCx08_Auth>

The ATECCx08 chip stores the controller's private key in hardware — the key never leaves the chip.

**Use cases:**
- mTLS auth to nginx (client certificates)
- OpenVPN with hardware-backed credentials
- Mosquitto broker connections with device cert

**Workflow:**
1. Admin creates a CA on a secure machine (self-signed)
2. Controller generates a CSR via the ATECCx08 engine (private key stays in chip)
3. Admin signs the CSR → device certificate
4. Device presents the certificate; crypto ops run inside the chip

When developing services that must verify the controller's identity, use the chip-signed certificate as the client cert. Do not try to extract or copy private keys — that is intentionally impossible.

## Useful references

| Topic | URL |
|---|---|
| Codestyle repo | <https://github.com/wirenboard/codestyle> |
| MQTT conventions | <https://github.com/wirenboard/conventions/blob/main/README.md> |
| MQTT-RPC spec | <https://github.com/wirenboard/mqtt-rpc> |
| Python MQTT-RPC | <https://github.com/wirenboard/python-mqtt-rpc> |
| Dev guide (wiki) | <https://wiki.wirenboard.com/wiki/%D0%9A%D0%B0%D0%BA_%D1%80%D0%B0%D0%B7%D1%80%D0%B0%D0%B1%D0%B0%D1%82%D1%8B%D0%B2%D0%B0%D1%82%D1%8C_%D0%9F%D0%9E_%D0%B4%D0%BB%D1%8F_Wiren_Board> |
| ATECCx08 auth | <https://wiki.wirenboard.com/wiki/CryptodevATECCx08_Auth> |
| MQTT wiki | <https://wiki.wirenboard.com/wiki/MQTT> |
