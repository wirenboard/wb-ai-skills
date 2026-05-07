---
name: mqtt-broker
description: Администрирование mosquitto на контроллере Wiren Board через MCP — listeners, пользователи, ACL, мосты к внешним брокерам, TLS.
allowed-tools: Bash Read Write WebFetch
---

# mqtt-broker (MCP)

`mosquitto` через MCP-tools. Управляется конфигами в `/etc/mosquitto/conf.d/*.conf` (НЕ редактируй главный `mosquitto.conf`).

Подгружай при: «открой MQTT наружу», «нужны пароли в MQTT», «настрой TLS», «бридж в облако», «бридж в HA», «не подключается к MQTT с ноута», «mosquitto», «ACL для MQTT».

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Статус брокера | `wb_systemd_unit unit=mosquitto` |
| Логи брокера | `wb_logs unit=mosquitto since="10m ago"` |
| Проверка конфига без рестарта | `wb_ssh_exec` `mosquitto -c /etc/mosquitto/mosquitto.conf -t` |
| Создать/обновить пароль | `wb_ssh_exec` `mosquitto_passwd [-c] /etc/mosquitto/passwd/default.conf <user>` |
| Записать listener-конфиг | `wb_write_file path=/etc/mosquitto/conf.d/10listeners.conf` |
| Записать ACL | `wb_write_file path=/etc/mosquitto/acl/default.conf` |
| Записать bridge | `wb_write_file path=/etc/mosquitto/conf.d/20bridges.conf` |
| Reload (passwd/acl без рестарта) | `wb_systemd_unit unit=mosquitto action=reload` |
| Restart (listener/bridge/TLS изменения) | `wb_systemd_unit unit=mosquitto action=restart` |
| $SYS-статистика | `wb_mqtt_list prefix='$SYS/broker/+' timeout=2` |

## Архитектура

```
/etc/mosquitto/mosquitto.conf            # включает 3 директории по порядку:
  /usr/share/wb-configs/mosquitto/        # WB-defaults — НЕ трогай
  /etc/mosquitto/conf.d/                  # пользовательское — твоё
  /usr/share/wb-configs/mosquitto-post/   # WB-post — НЕ трогай

/etc/mosquitto/conf.d/
├── 00default_listener.conf   # Unix-сокет для WB-сервисов (НЕ трогай)
├── 10listeners.conf          # порт 1883 / 8883 — сюда правки
└── 20bridges.conf            # мосты — сюда
```

WB-сервисы общаются через Unix-сокет (anonymous). Внешние клиенты — через 1883/8883, **там** делай auth.

## Сценарий: закрыть брокер паролем

1. Создать password-файл:
   ```
   wb_ssh_exec sn=<SN> cmd='mkdir -p /etc/mosquitto/passwd; chown mosquitto:mosquitto /etc/mosquitto/passwd'
   wb_ssh_exec sn=<SN> cmd='mosquitto_passwd -c /etc/mosquitto/passwd/default.conf <user>'
   wb_ssh_exec sn=<SN> cmd='chown mosquitto:mosquitto /etc/mosquitto/passwd/default.conf; chmod 0640 /etc/mosquitto/passwd/default.conf'
   ```
2. Listener конфиг с auth:
   ```
   wb_write_file sn=<SN> path=/etc/mosquitto/conf.d/10listeners.conf content='listener 1883
allow_anonymous false
acl_file /etc/mosquitto/acl/default.conf
password_file /etc/mosquitto/passwd/default.conf'
   ```
3. ACL (минимум — deny anonymous):
   ```
   wb_write_file sn=<SN> path=/etc/mosquitto/acl/default.conf content='topic deny #
user <user>
topic readwrite #'
   ```
4. Restart:
   ```
   wb_systemd_unit sn=<SN> unit=mosquitto action=restart
   ```
5. Тест:
   ```
   wb_ssh_exec sn=<SN> cmd="mosquitto_sub -h localhost -p 1883 -u <user> -P <pwd> -t '/devices/+/meta/name' -C 3 -W 3"
   ```

## Сценарий: bridge в Home Assistant

```
wb_write_file sn=<SN> path=/etc/mosquitto/conf.d/20bridges.conf content='connection ha-bridge
address ha.local:1883
topic /devices/# out 0 wb/<SN>/
topic ha/wb/cmd/+ in 0
remote_username <ha_user>
remote_password <ha_pwd>
keepalive_interval 60
notifications true
notifications_topic wb/<SN>/bridge/state
cleansession false'
wb_systemd_unit sn=<SN> unit=mosquitto action=restart
wb_mqtt_read sn=<SN> topic=wb/<SN>/bridge/state
```

`wb/<SN>/bridge/state` = `online` — мост поднялся.

## Сценарий: TLS на 8883

Self-signed CA + server cert (см. bash-двойник для openssl команд) → `wb_ssh_exec` создаёт `/etc/mosquitto/certs/{ca.crt, server.crt, server.key}`. Потом расширь listener:

```
listener 8883
allow_anonymous false
acl_file /etc/mosquitto/acl/default.conf
password_file /etc/mosquitto/passwd/default.conf
cafile /etc/mosquitto/certs/ca.crt
certfile /etc/mosquitto/certs/server.crt
keyfile /etc/mosquitto/certs/server.key
```

## Когда reload, когда restart

- **`reload`** — `password_file`, `acl_file` (новые юзеры/правила без даунтайма).
- **`restart`** — `listener`, `bridge`, TLS, изменения структуры конфигов. ≈1 сек даунтайма; внутренние WB-сервисы через Unix-сокет пережёют.

## Грабли

- **`per_listener_settings false`** — выключение позволит anonymous всем, включая 1883. WB ставит `true` в `00default_listener.conf` — не сбрасывай.
- **Правка `mosquitto.conf` напрямую** — всё в `conf.d/`. Базовый перезаписывается апдейтом.
- **Закрыл 1883, забыл про WB-сервисы** — они через Unix-сокет, не задеваются. Но если сломал `per_listener_settings`, то отвалятся.
- **mosquitto_passwd без `-c` для нового файла** — пароль не сохранится. С `-c` — затрёт существующих. Первый раз — `-c`, дальше без.
- **ACL без `topic deny #`** — anonymous (если разрешён) получает полный readwrite.
- **Bridge без `cleansession false`** — потеря сообщений при разрыве.
- **Right на password_file** — `mosquitto:mosquitto 0640`. Иначе `Unable to open password file ... Permission denied`.

## Связанные скиллы

- `/network` — если внешний клиент не подключается, проверь firewall.
- `/wb-cloud` — официальный мост wirenboard.cloud отдельным агентом, не через mosquitto bridge.
- `/services` — override-conf для mosquitto.

Подробности (TLS-сертификаты, ACL-синтаксис, формат bridge) — bash-двойник `/mqtt-broker`.

## Документация

- mosquitto.conf: <https://mosquitto.org/man/mosquitto-conf-5.html>
- mosquitto_passwd: <https://mosquitto.org/man/mosquitto_passwd-1.html>
- Bridges: <https://mosquitto.org/documentation/bridges/>
