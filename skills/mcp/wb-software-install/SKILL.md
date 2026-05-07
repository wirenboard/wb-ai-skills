---
name: wb-software-install
description: Installing third-party software on a WB controller via MCP. Default path — Docker via wb-docker-manager.sh; native install only for Zigbee2MQTT (adapter binding) and rare exceptions. Covers Node-RED, Home Assistant, Grafana, InfluxDB, Telegraf, Dockge.
allowed-tools: Bash Read Write WebFetch
---

# software-install (MCP)

Installing third-party software on a Wiren Board controller via MCP tools.

## Installation policy

**By default install everything in Docker.** Reasons:
- rootfs has only ~1.2 GB free (out of physical 2 GB) — native `apt`/`npm` quickly fills it.
- The container is isolated, updates and rollback via `docker compose pull/down/up`.
- The compose file is versioned, migration between controllers is trivial.
- `wb_audit` and `/wb-controller-backup` pick up compose files and named volumes themselves.

**Exceptions** — native:

| Software | Why | Channel |
|----------|-----|---------|
| **Zigbee2MQTT** | Bound to the adapter via `/dev/ttyMOD<N>` + `wb-mqtt-zigbee` integrates devices into WB-MQTT | apt from WB repo |
| Drivers / hardware-dependent (touches `/dev/*`) | Container eats kernel abstractions and hot-plug | apt |

Everything else (Node-RED, HA, Grafana, InfluxDB, Telegraf, Dockge) — **in Docker**, via compose in `/mnt/data/<name>/docker-compose.yml`. The wiki sometimes suggests native paths for Node-RED/HA — ignore and containerize.

## Tool routing

| Intent | Tool |
|--------|------|
| Free space and memory | `wb_metrics` |
| Already installed? | `wb_ssh_exec` `docker ps -a \| grep <name>` or `dpkg -l \| grep <pkg>` or `which <bin>` |
| Internet access | `wb_ssh_exec` `curl -s -m5 https://deb.wirenboard.com >/dev/null && echo ok` |
| Install packages | `wb_ssh_exec_async` `apt install -y ...` |
| Download install scripts (`wb-docker-manager.sh`) | `wb_ssh_exec_async` `wget ...` |
| `docker run/pull/compose pull/up` | `wb_ssh_exec_async` |
| Long job progress | `wb_job_tail` |
| Write compose / .env / configuration.yaml | `wb_write_file` |
| Start unit / autostart | `wb_ssh_exec` `systemctl enable --now <unit>` |
| Native service logs | `wb_logs unit=<unit>` |
| Container logs | `wb_ssh_exec` `docker logs --tail 50 <container>` |
| Z2M bridge / other MQTT services state | `wb_mqtt_read` |
| Package drift after install | `wb_audit` |

## Before installation

1. **Documentation:** `WebFetch https://wiki.wirenboard.com/wiki/<topic>` — check WB specifics. Without it (as for Node-RED/HA) — install in Docker, bypassing the wiki's native path.
2. **Space:** `wb_metrics`. Container images live in `/mnt/data/.docker/` — they don't eat rootfs. Native software does.
3. **Already installed?** See routing table above.

## Docker — mandatory base

Don't run `wb_ssh_exec_async` `apt install docker-ce` directly. Use `wb-docker-manager.sh`:

```
wb_ssh_exec_async sn=<SN> cmd='wget -O /tmp/wb-docker-manager.sh https://raw.githubusercontent.com/wirenboard/wb-community/refs/heads/main/scripts/docker-install/wb-docker-manager.sh && bash /tmp/wb-docker-manager.sh --install'
```

The script installs `docker-ce + containerd.io`, switches iptables to legacy, moves data-root to `/mnt/data/.docker`. **`docker compose` (the plugin) is a separate package**, install it additionally:

```
wb_ssh_exec_async sn=<SN> cmd='DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-plugin'
```

Verification:
```
wb_ssh_exec sn=<SN> cmd='docker --version && docker compose version && docker info --format "{{.DockerRootDir}}" && df -h /mnt/data'
```

`DockerRootDir` should be `/mnt/data/.docker`. `docker compose version` returns v2.x.

### If Docker doesn't start or installation was interrupted

See `/wb-troubleshooting` (Docker and iptables section) — kernel mismatch and iptables-legacy.

**Special case:** after an interrupted first attempt, `wb-docker-manager.sh` may silently exit on retry ("Docker is already installed") because `command -v docker` finds the cli package, while the daemon isn't working. Cure:
```
wb_ssh_exec sn=<SN> cmd='dpkg -l | grep -E "^iU|^iF|^pF|^iHR"'
wb_ssh_exec_async sn=<SN> cmd='DEBIAN_FRONTEND=noninteractive dpkg --configure -a'
wb_ssh_exec_async sn=<SN> cmd='DEBIAN_FRONTEND=noninteractive apt-get install --reinstall -y docker-ce'
```

## Typical compose project

