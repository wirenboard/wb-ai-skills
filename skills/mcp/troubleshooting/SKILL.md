---
name: troubleshooting
description: "Общая диагностика проблем на контроллере Wiren Board через MCP. Упавшие сервисы, нехватка места, kernel mismatch, Docker, iptables, диагностический архив. НЕ для serial/Modbus — для этого есть troubleshooting-serial."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# troubleshooting (MCP)

Общая диагностика проблем на контроллере Wiren Board через MCP-tools `wb_*`. Подгружай когда пользователь говорит: «не работает», «почини», «сломалось», «ошибка», «не запускается», «упал сервис», «проблема с...», «собери диагностику», «диагностический архив», «логи и состояние» — и это НЕ про serial/Modbus (для serial есть `/troubleshooting-serial`).

Не путай с бэкапом (`/controller-backup`). Диагностический архив — для анализа и поддержки, не для восстановления. Собирается утилитой `wb-diag-collect` и включает: конфиги из `/etc`, логи сервисов (wb*, mosquitto, NetworkManager и др.), вывод диагностических команд (df, ps, ip, dpkg и др.).

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Метрики (load, RAM, диск) | `wb_metrics` |
| Список упавших unit'ов | `wb_failed` |
| Логи конкретного сервиса (`journalctl -u`) | `wb_logs` |
| Аудит: пакеты, сервисы, кастомные файлы | `wb_audit` |
| Произвольная диагностическая команда (короткая) | `wb_ssh_exec` |
| Длинная (`wb-diag-collect`, `apt-get`) | `wb_ssh_exec_async` → `wb_job_tail` |
| Прочитать `/etc/resolv.conf`, `/etc/wb-mqtt-*` | `wb_read_file` |
| MQTT жив? | `wb_mqtt_list` (если возвращает топики — брокер живой) |

## Первые шаги — всегда

Прежде чем чинить — разберись в причине. Не чини симптомы.

### 0. Документация — ОБЯЗАТЕЛЬНО

**Перед любой починкой** делай `WebFetch` на страницу проблемного компонента в вики WB. Например: Docker — `WebFetch('https://wiki.wirenboard.com/wiki/Docker')`, Modbus — `WebFetch('https://wiki.wirenboard.com/wiki/Modbus')`, Home Assistant — `WebFetch('https://wiki.wirenboard.com/wiki/Home_Assistant')`. Ищи разделы «Известные проблемы», «Troubleshooting», «Ограничения». Если решение там есть — применяй его, не изобретай своё.

### 1. Kernel mismatch

**Самая частая причина проблем после обновления.** Проверь первым делом:

```
wb_ssh_exec sn=<SN> cmd='echo "running: $(uname -r)"; dpkg -l "linux-image-wb*" 2>/dev/null | grep ^ii | awk "{print \"installed:\", \$3}"'
```

Если версии не совпадают — контроллер работает на старом ядре. Модули ядра (br_netfilter, iptable_nat, can, i2c и др.) не загрузятся, Docker/iptables/сеть могут не работать. **Единственное решение — перезагрузка.** Не пытайся обойти через modprobe/iptables-legacy — это бесполезно при kernel mismatch.

`wb_audit` тоже отметит расхождение версий ядра.

### 2. Место на диске

`wb_metrics` отдаёт текущее свободное место по `/` и `/mnt/data`. Rootfs < 100 МБ — критично: apt не работает, логи не пишутся, сервисы падают. Чистка через `wb_ssh_exec_async` `cmd='apt clean; journalctl --vacuum-time=3d; rm -rf /tmp/*'`.

### 3. Упавшие сервисы

`wb_failed` — список failed-unit'ов. Для каждого нужны и status, и логи (status даёт exit code, Result, ExecMainStatus — короткий summary; журнал — подробности):

```
wb_ssh_exec sn=<SN> cmd='systemctl status <unit> --no-pager'
wb_logs sn=<SN> unit=<unit> lines=50
```

`systemctl status` для failed unit'а возвращает exit code 3 — это **нормально** (статус-код systemctl), не ошибка ssh. `wb_ssh_exec` отдаст `code: 3` в результате.

### 4. Журнал ошибок

```
wb_ssh_exec sn=<SN> cmd='journalctl -p err --since "1 hour ago" --no-pager'
```

