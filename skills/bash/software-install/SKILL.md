---
name: software-install
description: Установка стороннего ПО на контроллер WB. По умолчанию — Docker; нативно — только Zigbee2MQTT (привязка к адаптеру) и редкие исключения.
allowed-tools: Bash Read Write WebFetch
---

# software-install

Установка стороннего ПО на контроллер Wiren Board.

## Политика установки

**По умолчанию ставим всё в Docker.** Причины:
- rootfs всего ~1.2 ГБ свободно (при физических 2 ГБ) — нативные `apt`/`npm`-установки быстро его забьют.
- Контейнер изолирован, обновления и откат — через `docker compose pull` / `down` / `up`.
- compose-файл версионируется, переезжает между контроллерами тривиально.
- Бэкап (см. `/controller-backup`) сам подбирает compose-файлы и named volumes.

**Исключения** — нативная установка оправдана:

| ПО | Почему нативно | Канал |
|----|----------------|-------|
| **Zigbee2MQTT** | Жёсткая привязка к Zigbee-адаптеру через `/dev/ttyMOD<N>` + `wb-mqtt-zigbee` интегрирует устройства в WB-MQTT | apt из WB-репо |
| Драйверы устройств / hardware-зависимое (всё, что трогает `/dev/*`) | Контейнер съедает абстракции kernel и hot-plug | apt |

Прочее — Node-RED, Home Assistant, Grafana, InfluxDB, Mosquitto-broker (если отдельный), Telegraf, Dockge, MQTT-explorer, knxd-Web и т.п. — **в Docker**, через compose-stack в `/mnt/data/<имя-проекта>/docker-compose.yml`. Wiki иногда предлагает нативные пути для Node-RED/HA — игнорируй и ставь в контейнер, если нет конкретной причины обратного.

## Перед установкой

1. **Документация:** `WebFetch https://wiki.wirenboard.com/wiki/<тема>` — проверь, нет ли WB-специфики (например, Z2M требует `wb-mqtt-zigbee`). Для софта без WB-интеграции страница вики обычно описывает нативный путь — игнорируй её в пользу официального Docker-образа.
2. **Место:** `ssh root@<HOST> 'df -h / /mnt/data'`. Rootfs физически 2 ГБ, после прошивки занято ~700 МБ (реально доступно ~1.2 ГБ). `/mnt/data` обычно несколько десятков ГБ. Контейнерные образы и тома живут в `/mnt/data/.docker/` — они **не** едят rootfs.
3. **Уже установлено?**
   - Контейнер: `docker ps -a | grep <имя>`.
   - apt-пакет: `dpkg -l | grep <пакет>; systemctl is-active <unit>`.
   - npm-глобалка: `which <бинарь>; ls /usr/lib/node_modules/<пакет>`.

## Docker — обязательная база

**НЕ ставь через `apt install docker-ce`** напрямую — нет настройки iptables-legacy, демон не подхватит overlay-сеть. Используй `wb-docker-manager.sh` из community-репо.

**Установка из чистого состояния:**
```bash
ssh root@<HOST> 'systemd-run --unit=wb-ai-docker-install --collect bash -c "wget -O /tmp/wb-docker-manager.sh https://raw.githubusercontent.com/wirenboard/wb-community/refs/heads/main/scripts/docker-install/wb-docker-manager.sh && bash /tmp/wb-docker-manager.sh --install"'
```

Скрипт ставит `docker-ce + containerd.io`, переключает iptables на legacy, переносит `data-root` в `/mnt/data/.docker`. **`docker compose` (плагин) скрипт НЕ ставит** — добавь отдельно:

```bash
ssh root@<HOST> 'systemd-run --unit=wb-ai-compose-install --collect bash -c "DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-plugin"'
```

Проверка после установки:
```bash
ssh root@<HOST> 'docker --version && docker compose version && docker info --format "{{.DockerRootDir}}" && df -h /mnt/data'
```
`DockerRootDir` должен быть `/mnt/data/.docker` (не `/var/lib/docker`). `docker compose version` должна отдать v2.x.

