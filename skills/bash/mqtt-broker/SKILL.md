---
name: mqtt-broker
description: Администрирование mosquitto на контроллере Wiren Board — listeners, пользователи, ACL, мосты к внешним брокерам, TLS. /etc/mosquitto/conf.d/.
allowed-tools: Bash Read Write WebFetch
---

# mqtt-broker

`mosquitto` на контроллере WB — основной MQTT-брокер, через который ходят все WB-сервисы и пользовательские приложения. Управление через `/etc/mosquitto/conf.d/*.conf` (НЕ редактируй `mosquitto.conf` напрямую).

Подгружай при: «открой MQTT наружу», «нужны пароли в MQTT», «настрой TLS», «бридж в облако», «бридж в HA», «не подключается к MQTT с ноута», «mosquitto», «ACL для MQTT», «пароли на брокер», «зашифровать MQTT».

## Структура конфигов

```
/etc/mosquitto/mosquitto.conf            # включает 3 директории по порядку:
  /usr/share/wb-configs/mosquitto/        # WB-defaults (НЕ трогай)
  /etc/mosquitto/conf.d/                  # пользовательское — сюда писать
  /usr/share/wb-configs/mosquitto-post/   # WB-post (НЕ трогай)

/etc/mosquitto/conf.d/
├── 00default_listener.conf   # Unix-сокет для wb-сервисов (НЕ трогай)
├── 10listeners.conf          # внешние listener'ы (порт 1883, 8883) — твоё
├── 20bridges.conf            # мосты к другим брокерам — твоё
└── 21bridge.conf.example     # шаблон моста

/etc/mosquitto/passwd/        # password files (mosquitto_passwd -c)
/etc/mosquitto/acl/           # ACL files (топики per-user)
/etc/mosquitto/certs/         # TLS-сертификаты (создашь)
```

**Принцип**: WB-сервисы общаются через Unix-сокет `/var/run/mosquitto/mosquitto.sock` (анонимно — 00default_listener). Внешние клиенты — через 1883/8883, и **там** делай аутентификацию.

По умолчанию (заводские настройки): listener 1883 anonymous = брокер открыт всему миру. **Для production это надо закрыть**.

## Базовые команды

```bash
ssh root@<HOST> 'systemctl is-active mosquitto'
ssh root@<HOST> 'mosquitto -c /etc/mosquitto/mosquitto.conf -t'      # проверка конфига без запуска
ssh root@<HOST> 'journalctl -u mosquitto -n 50 --no-pager'
ssh root@<HOST> "mosquitto_sub -h localhost -t '\$SYS/#' -C 5"        # системная статистика брокера
ssh root@<HOST> "mosquitto_sub -h localhost -t '\$SYS/broker/clients/connected' -C 1"
```

## Аутентификация: пароли

### Создать password-файл

```bash
ssh root@<HOST> 'mkdir -p /etc/mosquitto/passwd; chown mosquitto:mosquitto /etc/mosquitto/passwd'
ssh root@<HOST> 'mosquitto_passwd -c /etc/mosquitto/passwd/default.conf <username>'
# enter password: ****
ssh root@<HOST> 'chown mosquitto:mosquitto /etc/mosquitto/passwd/default.conf; chmod 0640 /etc/mosquitto/passwd/default.conf'
```

`-c` — создать файл (затрёт существующий!). Без `-c` — добавить юзера к существующему. Удалить юзера: `mosquitto_passwd -D /etc/mosquitto/passwd/default.conf <username>`.

### Настроить listener использовать пароли

В `/etc/mosquitto/conf.d/10listeners.conf` уже есть пример. Поправь чтобы запретить anonymous:

```bash
ssh root@<HOST> 'cat > /etc/mosquitto/conf.d/10listeners.conf' <<'EOF'
listener 1883
allow_anonymous false
acl_file /etc/mosquitto/acl/default.conf
password_file /etc/mosquitto/passwd/default.conf
EOF
ssh root@<HOST> 'systemctl restart mosquitto'
```

`per_listener_settings true` (в `00default_listener.conf`) — ключевой: позволяет разные `allow_anonymous` для разных listener'ов. Внутренний сокет остаётся anonymous, внешний — с паролем.

