---
name: software-install
description: Installing third-party software on a WB controller. Default — Docker; native — only Zigbee2MQTT (adapter binding) and rare exceptions.
allowed-tools: Bash Read Write WebFetch
---

# software-install

Installing third-party software on a Wiren Board controller.

## Installation policy

**By default we install everything in Docker.** Reasons:
- rootfs has only ~1.2 GB free (out of 2 GB physical) — native `apt`/`npm` installs fill it quickly.
- A container is isolated, updates and rollbacks — via `docker compose pull` / `down` / `up`.
- The compose file is versioned, easy to migrate between controllers.
- The backup (see `/controller-backup`) picks up compose files and named volumes itself.

**Exceptions** — native install is justified:

| Software | Why native | Channel |
|----|----------------|-------|
| **Zigbee2MQTT** | Hard binding to the Zigbee adapter via `/dev/ttyMOD<N>` + `wb-mqtt-zigbee` integrates devices into WB-MQTT | apt from WB repo |
| Device drivers / hardware-dependent (anything touching `/dev/*`) | A container eats the kernel abstractions and hot-plug | apt |

Everything else — Node-RED, Home Assistant, Grafana, InfluxDB, Mosquitto broker (if separate), Telegraf, Dockge, MQTT-explorer, knxd-Web, etc. — **in Docker**, via a compose stack at `/mnt/data/<project-name>/docker-compose.yml`. The wiki sometimes suggests native paths for Node-RED/HA — ignore and put it in a container unless there's a specific reason otherwise.

## Before installing

1. **Documentation:** `WebFetch https://wiki.wirenboard.com/wiki/<topic>` — check for WB-specifics (e.g. Z2M requires `wb-mqtt-zigbee`). For software without WB integration, the wiki page typically describes the native path — ignore it in favor of the official Docker image.
2. **Disk space:** `ssh root@<HOST> 'df -h / /mnt/data'`. Rootfs is physically 2 GB, after flash ~700 MB used (effective ~1.2 GB free). `/mnt/data` is usually tens of GBs. Container images and volumes live in `/mnt/data/.docker/` — they do **not** eat rootfs.
3. **Already installed?**
   - Container: `docker ps -a | grep <name>`.
   - apt package: `dpkg -l | grep <pkg>; systemctl is-active <unit>`.
   - npm global: `which <bin>; ls /usr/lib/node_modules/<pkg>`.

## Docker — mandatory base

**DO NOT install via plain `apt install docker-ce`** — no iptables-legacy setup, the daemon won't pick up overlay networks. Use `wb-docker-manager.sh` from the community repo.

**Install from a clean state:**
```bash
ssh root@<HOST> 'systemd-run --unit=wb-ai-docker-install --collect bash -c "wget -O /tmp/wb-docker-manager.sh https://raw.githubusercontent.com/wirenboard/wb-community/refs/heads/main/scripts/docker-install/wb-docker-manager.sh && bash /tmp/wb-docker-manager.sh --install"'
```

The script installs `docker-ce + containerd.io`, switches iptables to legacy, moves `data-root` to `/mnt/data/.docker`. **The script does NOT install `docker compose` (the plugin)** — add separately:

```bash
ssh root@<HOST> 'systemd-run --unit=wb-ai-compose-install --collect bash -c "DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-plugin"'
```

Verification after install:
```bash
ssh root@<HOST> 'docker --version && docker compose version && docker info --format "{{.DockerRootDir}}" && df -h /mnt/data'
```
`DockerRootDir` should be `/mnt/data/.docker` (not `/var/lib/docker`). `docker compose version` should return v2.x.

### If Docker doesn't start or installation was interrupted

1. **Kernel mismatch:** `ssh root@<HOST> 'echo "running: $(uname -r)"; dpkg -l "linux-image-wb*" | grep ^ii'` — if mismatch → reboot.

2. **`wb-docker-manager.sh` exits silently (`Docker already installed`), but daemon doesn't work** — common after an interrupted first attempt: cli package is unpacked, `command -v docker` finds it, the script thinks "all good". Cure:
   ```bash
   # first ensure dpkg integrity if there's anything half-installed:
   ssh root@<HOST> 'dpkg -l | grep -E "^iU|^iF|^pF|^iHR"'
   ssh root@<HOST> 'systemd-run --unit=wb-ai-dpkg-fix --collect bash -c "DEBIAN_FRONTEND=noninteractive dpkg --configure -a"'
   # then — reinstall docker-ce; configs and data-root that the script already created will survive:
   ssh root@<HOST> 'systemd-run --unit=wb-ai-docker-reinstall --collect bash -c "DEBIAN_FRONTEND=noninteractive apt-get install --reinstall -y docker-ce"'
   ```

3. **Manual iptables fix** (if it complains about `MASQUERADE` / `Chain ... does not exist`):
   ```bash
   ssh root@<HOST> 'update-alternatives --set iptables /usr/sbin/iptables-legacy && update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy && iptables -w10 -t nat -I POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE && systemctl restart docker'
   ```

## Typical compose project

Structure for any software in Docker:

```
/mnt/data/<project-name>/
├── docker-compose.yml
├── data/                  # bind-mount for configs and state
└── .env                   # secrets, tokens
```

Commands from `/mnt/data/<project-name>/`:
```bash
docker compose pull       # update images
docker compose up -d      # start
docker compose logs -f    # log
docker compose down       # stop (without deleting data)
```

`/controller-backup` picks up `docker-compose.yml`, `.env`, `data/` entirely; named volumes — separately via `docker run -v <vol>:/data alpine tar`.

### Node-RED (example)

