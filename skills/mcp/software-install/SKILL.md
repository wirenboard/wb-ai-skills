---
name: software-install
description: Установка стороннего ПО на контроллер WB через MCP. По умолчанию — Docker; нативно — только Zigbee2MQTT и редкие исключения.
allowed-tools: Bash Read Write WebFetch
---

# software-install (MCP)

Установка стороннего ПО на контроллер Wiren Board через MCP-tools.

## Политика установки

**По умолчанию ставим всё в Docker.** Причины:
- rootfs всего ~1.2 ГБ свободно (при физических 2 ГБ) — нативные `apt`/`npm` быстро забьют.
- Контейнер изолирован, обновления и откат через `docker compose pull/down/up`.
- compose-файл версионируется, миграция между контроллерами тривиальна.
- `wb_audit` и `/controller-backup` сами подбирают compose-файлы и named volumes.

**Исключения** — нативно:

| ПО | Почему | Канал |
|----|--------|-------|
| **Zigbee2MQTT** | Привязка к адаптеру через `/dev/ttyMOD<N>` + `wb-mqtt-zigbee` интегрирует устройства в WB-MQTT | apt из WB-репо |
| Драйверы / hardware-зависимое (трогает `/dev/*`) | Контейнер съедает kernel-абстракции и hot-plug | apt |

Прочее (Node-RED, HA, Grafana, InfluxDB, Telegraf, Dockge) — **в Docker**, через compose в `/mnt/data/<имя>/docker-compose.yml`. Wiki иногда предлагает нативные пути для Node-RED/HA — игнорируй и контейнеризируй.

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Свободное место и память | `wb_metrics` |
| Уже установлено? | `wb_ssh_exec` `docker ps -a \| grep <имя>` или `dpkg -l \| grep <pkg>` или `which <бин>` |
| Доступ к интернету | `wb_ssh_exec` `curl -s -m5 https://deb.wirenboard.com >/dev/null && echo ok` |
| Установка пакетов | `wb_ssh_exec_async` `apt install -y ...` |
| Скачивание скриптов установки (`wb-docker-manager.sh`) | `wb_ssh_exec_async` `wget ...` |
| `docker run/pull/compose pull/up` | `wb_ssh_exec_async` |
| Прогресс долгой задачи | `wb_job_tail` |
| Записать compose / .env / configuration.yaml | `wb_write_file` |
| Запустить unit / автостарт | `wb_ssh_exec` `systemctl enable --now <unit>` |
| Логи нативного сервиса | `wb_logs unit=<unit>` |
| Логи контейнера | `wb_ssh_exec` `docker logs --tail 50 <container>` |
| Состояние Z2M-моста / других MQTT-сервисов | `wb_mqtt_read` |
| Дрейф пакетов после установки | `wb_audit` |

## Перед установкой

1. **Документация:** `WebFetch https://wiki.wirenboard.com/wiki/<тема>` — проверь WB-специфику. Без неё (как у Node-RED/HA) — ставь в Docker, минуя нативный путь вики.
2. **Место:** `wb_metrics`. Контейнерные образы в `/mnt/data/.docker/` — не едят rootfs. Нативный софт — ест.
3. **Уже установлено?** См. таблицу маршрутизации выше.

## Docker — обязательная база

Не ставь `wb_ssh_exec_async` `apt install docker-ce` напрямую. Используй `wb-docker-manager.sh`:

```
wb_ssh_exec_async sn=<SN> cmd='wget -O /tmp/wb-docker-manager.sh https://raw.githubusercontent.com/wirenboard/wb-community/refs/heads/main/scripts/docker-install/wb-docker-manager.sh && bash /tmp/wb-docker-manager.sh --install'
```

Скрипт ставит `docker-ce + containerd.io`, переключает iptables на legacy, переносит data-root в `/mnt/data/.docker`. **`docker compose` (плагин) — отдельный пакет**, нужно поставить дополнительно:

```
wb_ssh_exec_async sn=<SN> cmd='DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-plugin'
```

Проверка:
```
wb_ssh_exec sn=<SN> cmd='docker --version && docker compose version && docker info --format "{{.DockerRootDir}}" && df -h /mnt/data'
```

`DockerRootDir` должен быть `/mnt/data/.docker`. `docker compose version` отдаёт v2.x.

### Если Docker не стартует или установка прерывалась

См. `/troubleshooting` (раздел Docker и iptables) — kernel mismatch и iptables-legacy.

**Особый случай:** после прерванной первой попытки `wb-docker-manager.sh` повторно может молча выйти ("Docker уже установлен"), потому что `command -v docker` находит cli-пакет, а демон при этом не работает. Лечение:
```
wb_ssh_exec sn=<SN> cmd='dpkg -l | grep -E "^iU|^iF|^pF|^iHR"'
wb_ssh_exec_async sn=<SN> cmd='DEBIAN_FRONTEND=noninteractive dpkg --configure -a'
wb_ssh_exec_async sn=<SN> cmd='DEBIAN_FRONTEND=noninteractive apt-get install --reinstall -y docker-ce'
```

