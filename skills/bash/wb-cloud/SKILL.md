---
name: wb-cloud
description: Wiren Board Cloud — облачный агент `wb-cloud-agent` на контроллере. Активация, привязка к аккаунту, статус подключения, отвязка, диагностика связи с облаком. Свой облачный backend.
allowed-tools: Bash Read Write WebFetch
---

# wb-cloud

`wb-cloud-agent` — служба на контроллере, поддерживающая туннель к Wiren Board Cloud (`https://wirenboard.cloud`) для удалённого доступа к Web UI и API. Каждый контроллер имеет криптографический сертификат в защищённой памяти (`ATECCx08`), которым подписывается активация.

Подгружай при: «привязать контроллер к облаку», «активировать в wirenboard.cloud», «не открывается через облако», «отвязать от аккаунта», «свой cloud backend», «статус облака», «удалённый доступ через wirenboard.cloud».

## Архитектура

```
Web UI (wirenboard.cloud)
      ↑ (long-poll/websocket)
      │
      ▼
wb-cloud-agent  ──reads──▶  /etc/wb-cloud-agent.conf  (LOG_LEVEL, CLIENT_CERT_ENGINE_KEY, CLOUD_BASE_URL)
      │
      ├── /var/lib/wb-cloud-agent/device_bundle.crt.pem      (сертификат устройства)
      ├── /var/lib/wb-cloud-agent/providers/<provider>/       (per-provider state)
      │
      └── публикует в MQTT:
          /devices/system__wb-cloud-agent__<provider>/controls/status
                                                           /activation_link
                                                           /cloud_base_url
```

Provider — конкретное облако. По умолчанию `wirenboard.cloud`. Можно поднять свой — см. ниже.

## Базовые команды

```bash
# Активность сервиса
ssh root@<HOST> 'systemctl is-active wb-cloud-agent'

# Конфиг
ssh root@<HOST> 'cat /etc/wb-cloud-agent.conf'

# Сертификат устройства (наличие)
ssh root@<HOST> 'ls -la /var/lib/wb-cloud-agent/device_bundle.crt.pem'

# Провайдеры (список облаков)
ssh root@<HOST> 'ls /var/lib/wb-cloud-agent/providers/'

# MQTT-статус (для конкретного провайдера)
ssh root@<HOST> "mosquitto_sub -F '%t\\t%p' -t '/devices/system__wb-cloud-agent__+/controls/+' -W 3"
```

## Активация (привязка к аккаунту)

1. Убедись, что сервис запущен и есть интернет:
   ```bash
   ssh root@<HOST> 'systemctl is-active wb-cloud-agent && curl -s -m5 https://wirenboard.cloud >/dev/null && echo ok'
   ```

2. Если `inactive` — запусти:
   ```bash
   ssh root@<HOST> 'systemctl enable --now wb-cloud-agent'
   ```

3. Получи activation_link:
   ```bash
   ssh root@<HOST> "mosquitto_sub -t '/devices/system__wb-cloud-agent__wirenboard.cloud/controls/activation_link' -C 1 -W 5"
   ```

4. Открой ссылку в браузере, авторизуйся в `wirenboard.cloud`, привяжи к аккаунту.

5. После привязки `status` поменяется на `active`:
   ```bash
   ssh root@<HOST> "mosquitto_sub -t '/devices/system__wb-cloud-agent__wirenboard.cloud/controls/status' -C 1 -W 5"
   ```

   Возможные значения `status`:
   - `unknown` — агент только запустился, ещё не подключился.
   - `ok` (или `active`) — туннель установлен, контроллер виден из облака.
   - `not_activated` — сертификат есть, но устройство не привязано к аккаунту.
   - `error` — см. логи.

## Отвязка / сброс активации

```bash
ssh root@<HOST> 'systemctl stop wb-cloud-agent'
ssh root@<HOST> 'rm -rf /var/lib/wb-cloud-agent/providers/wirenboard.cloud/'
ssh root@<HOST> 'systemctl start wb-cloud-agent'
```