`/mnt/data/nodered/docker-compose.yml`:
```yaml
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
      # resolve host services from a container in bridge network (Docker Engine on Linux):
      - "host.docker.internal:host-gateway"
```

Start:
```bash
ssh root@<HOST> 'mkdir -p /mnt/data/nodered/data && chown -R 1000:1000 /mnt/data/nodered/data && cd /mnt/data/nodered && docker compose up -d'
```

**`chown 1000:1000` is required:** the official `nodered/node-red` image runs as user `node-red` (uid 1000). Without chown, the bind-mount `./data` is owned by root, the container goes into a restart loop with `EACCES: permission denied, open '/data/.config.runtime.json'`.

UI: `http://wirenboard-<SN>.local:1880/`. **No authentication by default** — set up `adminAuth` in `data/settings.js` or close via nginx revproxy.

**Connection to the controller's MQTT broker** in Node-RED MQTT node:
- `host.docker.internal` — works only if compose has `extra_hosts: ["host.docker.internal:host-gateway"]` (see above). On Docker Engine under Linux **without** that line, the name does NOT resolve.
- Alternative: docker network gateway IP (default `172.17.0.1` for the default bridge) — always works, but tied to network configuration.

### Home Assistant, Grafana, InfluxDB, Telegraf, Dockge

Same compose stacks. Images:
- `homeassistant/home-assistant:stable` (requires `network_mode: host` for discovery)
- `grafana/grafana-oss:latest`
- `influxdb:2`
- `telegraf:latest`
- `louislam/dockge:latest` (UI on top of docker compose)

In each case — `/mnt/data/<name>/data:/<config-dir>`, port forwarded, `restart: unless-stopped`.

## Zigbee2MQTT (exception — native)

Wiki: <https://wiki.wirenboard.com/wiki/Zigbee2MQTT>. Installed from the WB repo together with `wb-mqtt-zigbee` (the latter integrates Z2M devices into `/devices/zigbee_*`).

1. **Verify the module** — a slot with a Zigbee adapter is required (see `/hardware-modules`). Without the module Z2M won't start.
2. **Install:**
   ```bash
   ssh root@<HOST> 'systemd-run --unit=wb-ai-z2m --collect bash -c "DEBIAN_FRONTEND=noninteractive apt-get update && apt-get -y --no-install-recommends install zigbee2mqtt && apt-get -y install wb-mqtt-zigbee"'
   ```
3. **Configure the port** in `/mnt/data/root/zigbee2mqtt/data/configuration.yaml`:
   ```bash
   ssh root@<HOST> "sed -i 's|port:.*|port: /dev/ttyMOD<N>|' /mnt/data/root/zigbee2mqtt/data/configuration.yaml"
   ```
4. **Start:**
   ```bash
   ssh root@<HOST> 'systemctl enable --now zigbee2mqtt && systemctl is-active zigbee2mqtt'
   ```
5. **Verify:**
   ```bash
   ssh root@<HOST> "mosquitto_sub -t 'zigbee2mqtt/bridge/state' -C 1 -W 5"
   ```
   Should be `online`.

## Native install as a fallback

If for some reason Docker isn't available (old firmware ≤ wb-2207, kernel mismatch, no space for the image) — go native. **Always** discuss with the user that Docker is preferred.

### Node-RED via apt+npm (old path)

Wiki: <https://wiki.wirenboard.com/wiki/Node-RED>. On wb-2602+ `nodejs` is in the WB repo (~22.x), `node-red` is installed via `npm install -g`.

1. Dependencies:
   ```bash
   ssh root@<HOST> 'systemd-run --unit=wb-ai-nodered-deps --collect bash -c "DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y nodejs git ca-certificates"'
   ```
2. User data on `/mnt/data`:
   ```bash
   ssh root@<HOST> 'mkdir -p /mnt/data/root/.node-red && ln -sfn /mnt/data/root/.node-red /root/.node-red'
   ```
3. Node-RED itself:
   ```bash
   ssh root@<HOST> 'systemd-run --unit=wb-ai-nodered-install --collect bash -c "npm install -g --unsafe-perm node-red"'
   ```
   ~280 packages, ~120 MB rootfs, 1-3 min.
4. systemd unit `/etc/systemd/system/nodered.service`:
   ```
   [Unit]
   Description=Node-RED
   After=network-online.target

   [Service]
   Type=simple
   User=root
   ExecStart=/usr/bin/node-red --userDir /mnt/data/root/.node-red
   Restart=on-failure

   [Install]
   WantedBy=multi-user.target
   ```
   ```bash
   ssh root@<HOST> 'systemctl daemon-reload && systemctl enable --now nodered'
   ```

Drawbacks vs Docker: eats ~310 MB rootfs, updates via `npm` by hand, migration to another controller is harder.

## General rules

- All long installs (`apt`, `npm install -g`, `docker pull/build`) — via `systemd-run --collect`. A synchronous ssh will time out.
- Data in `/mnt/data/<project>/`, not in rootfs.
- After start: `systemctl is-active <unit>` (for native) or `docker ps` (for containers) + `journalctl -u <unit> -n 20` or `docker logs --tail 30 <container>`.
- Web UI without authentication is open to everyone on the local network. Warn the user.

## Documentation

- Docker: <https://wiki.wirenboard.com/wiki/Docker>
- Zigbee2MQTT: <https://wiki.wirenboard.com/wiki/Zigbee2MQTT>
- Home Assistant: <https://wiki.wirenboard.com/wiki/Home_Assistant>
- Node-RED (native path): <https://wiki.wirenboard.com/wiki/Node-RED>
- Community scripts (`wb-docker-manager.sh` etc.): <https://github.com/wirenboard/wb-community>