### Тест

```bash
ssh root@<HOST> "mosquitto_sub -h localhost -p 1883 -u <user> -P <pwd> -t '/devices/+/meta/name' -C 3 -W 3"
```

Без -u/-P должно отказать (`Connection error: Connection Refused: not authorised.`).

## ACL — права per-user

ACL-файл — права user'а на топики:

```bash
ssh root@<HOST> 'cat > /etc/mosquitto/acl/default.conf' <<'EOF'
# Default — anonymous deny
topic deny #

# user "admin" — полный доступ
user admin
topic readwrite #

# user "frontend" — только чтение /devices/, запись в /devices/+/controls/+/on
user frontend
topic read /devices/#
topic write /devices/+/controls/+/on

# user "external_app" — только своё пространство
user external_app
topic readwrite app/external_app/#
EOF
ssh root@<HOST> 'systemctl reload mosquitto'   # ACL подхватываются по reload (не requires restart)
```

Перед публикацией каждое сообщение проверяется по ACL. **Внутренние WB-сервисы через Unix-сокет ACL не задевает** — у них своя секция в `00default_listener.conf` (`allow_anonymous true`, без acl_file).

## TLS на порту 8883

### Сертификаты

Свой self-signed CA + сертификат сервера — для домашних задач. Для production лучше Let's Encrypt (через certbot/acme.sh) с публичным доменом.

```bash
# self-signed CA + server cert (один раз)
ssh root@<HOST> 'mkdir -p /etc/mosquitto/certs && cd /etc/mosquitto/certs && \
  openssl genrsa -out ca.key 2048 && \
  openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt -subj "/CN=WB-MQTT-CA" && \
  openssl genrsa -out server.key 2048 && \
  openssl req -new -key server.key -out server.csr -subj "/CN=wirenboard-<SN>.local" && \
  openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 3650 -sha256 && \
  chown mosquitto:mosquitto *.key *.crt && chmod 0640 *.key'
```

### Listener TLS

```bash
ssh root@<HOST> 'cat >> /etc/mosquitto/conf.d/10listeners.conf' <<'EOF'

listener 8883
allow_anonymous false
acl_file /etc/mosquitto/acl/default.conf
password_file /etc/mosquitto/passwd/default.conf
cafile /etc/mosquitto/certs/ca.crt
certfile /etc/mosquitto/certs/server.crt
keyfile /etc/mosquitto/certs/server.key
EOF
ssh root@<HOST> 'systemctl restart mosquitto'
```

### Тест TLS

```bash
ssh root@<HOST> "mosquitto_sub -h localhost -p 8883 --cafile /etc/mosquitto/certs/ca.crt -u <u> -P <p> -t test -C 1 -W 5"
```

С внешнего хоста — раздай `ca.crt` клиенту, подключайся к `wirenboard-<SN>.local:8883`. Self-signed без `--cafile` — `tls_version mismatch`/`certificate verify failed`.

Для Let's Encrypt — только `cafile` не нужен (системный CA), `certfile`/`keyfile` указывай на пути от certbot.

## Bridges — мосты к другим брокерам

Bridge — это режим, когда mosquitto сам подключается к другому брокеру и копирует выбранные топики туда-сюда. Типичные кейсы: репликация в Home Assistant, копия в облако, бэкап-брокер.

### Пример: bridge в Home Assistant

`/etc/mosquitto/conf.d/20bridges.conf`:

```bash
ssh root@<HOST> 'cat > /etc/mosquitto/conf.d/20bridges.conf' <<'EOF'
connection ha-bridge
address ha.local:1883
topic /devices/# out 0 wb/A25NDEMJ/
topic ha/wb/cmd/+ in 0
remote_username <ha_mqtt_user>
remote_password <ha_mqtt_password>
keepalive_interval 60
restart_timeout 10
notifications true
notifications_topic wb/A25NDEMJ/bridge/state
cleansession false
try_private false
EOF
ssh root@<HOST> 'systemctl restart mosquitto'
```

Topic-параметр: `<pattern> <direction> <qos> <local-prefix> <remote-prefix>`.
- `out` — публикуем туда (наружу), `in` — забираем сюда, `both` — оба направления.
- `wb/A25NDEMJ/` — префикс на удалённой стороне (там будут видны топики `wb/A25NDEMJ/devices/...`).