### Если Docker не стартует или установка прерывалась

1. **Kernel mismatch:** `ssh root@<HOST> 'echo "running: $(uname -r)"; dpkg -l "linux-image-wb*" | grep ^ii'` — если расходится → reboot.

2. **`wb-docker-manager.sh` молча выходит (`Docker уже установлен`), но демон не работает** — частый случай после прерванной первой попытки: cli-пакет распакован, `command -v docker` находит его, скрипт думает "всё ок". Лечение:
   ```bash
   # сначала добиться целостности dpkg, если есть half-installed:
   ssh root@<HOST> 'dpkg -l | grep -E "^iU|^iF|^pF|^iHR"'
   ssh root@<HOST> 'systemd-run --unit=wb-ai-dpkg-fix --collect bash -c "DEBIAN_FRONTEND=noninteractive dpkg --configure -a"'
   # потом — реинсталл docker-ce; конфиги и data-root, которые скрипт уже создал, переживут:
   ssh root@<HOST> 'systemd-run --unit=wb-ai-docker-reinstall --collect bash -c "DEBIAN_FRONTEND=noninteractive apt-get install --reinstall -y docker-ce"'
   ```

3. **iptables fix вручную** (если ругается на `MASQUERADE` / `Chain ... does not exist`):
   ```bash
   ssh root@<HOST> 'update-alternatives --set iptables /usr/sbin/iptables-legacy && update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy && iptables -w10 -t nat -I POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE && systemctl restart docker'
   ```

## Типовой compose-проект

Структура для любого софта в Docker:

```
/mnt/data/<имя-проекта>/
├── docker-compose.yml
├── data/                  # bind-mount для конфигов и состояния
└── .env                   # секреты, токены
```

Команды из `/mnt/data/<имя-проекта>/`:
```bash
docker compose pull       # обновить образы
docker compose up -d      # запуск
docker compose logs -f    # лог
docker compose down       # остановка (без удаления данных)
```

`/controller-backup` забирает `docker-compose.yml`, `.env`, `data/` целиком; named volumes — отдельно через `docker run -v <vol>:/data alpine tar`.

### Node-RED (пример)

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
      # резолв host-services из контейнера в bridge-сети (Docker Engine на Linux):
      - "host.docker.internal:host-gateway"
```

Запуск:
```bash
ssh root@<HOST> 'mkdir -p /mnt/data/nodered/data && chown -R 1000:1000 /mnt/data/nodered/data && cd /mnt/data/nodered && docker compose up -d'
```

**`chown 1000:1000` обязателен:** официальный образ `nodered/node-red` работает под пользователем `node-red` (uid 1000). Без chown bind-mount `./data` принадлежит root, контейнер падает в restart-loop с `EACCES: permission denied, open '/data/.config.runtime.json'`.

UI: `http://wirenboard-<SN>.local:1880/`. **Аутентификации нет по умолчанию** — настрой `adminAuth` в `data/settings.js` или закрой через nginx-revprox.

**Связь с MQTT-брокером контроллера** в Node-RED MQTT-ноде:
- `host.docker.internal` — сработает только если в compose есть `extra_hosts: ["host.docker.internal:host-gateway"]` (см. выше). На Docker Engine под Linux **без** этой строки имя НЕ резолвится.
- Альтернатива: IP gateway docker-сети (по умолчанию `172.17.0.1` для дефолтного bridge) — работает всегда, но завязка на сетевую конфигурацию.

### Home Assistant, Grafana, InfluxDB, Telegraf, Dockge

Те же compose-stacks. Образы:
- `homeassistant/home-assistant:stable` (требует `network_mode: host` для discovery)
- `grafana/grafana-oss:latest`
- `influxdb:2`
- `telegraf:latest`
- `louislam/dockge:latest` (UI поверх docker compose)

В каждом случае — `/mnt/data/<имя>/data:/<config-dir>`, порт пробрасывается, `restart: unless-stopped`.