Без `--since` журналы могут уйти на дни/недели назад. Период подбирай по контексту (`'10 minutes ago'`, `'today'`, `'1 hour ago'`). `wb_logs` сам по себе принимает `unit`/`lines`/`priority`, но окно времени надёжнее задавать через прямой `journalctl --since` через `wb_ssh_exec`.

### 5. Нагрузка и память

`wb_metrics` отдаёт load и память. Load > 4 на WB — перегрузка. Кто ест CPU:

```
wb_ssh_exec sn=<SN> cmd='top -bn1 | head -20'
```

## Типичные проблемы

| Симптом | Первый шаг |
|---------|-----------|
| Сервис не запускается после обновления | Kernel mismatch → перезагрузка |
| Docker не стартует, iptables ошибки | Сначала kernel mismatch. Если ядро ОК — iptables-legacy fix (см. ниже) |
| modprobe: module not found | Kernel mismatch → перезагрузка |
| apt не работает, dpkg lock | `wb_ssh_exec` `fuser /var/lib/dpkg/lock-frontend` — кто держит. Зомби от прерванного apt: `wb_ssh_exec_async` `dpkg --configure -a` |
| Сервис падает в цикле | `wb_logs unit=<unit> lines=100` — ищи причину, не перезапускай вслепую |
| `fstrim.service` failed, `status=64/USAGE` | Запись в `/etc/fstab` указывает на физически отсутствующий раздел (типично — `/mnt/sdcard` без SD). `fstrim --listed-in /etc/fstab` падает, не дойдя до остальных точек. Проверь `wb_ssh_exec` `mount; ls /dev/mmcblk1*`. Лечение: убрать строку из fstab или drop-in с `ExecStart=/sbin/fstrim --fstab --quiet-unsupported` |
| Нет сети | `wb_ssh_exec` `ip addr; nmcli; ping -c2 8.8.8.8`; `wb_read_file` `/etc/resolv.conf` |
| MQTT не работает | `wb_ssh_exec` `systemctl is-active mosquitto`; `wb_mqtt_list` |
| Web UI не открывается | `wb_ssh_exec` `systemctl is-active nginx wb-mqtt-homeui` |

## Docker и iptables

Если Docker не стартует с ошибками вроде `Chain 'MASQUERADE' does not exist`, `DOCKER-ISOLATION-STAGE`, `Failed to Setup IP tables` — и kernel mismatch исключён:

1. Переключи iptables на legacy (с подтверждением):

   ```
   wb_ssh_exec sn=<SN> cmd='update-alternatives --set iptables /usr/sbin/iptables-legacy && update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy'
   ```

2. Создай недостающее правило NAT:

   ```
   wb_ssh_exec sn=<SN> cmd='iptables -w10 -t nat -I POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE'
   ```

3. Перезапусти Docker:

   ```
   wb_ssh_exec sn=<SN> cmd='systemctl restart docker && systemctl is-active docker'
   ```

Если не помогло — перезагрузка (`wb_ssh_exec` `reboot`, ждёшь disconnect, потом `wb_probe`).

Подробнее: <https://wiki.wirenboard.com/wiki/Docker>.

## Диагностический архив

**Собирай ТОЛЬКО в двух случаях:**
1. Пользователь явно просит «пришли диагархив» / «диагностический архив».
2. Составляется багрепорт (`/bugreport`) — архив обязателен как вложение.

Во всех остальных случаях (диагностика, поиск причины, починка) — **не создавай архив**, работай с логами напрямую через `wb_logs`.

Сбор занимает 30-60 секунд:

```
wb_ssh_exec_async sn=<SN> cmd='wb-diag-collect /tmp/diag'
```

`wb-diag-collect` берёт аргумент как **префикс** и сам дописывает `_SN_ДАТА.zip`. Реальное имя узнавай после завершения:

```
wb_job_status job_id=<id>     # дождись exited
wb_ssh_exec sn=<SN> cmd='ls -1 /tmp/diag*.zip | tail -1'
```

Скачивание архива через локальный `scp` (вне MCP) или `wb_read_file`, если архив помещается в 64 КБ (обычно нет — там десятки МБ, используй scp):

```bash
scp root@wirenboard-<SN>.local:<путь> ./
```

## Принцип

Диагностируй → читай документацию → объясни причину → предложи решение → жди подтверждения. Не чини вслепую.
