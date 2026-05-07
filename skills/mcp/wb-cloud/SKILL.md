---
name: wb-cloud
description: Wiren Board Cloud — облачный агент `wb-cloud-agent` через MCP. Активация, статус, отвязка, диагностика связи с облаком, свой backend.
allowed-tools: Bash Read Write WebFetch
---

# wb-cloud (MCP)

Облачный агент Wiren Board (`wb-cloud-agent`) через MCP-tool `wb_cloud_status` + ассоциированные.

Подгружай при: «привязать к облаку», «активировать в wirenboard.cloud», «не открывается через облако», «отвязать», «свой cloud backend», «статус облака», «удалённый доступ».

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Сводный статус (сервис, сертификат, MQTT-controls, providers) | `wb_cloud_status` |
| Активность сервиса | `wb_systemd_unit unit=wb-cloud-agent` |
| Запустить / остановить / перезапустить | `wb_systemd_unit unit=wb-cloud-agent action=start|stop|restart` |
| Включить автозагрузку | `wb_systemd_unit unit=wb-cloud-agent action=enable` |
| Логи агента | `wb_logs unit=wb-cloud-agent` (с `since`/`grep` если нужно) |
| Изменить URL облака (CLOUD_BASE_URL) | `wb_write_file path=/etc/wb-cloud-agent.conf` |
| Получить activation_link (готовая ссылка для пользователя) | `wb_mqtt_read topic=/devices/system__wb-cloud-agent__<provider>/controls/activation_link` |
| Сбросить привязку | `wb_systemd_unit stop` + `wb_ssh_exec rm -rf /var/lib/wb-cloud-agent/providers/<provider>/` + `wb_systemd_unit start` |

## Сценарий: активировать (привязать к аккаунту)

1. **Сводный статус**:
   ```
   wb_cloud_status sn=<SN>
   ```
   Проверь: `serviceActive`, `certPresent`, `providers`, `mqtt.<provider>.status`, `mqtt.<provider>.activation_link`.

2. **Если сервис неактивен** — включи и стартуй:
   ```
   wb_systemd_unit sn=<SN> unit=wb-cloud-agent action=enable
   wb_systemd_unit sn=<SN> unit=wb-cloud-agent action=start
   ```

3. **Возьми activation_link** (после старта подожди 5-15 сек):
   ```
   wb_mqtt_read sn=<SN> topic=/devices/system__wb-cloud-agent__wirenboard.cloud/controls/activation_link
   ```
   Покажи URL пользователю — он откроет в браузере и привяжет.

4. **Проверь через 30 сек**:
   ```
   wb_cloud_status sn=<SN>
   ```
   `mqtt.wirenboard.cloud.status` должен стать `ok` (или `active`).

## Сценарий: отвязать / сбросить активацию

```
wb_systemd_unit sn=<SN> unit=wb-cloud-agent action=stop
wb_ssh_exec sn=<SN> cmd='rm -rf /var/lib/wb-cloud-agent/providers/wirenboard.cloud/'
wb_systemd_unit sn=<SN> unit=wb-cloud-agent action=start
```

После этого `wb_cloud_status` через минуту даст новый `activation_link`. Старую привязку в личном кабинете wirenboard.cloud удали вручную.

## Сценарий: свой backend

```
wb_write_file sn=<SN> path=/etc/wb-cloud-agent.conf content='{
    "LOG_LEVEL": "INFO",
    "CLIENT_CERT_ENGINE_KEY": "ATECCx08:00:02:C0:00",
    "CLOUD_BASE_URL": "https://my.cloud.example/"
}'
wb_systemd_unit sn=<SN> unit=wb-cloud-agent action=restart
```

Это редкий случай — для self-hosted облака (своя API, совместимая с wirenboard.cloud).

## Сценарий: «не подключается к облаку»

1. `wb_cloud_status sn=<SN>` — `serviceActive`, `certPresent`, `mqtt.*.status`.
2. Если `serviceActive: false` — `wb_systemd_unit unit=wb-cloud-agent action=start`.
3. Если `certPresent: false` — контроллер не WB или ATECC сломан, эскалация в support.
4. `wb_logs unit=wb-cloud-agent lines=50`. Типовые ошибки:
   - `connection refused`/`timeout` → проверь интернет: `wb_network_status pingTarget=wirenboard.cloud` или `wb_ssh_exec curl -s -m5 https://wirenboard.cloud`.
   - `Certificate verification failed` → дата на контроллере, NTP. `wb_ssh_exec date; systemctl is-active ntp`.
   - `Authentication failed` → сертификат отозван или устройство удалено из БД облака. Cleanup providers/ + рестарт.

## Связанные скиллы

- `/network` — если облако недоступно из-за интернета.
- `/services` — `wb-cloud-agent` это systemd-юнит.
- `/controller-backup` — `/etc/wb-cloud-agent.conf` уже в core-tar.

## Грабли

- **Время врёт** — TLS handshake к облаку упадёт. NTP должен работать.
- **VPN с default route** — может ломать доступ к облаку. `wb_ssh_exec` `ip route get wirenboard.cloud-IP`.
- **`CLIENT_CERT_ENGINE_KEY`** руками не меняй — адрес сертификата в ATECC, прошит на заводе.
- **Удалил из Web UI облака без локального сброса** — agent продолжит ломиться с `Authentication failed`. Делай cleanup providers/ + рестарт.
- **Activation-ссылка одноразовая** — если не довёл до конца, agent сгенерит новую при рестарте.

Подробности (свой backend, провайдеры) — bash-двойник `/wb-cloud`.

## Документация

- WB Cloud: <https://wirenboard.com/wiki/Wiren_Board_Cloud>
- Удалённый доступ: <https://wirenboard.com/wiki/Remote_access>