## Zigbee2MQTT (исключение — нативно)

Wiki: <https://wiki.wirenboard.com/wiki/Zigbee2MQTT>. Ставится из WB-репо вместе с `wb-mqtt-zigbee` (последний интегрирует Z2M-устройства в `/devices/zigbee_*`).

1. **Проверь модуль** — нужен слот с Zigbee-адаптером (см. `/hardware-modules`). Без модуля Z2M не запустится.
2. **Установи:**
   ```bash
   ssh root@<HOST> 'systemd-run --unit=wb-ai-z2m --collect bash -c "DEBIAN_FRONTEND=noninteractive apt-get update && apt-get -y --no-install-recommends install zigbee2mqtt && apt-get -y install wb-mqtt-zigbee"'
   ```
3. **Настрой порт** в `/mnt/data/root/zigbee2mqtt/data/configuration.yaml`:
   ```bash
   ssh root@<HOST> "sed -i 's|port:.*|port: /dev/ttyMOD<N>|' /mnt/data/root/zigbee2mqtt/data/configuration.yaml"
   ```
4. **Запусти:**
   ```bash
   ssh root@<HOST> 'systemctl enable --now zigbee2mqtt && systemctl is-active zigbee2mqtt'
   ```
5. **Проверь:**
   ```bash
   ssh root@<HOST> "mosquitto_sub -t 'zigbee2mqtt/bridge/state' -C 1 -W 5"
   ```
   Должно быть `online`.

## Нативная установка как fallback

Если по какой-то причине Docker недоступен (старая прошивка ≤ wb-2207, kernel mismatch, нет места под образ) — нативно. **Всегда** обсуждай с пользователем, что Docker предпочтительнее.

### Node-RED через apt+npm (старый путь)

Wiki: <https://wiki.wirenboard.com/wiki/Node-RED>. На wb-2602+ `nodejs` есть в WB-репо (~22.x), `node-red` ставится через `npm install -g`.

1. Зависимости:
   ```bash
   ssh root@<HOST> 'systemd-run --unit=wb-ai-nodered-deps --collect bash -c "DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y nodejs git ca-certificates"'
   ```
2. Юзер-данные на `/mnt/data`:
   ```bash
   ssh root@<HOST> 'mkdir -p /mnt/data/root/.node-red && ln -sfn /mnt/data/root/.node-red /root/.node-red'
   ```
3. Сам Node-RED:
   ```bash
   ssh root@<HOST> 'systemd-run --unit=wb-ai-nodered-install --collect bash -c "npm install -g --unsafe-perm node-red"'
   ```
   ~280 пакетов, ~120 МБ rootfs, 1-3 мин.
4. Systemd-юнит `/etc/systemd/system/nodered.service`:
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

Минусы по сравнению с Docker: ест ~310 МБ rootfs, обновления через `npm` руками, миграция на другой контроллер сложнее.

## Общие правила

- Все долгие установки (`apt`, `npm install -g`, `docker pull/build`) — через `systemd-run --collect`. Синхронный ssh упадёт по таймауту.
- Данные — в `/mnt/data/<проект>/`, не в rootfs.
- После запуска: `systemctl is-active <unit>` (для нативных) или `docker ps` (для контейнеров) + `journalctl -u <unit> -n 20` или `docker logs --tail 30 <container>`.
- Web-UI без аутентификации — открыт всем в локальной сети. Предупреждай пользователя.

## Документация

- Docker: <https://wiki.wirenboard.com/wiki/Docker>
- Zigbee2MQTT: <https://wiki.wirenboard.com/wiki/Zigbee2MQTT>
- Home Assistant: <https://wiki.wirenboard.com/wiki/Home_Assistant>
- Node-RED (нативный путь): <https://wiki.wirenboard.com/wiki/Node-RED>
- Community-скрипты (`wb-docker-manager.sh` и др.): <https://github.com/wirenboard/wb-community>