## Типовой compose-проект

```
/mnt/data/<имя-проекта>/
├── docker-compose.yml
├── data/
└── .env
```

Команды (`wb_ssh_exec_async` для всех — pull/up/build долгие):
- `cd /mnt/data/<имя> && docker compose pull`
- `cd /mnt/data/<имя> && docker compose up -d`
- `wb_ssh_exec` `docker ps; docker compose logs --tail 30`

### Node-RED в Docker (рекомендуемый путь)

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

Развёртывание:
```
wb_write_file sn=<SN> path=/mnt/data/nodered/docker-compose.yml content=<...>
wb_ssh_exec sn=<SN> cmd='mkdir -p /mnt/data/nodered/data && chown -R 1000:1000 /mnt/data/nodered/data'
wb_ssh_exec_async sn=<SN> cmd='cd /mnt/data/nodered && docker compose up -d'
```

**`chown 1000:1000` обязателен** — образ `nodered/node-red` работает под uid 1000, без chown bind-mount `./data` принадлежит root → restart-loop с EACCES.

UI: `http://wirenboard-<SN>.local:1880/`. **Без auth** — закрой через `adminAuth` в `data/settings.js` или revprox.

**Связь с MQTT-брокером контроллера** в Node-RED:
- `host.docker.internal` — резолвится, потому что в compose есть `extra_hosts: ["host.docker.internal:host-gateway"]`. Без этой строки на Docker Engine под Linux имя НЕ работает.
- Альтернатива: IP gateway docker-сети (обычно `172.17.0.1` для дефолтного bridge).

### Прочее в Docker

- `homeassistant/home-assistant:stable` (нужен `network_mode: host` для discovery).
- `grafana/grafana-oss:latest`.
- `influxdb:2`.
- `telegraf:latest`.
- `louislam/dockge:latest` (UI для compose).

В каждом — `/mnt/data/<имя>/data:/<config>`, проброс портов, `restart: unless-stopped`.

## Zigbee2MQTT (нативно — исключение)

Wiki: <https://wiki.wirenboard.com/wiki/Zigbee2MQTT>. Из WB-репо вместе с `wb-mqtt-zigbee` (интегрирует устройства в `/devices/zigbee_*`).

1. **Проверь Zigbee-модуль** — `wb_confed_load /etc/wb-hardware.conf`, найди слот с zigbee (см. `/hardware-modules`).
2. **Установка:**
   ```
   wb_ssh_exec_async sn=<SN> cmd='DEBIAN_FRONTEND=noninteractive apt-get update && apt-get -y --no-install-recommends install zigbee2mqtt && apt-get -y install wb-mqtt-zigbee'
   ```
3. **Порт.** Прочитай конфиг, отредактируй и запиши:
   ```
   wb_read_file sn=<SN> path=/mnt/data/root/zigbee2mqtt/data/configuration.yaml
   # подставь port: /dev/ttyMOD<N>
   wb_write_file sn=<SN> path=/mnt/data/root/zigbee2mqtt/data/configuration.yaml content=<обновлённый YAML>
   ```
4. **Запуск:**
   ```
   wb_ssh_exec sn=<SN> cmd='systemctl enable --now zigbee2mqtt && systemctl is-active zigbee2mqtt'
   ```
5. **Проверь:** `wb_mqtt_read topic=zigbee2mqtt/bridge/state` (ожидание `online`).

## Нативная установка как fallback

Если Docker недоступен (старая прошивка ≤ wb-2207, kernel mismatch, нет места под образ) — нативно. **Всегда** обсуждай с пользователем, что Docker предпочтительнее.

Полный нативный рецепт Node-RED (apt nodejs+git, симлинк `~/.node-red → /mnt/data/`, `npm install -g node-red`, systemd-юнит) — см. в bash-двойнике скилла. Минусы: ест ~310 МБ rootfs, обновления через `npm` руками.

## Общие правила

- Все долгие операции (`apt`, `npm install -g`, `docker pull/build`) — `wb_ssh_exec_async`.
- Данные — в `/mnt/data/<проект>/`, не в rootfs.
- После запуска: `wb_ssh_exec` `systemctl is-active <unit>` (для нативных) или `docker ps` (для контейнеров) + логи через `wb_logs` или `docker logs`.
- `apt install` блокируется параллельным `apt upgrade` — проверь активные `wb_job_status` всех `job_id`.
- `wb_metrics` после `docker pull` — обязательно (на wb6 4 ГБ eMMC `.docker/` быстро ест место).

## Документация

- Docker: <https://wiki.wirenboard.com/wiki/Docker>
- Zigbee2MQTT: <https://wiki.wirenboard.com/wiki/Zigbee2MQTT>
- Home Assistant: <https://wiki.wirenboard.com/wiki/Home_Assistant>
- Node-RED (нативный путь): <https://wiki.wirenboard.com/wiki/Node-RED>
- Community-скрипты: <https://github.com/wirenboard/wb-community>