```
/mnt/data/<project-name>/
├── docker-compose.yml
├── data/
└── .env
```

Commands (`wb_ssh_exec_async` for all — pull/up/build are long):
- `cd /mnt/data/<name> && docker compose pull`
- `cd /mnt/data/<name> && docker compose up -d`
- `wb_ssh_exec` `docker ps; docker compose logs --tail 30`

### Node-RED in Docker (recommended path)

```yaml
# /mnt/data/nodered/docker-compose.yml
services:
  nodered:
    image: nodered/node-red:latest
    container_name: nodered
    restart: unless-stopped
    ports:
      - "1880:1880"
    volumes:
      - ./data:/data
    environment:
      - TZ=Europe/Moscow
    network_mode: bridge
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

Deployment:
```
wb_write_file sn=<SN> path=/mnt/data/nodered/docker-compose.yml content=<...>
wb_ssh_exec sn=<SN> cmd='mkdir -p /mnt/data/nodered/data && chown -R 1000:1000 /mnt/data/nodered/data'
wb_ssh_exec_async sn=<SN> cmd='cd /mnt/data/nodered && docker compose up -d'
```

**`chown 1000:1000` is mandatory** — the `nodered/node-red` image runs as uid 1000, without chown the bind-mount `./data` is owned by root → restart-loop with EACCES.

UI: `http://wirenboard-<SN>.local:1880/`. **No auth** — close it via `adminAuth` in `data/settings.js` or revprox.

**Connecting to the controller's MQTT broker** in Node-RED:
- `host.docker.internal` — resolves because the compose has `extra_hosts: ["host.docker.internal:host-gateway"]`. Without that line on Docker Engine under Linux the name does NOT work.
- Alternative: gateway IP of the docker network (usually `172.17.0.1` for the default bridge).

### Other in Docker

- `homeassistant/home-assistant:stable` (needs `network_mode: host` for discovery).
- `grafana/grafana-oss:latest`.
- `influxdb:2`.
- `telegraf:latest`.
- `louislam/dockge:latest` (UI for compose).

For each — `/mnt/data/<name>/data:/<config>`, port forwarding, `restart: unless-stopped`.

## Zigbee2MQTT (native — exception)

Wiki: <https://wiki.wirenboard.com/wiki/Zigbee2MQTT>. From WB repo together with `wb-mqtt-zigbee` (integrates devices into `/devices/zigbee_*`).

1. **Verify Zigbee module** — `wb_confed_load /etc/wb-hardware.conf`, find the slot with zigbee (see `/wb-hardware-modules`).
2. **Install:**
   ```
   wb_ssh_exec_async sn=<SN> cmd='DEBIAN_FRONTEND=noninteractive apt-get update && apt-get -y --no-install-recommends install zigbee2mqtt && apt-get -y install wb-mqtt-zigbee'
   ```
3. **Port.** Read the config, edit, write back:
   ```
   wb_read_file sn=<SN> path=/mnt/data/root/zigbee2mqtt/data/configuration.yaml
   # set port: /dev/ttyMOD<N>
   wb_write_file sn=<SN> path=/mnt/data/root/zigbee2mqtt/data/configuration.yaml content=<updated YAML>
   ```
4. **Start:**
   ```
   wb_ssh_exec sn=<SN> cmd='systemctl enable --now zigbee2mqtt && systemctl is-active zigbee2mqtt'
   ```
5. **Verify:** `wb_mqtt_read topic=zigbee2mqtt/bridge/state` (expect `online`).

## Native installation as fallback

If Docker is unavailable (old firmware ≤ wb-2207, kernel mismatch, no space for the image) — native. **Always** discuss with the user that Docker is preferable.

A full native Node-RED recipe (apt nodejs+git, symlink `~/.node-red → /mnt/data/`, `npm install -g node-red`, systemd unit) — see in the bash-flavor twin of this skill. Downsides: eats ~310 MB of rootfs, updates via `npm` by hand.

## General rules

- All long operations (`apt`, `npm install -g`, `docker pull/build`) — `wb_ssh_exec_async`.
- Data — in `/mnt/data/<project>/`, not in rootfs.
- After start: `wb_ssh_exec` `systemctl is-active <unit>` (for native) or `docker ps` (for containers) + logs via `wb_logs` or `docker logs`.
- `apt install` is blocked by a parallel `apt upgrade` — check active `wb_job_status` for all `job_id`s.
- `wb_metrics` after `docker pull` — mandatory (on wb6 4 GB eMMC `.docker/` quickly eats space).

## Documentation

- Docker: <https://wiki.wirenboard.com/wiki/Docker>
- Zigbee2MQTT: <https://wiki.wirenboard.com/wiki/Zigbee2MQTT>
- Home Assistant: <https://wiki.wirenboard.com/wiki/Home_Assistant>
- Node-RED (native path): <https://wiki.wirenboard.com/wiki/Node-RED>
- Community scripts: <https://github.com/wirenboard/wb-community>
