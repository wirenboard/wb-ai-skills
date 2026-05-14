---
name: wb-dev
description: "Writing software FOR Wiren Board controllers — custom daemons (C++/Python/Go), MQTT bridges (Zigbee2MQTT → WB, Modbus → WB, custom hardware), MQTT-RPC services, wbdev cross-compilation, Debian packaging, /devices/X/controls/Y topic conventions. Use when user wants to write a daemon, integration bridge, or hardware adapter. NOT for wb-rules JS automation."
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

## Codestyle

Canonical configs (clang-format, pyproject.toml, find-python-files) live in <https://github.com/wirenboard/codestyle>. Apply formatters before every commit; CI checks them.

- **C++** — Google base + WB extensions (T-prefix classes, `Base`/`I` suffixes, `CamelCase` methods, `.clang-format`).
- **Python** — PEP8 with WB diffs: line length 110, double quotes, type annotations, trailing comma; black + isort + pylint.
- **Go** — `go fmt`, `staticcheck`.

For naming rules, exact CLI invocations and config paths — see **`references/codestyle.md`**.

## MQTT conventions and MQTT-RPC

Every integration on WB must expose state through the `/devices/<id>/controls/<id>` topic space; the web UI, wb-rules, and other services consume that namespace. All `/meta` topics are retained; `/meta/error` doubles as the LWT. Specific typed controls (`temperature`, `voltage`) are deprecated — use `type: value` + `units`.

MQTT-RPC uses paired topics `/rpc/v1/<driver>/<service>/<method>/<client_id>{,/reply}` with strict JSON requests (`{id, params}`) and responses (`{id, result, error}`).

For the full topic structure, naming rules, meta JSON shapes, control types table, publishing rules, MQTT-RPC details, and the Python reference implementation — see **`references/mqtt-conventions.md`**.

## JSON editor (confed) — configuration UI for services

Drop a JSON Schema at `/etc/wb-mqtt-confed/schemas/<name>.schema.json` to get a "Device configurations" page in the web UI for free. `wb-mqtt-confed` renders the schema as a form, validates on save, writes the config file, and restarts the service. Plain-JSON configs need no converters; custom formats use `toJSON`/`fromJSON`.

For the schema skeleton, full `configFile` parameter table, WB-specific extensions (`_format: checkbox`, `wb-autocomplete`, etc.) and install instructions — see **`references/confed-schema.md`**.

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

## What the agent does NOT do

- **Write a service that talks to its own internal bus or API without exposing state to MQTT.** Integrations invisible to the `/devices/.../controls/...` namespace can't be used by the web UI or wb-rules.
- **Install Docker via `apt install docker-ce` directly.** Use `wb-docker-manager.sh` from the WB community repo — generic apt install breaks the `/mnt/data` storage path.
- **Store Docker images or volumes on the root partition.** Limited space; use `/mnt/data/<project>/`.
- **Add file-level lint disables** (`# pylint: disable=` at top of file, `# type: ignore` on a module) to ship — surface the issue instead.
- **Try to extract the ATECCx08 private key.** It's hardware-bound by design; build flows around CSRs/signing on the chip.
- **Cross-compile by sshing in and running `make` on the controller.** Use `wbdev` on the developer machine — controller RAM is too limited for serious builds.

## When to ask the user

- Borderline Docker-vs-deb decision (small daemon but with a heavy runtime dep) — surface trade-offs.
- A new service needs to reserve a top-level MQTT prefix that overlaps with an existing driver — confirm naming.
- The service will run as root — confirm there's no less-privileged option that satisfies the requirements.
- About to commit large generated files (vendored deps, lockfiles >1 MB) — confirm.
- Confed schema would significantly change an existing service's config layout — confirm migration plan.

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