После этого agent выпустит новый activation_link. Старая привязка в личном кабинете wirenboard.cloud сохранится, но будет указывать в никуда — её нужно удалить вручную через Web UI облака.

## Свой облачный backend

CLOUD_BASE_URL в `/etc/wb-cloud-agent.conf` указывает на адрес облака. По умолчанию `https://wirenboard.cloud/`. Чтобы переключить:

```bash
ssh root@<HOST> 'cat > /etc/wb-cloud-agent.conf' <<'EOF'
{
    "LOG_LEVEL": "INFO",
    "CLIENT_CERT_ENGINE_KEY": "ATECCx08:00:02:C0:00",
    "CLOUD_BASE_URL": "https://my.cloud.example/"
}
EOF
ssh root@<HOST> 'systemctl restart wb-cloud-agent'
```

Свой backend должен реализовывать API совместимое с `wirenboard.cloud`. Это редкий случай — обычно для self-hosted развёртываний или тестовых стендов. Cертификат устройства ATECC всё равно подписан Wiren Board, но может быть верифицирован своим CA если доверяете root-сертификату WB.

## Диагностика «не подключается к облаку»

1. **Сервис активен?** `systemctl is-active wb-cloud-agent`. `inactive` → `enable --now`.
2. **Сертификат есть?** `ls /var/lib/wb-cloud-agent/device_bundle.crt.pem`. Нет — контроллер не Wiren Board или ATECC сломан.
3. **Интернет наружу?** `curl -s -m5 https://wirenboard.cloud >/dev/null && echo ok`. Нет — см. `/network` (failover, DNS).
4. **Логи**: `journalctl -u wb-cloud-agent -n 100 --no-pager`. Типовые ошибки:
   - `connection refused` / `timeout` — сетевая проблема.
   - `Certificate verification failed` — кривая дата на контроллере (`date`), синхронизуй NTP.
   - `Authentication failed` — сертификат отозван / устройство удалено из БД облака.
5. **MQTT публикуется?** `mosquitto_sub -t '/devices/system__wb-cloud-agent__wirenboard.cloud/controls/status' -C 1 -W 3`. Пусто — агент не доходит до публикации, проверь логи.

## Связь со скиллами

- `/network` — если облако недоступно из-за интернета.
- `/services` — `wb-cloud-agent` это systemd-юнит, override-conf и mask/unmask отсюда.
- `/controller-backup` — `/etc/wb-cloud-agent.conf` уже включён в core-tar; `/var/lib/wb-cloud-agent/providers/` обычно НЕ бэкапится (новая активация даёт новый providers state, и это нормально).
- `/troubleshooting` — общая диагностика, kernel mismatch, место.

## Грабли

- **Время сильно врёт** — TLS handshake к облаку упадёт. NTP должен работать (`systemctl is-active ntp` или `systemd-timesyncd`).
- **VPN на контроллере с маршрутом по умолчанию** — может ломать доступ к облаку, если VPN-сервер блокирует исходящий wirenboard.cloud. Проверь маршрут: `ip route get $(getent hosts wirenboard.cloud | awk "{print \$1}")`.
- **CLIENT_CERT_ENGINE_KEY** менять руками не нужно — это адрес сертификата в ATECC, прошит на заводе.
- **Удалить контроллер в Web UI облака без локального сброса** — local agent продолжит ломиться с `Authentication failed`. Сделай локально cleanup providers/ и перезапусти агент.
- **Активация-ссылка одноразовая** — если кликнул, но не довёл до конца, agent сгенерит новую при следующем запросе/рестарте.

## Документация

- WB Cloud: <https://wirenboard.com/wiki/Wiren_Board_Cloud>
- Удалённый доступ: <https://wirenboard.com/wiki/Remote_access>