`notifications` создаёт `wb/A25NDEMJ/bridge/state` с `online`/`offline` — удобно для мониторинга связи.

`cleansession false` важно: при разрыве сообщения копятся с QoS≥1 и доставляются после восстановления.

### Bridge с TLS

Добавь в connection-блок:

```
bridge_cafile /etc/mosquitto/certs/ha-ca.crt
bridge_certfile /etc/mosquitto/certs/wb-client.crt
bridge_keyfile /etc/mosquitto/certs/wb-client.key
bridge_insecure false
```

`bridge_insecure true` отключает hostname verification — только для отладки.

## Изменения без рестарта

`systemctl reload mosquitto` — перечитывает только `password_file` и `acl_file`. Listener'ы, bridges, TLS — требуют `restart` (≈1 секунда даунтайма; WB-сервисы через Unix-сокет переживают).

## Проверка состояния и активных клиентов

```bash
ssh root@<HOST> "mosquitto_sub -h localhost -t '\$SYS/broker/+' -C 20 -W 2"
# /devices/+/meta/name плюс $SYS/broker/clients/connected, $SYS/broker/messages/received/1min и т.д.
```

`mosquitto_sub` без `-u` к закрытому листенеру → 1883 откажет, 1883 на Unix-сокете (mosquitto_sub автоматически выбирает hostname=localhost:1883 по умолчанию). Чтобы попасть в Unix-сокет: `mosquitto_sub -L mqtt://localhost:1883/<topic>` или подключайся `mosquitto_sub -h /var/run/mosquitto/mosquitto.sock` — в ряде версий не работает, проще через 1883.

## Бэкап и FIT

`/etc/mosquitto/conf.d/`, `/etc/mosquitto/passwd/`, `/etc/mosquitto/acl/`, `/etc/mosquitto/certs/` — все НЕ переживают FIT. Через `/controller-backup` они уже подбираются (часть `dpkg --verify` отметит изменения, и core-tar их захватит как изменённые конфиги).

## Грабли

- **`per_listener_settings false`** (default в Debian-пакете) — `allow_anonymous` применяется глобально, отдельный режим для Unix-сокета не получится. WB-конфиг включает `per_listener_settings true` — не сбрасывай.
- **Правка `/etc/mosquitto/mosquitto.conf` напрямую** — всё что нужно в `/etc/mosquitto/conf.d/`. Базовый файл может перезаписаться апдейтом.
- **Закрыл 1883 anonymous, забыл про wb-сервисы** — wb-сервисы используют Unix-сокет (`00default_listener.conf`, отдельный режим), их это не задевает. Но если переключил `per_listener_settings false` — WB-сервисы отвалятся.
- **mosquitto_passwd без `-c` для нового файла** — пароль не сохранится (нет файла). С `-c` — затрёт всех существующих юзеров. После первого юзера — без `-c`.
- **password_file без перезагрузки** — пароли изменяются по `systemctl reload mosquitto`. Полный restart не нужен.
- **ACL без явного deny `topic deny #`** — anonymous user (если allow_anonymous true) получает full readwrite по умолчанию.
- **Bridge без `cleansession false`** — потеряешь сообщения при разрыве.
- **Bridge с `try_private true`** mosquitto.conf-only feature — для брокеров != mosquitto оставь `false`.
- **TLS-сертификат истёк** — `journalctl -u mosquitto` покажет, и клиенты получат `tls handshake failure`. Renew через certbot или регенерируй self-signed.
- **Right на `/etc/mosquitto/passwd/default.conf`** — должен быть `mosquitto:mosquitto 0640`, иначе mosquitto не прочитает (видно в логах: `Unable to open password file ... Permission denied`).

## Документация

- mosquitto.conf: `man mosquitto.conf`, <https://mosquitto.org/man/mosquitto-conf-5.html>
- ACL: <https://mosquitto.org/documentation/dynamic-security/>
- mosquitto_passwd: <https://mosquitto.org/man/mosquitto_passwd-1.html>
- Bridges: <https://mosquitto.org/documentation/bridges/>
