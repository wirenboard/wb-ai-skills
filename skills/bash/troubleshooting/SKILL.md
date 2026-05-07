---
name: troubleshooting
description: "Общая диагностика проблем на контроллере Wiren Board. Упавшие сервисы, нехватка места, kernel mismatch, Docker, iptables, диагностический архив. НЕ для serial/Modbus — для этого есть troubleshooting-serial."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# troubleshooting

Общая диагностика проблем на контроллере Wiren Board. Подгружай когда пользователь говорит: «не работает», «почини», «сломалось», «ошибка», «не запускается», «упал сервис», «проблема с...», «собери диагностику», «диагностический архив», «логи и состояние» — и это НЕ про serial/Modbus (для serial есть troubleshooting-serial).

Не путай с бэкапом (`controller-backup`). Диагностический архив — для анализа и поддержки, не для восстановления. Собирается утилитой `wb-diag-collect` и включает: конфиги из `/etc`, логи сервисов (wb*, mosquitto, NetworkManager и др.), вывод диагностических команд (df, ps, ip, dpkg и др.).

**Переменная HOST:** во всех примерах ниже `<HOST>` означает `wirenboard-<SN>.local`, где `<SN>` — серийный номер контроллера (например `wirenboard-AABBCCDD.local`). Подставляй реальный адрес.

## Первые шаги — всегда

Прежде чем чинить — разберись в причине. Не чини симптомы.

### 0. Документация — ОБЯЗАТЕЛЬНО

**Перед любой починкой** используй `WebFetch` на страницу проблемного компонента в вики WB. Например: Docker — `WebFetch('https://wiki.wirenboard.com/wiki/Docker')`, Modbus — `WebFetch('https://wiki.wirenboard.com/wiki/Modbus')`, Home Assistant — `WebFetch('https://wiki.wirenboard.com/wiki/Home_Assistant')`. Ищи разделы "Известные проблемы", "Troubleshooting", "Ограничения". Если решение там есть — применяй его, не изобретай своё.

### 1. Kernel mismatch

**Самая частая причина проблем после обновления.** Проверь первым делом:

```bash
ssh root@<HOST> 'echo "running: $(uname -r)"; dpkg -l "linux-image-wb*" 2>/dev/null | grep ^ii | awk "{print \"installed:\", \$3}"'
```

Если версии не совпадают — контроллер работает на старом ядре. Модули ядра (br_netfilter, iptable_nat, can, i2c и др.) не загрузятся, Docker/iptables/сеть могут не работать. **Единственное решение — перезагрузка.** Не пытайся обойти через modprobe/iptables-legacy — это бесполезно при kernel mismatch.

### 2. Место на диске

```bash
ssh root@<HOST> "df -h / /mnt/data"
```

`use% > 95%` или свободного места `< 100 МБ` (на типовом 2-гиговом rootfs) — критично: apt не работает, логи не пишутся, сервисы падают. Ориентируйся на процент использования, а не на абсолютные значения — размер `/` зависит от платформы (wb6 — 2 ГБ, wb7/wb8 — 2 ГБ, на старых сборках встречается ~700 МБ). Чистка: `apt clean; journalctl --vacuum-time=3d; rm -rf /tmp/*`.

### 3. Упавшие сервисы

```bash
ssh root@<HOST> "systemctl --failed --no-pager"
```

Для каждого упавшего — два запроса (вместе они дают полную картину):
```bash
ssh root@<HOST> "systemctl status <unit> --no-pager"        # exit code, Result, ExecMainStatus — короткий summary
ssh root@<HOST> "journalctl -u <unit> -n 50 --no-pager"    # подробные логи с причиной падения
```

`systemctl status` для failed unit'а сам возвращает exit code 3 — это **нормально** (статус-код systemctl, не ssh-ошибка). При автоматизации не путай с реальной ошибкой подключения.

### 4. Журнал ошибок

```bash
ssh root@<HOST> "journalctl -p err --since '1 hour ago' --no-pager"
```

Без `--since` `journalctl` вернёт N последних строк независимо от давности — могут оказаться ошибки недельной давности. Период подбирай по контексту (`'10 minutes ago'`, `'today'`, `'1 hour ago'`).

### 5. Нагрузка и память

```bash
ssh root@<HOST> "uptime; free -h"
```

Load > 4 на WB — перегрузка.
```bash
ssh root@<HOST> "top -bn1 | head -20"
```
Покажет кто ест CPU.

## Типичные проблемы

| Симптом | Первый шаг |
|---|---|
| Сервис не запускается после обновления | Kernel mismatch -> перезагрузка |
| Docker не стартует, iptables ошибки | Сначала kernel mismatch. Если ядро ОК — iptables-legacy fix (см. ниже) |
| modprobe: module not found | Kernel mismatch -> перезагрузка |
| apt не работает, dpkg lock | `fuser /var/lib/dpkg/lock-frontend` — кто держит. Если зомби от прерванного apt: `dpkg --configure -a` |
| Сервис падает в цикле | `journalctl -u <unit> -n 100` — ищи причину, не перезапускай вслепую |
| `fstrim.service` failed, `status=64/USAGE` | Запись в `/etc/fstab` указывает на физически отсутствующий раздел (типично — `/mnt/sdcard` без вставленной SD). `fstrim --listed-in /etc/fstab` падает, не дойдя до остальных точек. Проверь `mount` и `ls /dev/mmcblk1*`. Лечение: убрать строку из fstab или drop-in c `ExecStart=/sbin/fstrim --fstab --quiet-unsupported` |
| Нет сети | `ip addr`, `nmcli`, `ping 8.8.8.8`, `cat /etc/resolv.conf` |
| MQTT не работает | `systemctl is-active mosquitto`, `mosquitto_sub -t '#' -C 1 -W 2` |
| Web UI не открывается | `systemctl is-active nginx wb-mqtt-homeui` |

## Docker и iptables

Если Docker не стартует с ошибками вроде `Chain 'MASQUERADE' does not exist`, `DOCKER-ISOLATION-STAGE`, `Failed to Setup IP tables` — и kernel mismatch исключён:

1. Переключи iptables на legacy:
```bash
ssh root@<HOST> "update-alternatives --set iptables /usr/sbin/iptables-legacy && update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy"
```

2. Создай недостающее правило NAT:
```bash
ssh root@<HOST> "iptables -w10 -t nat -I POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE"
```

3. Перезапусти Docker:
```bash
ssh root@<HOST> "systemctl restart docker && systemctl is-active docker"
```

Если не помогло — перезагрузка:
```bash
ssh root@<HOST> "reboot"
```

Подробнее: <https://wiki.wirenboard.com/wiki/Docker>.

## Диагностический архив

**Собирай ТОЛЬКО в двух случаях:**
1. Пользователь явно просит «пришли диагархив» / «диагностический архив»
2. Составляешь багрепорт — архив обязателен как вложение вместе с логами по проблеме

Во всех остальных случаях (диагностика, поиск причины, починка) — **не создавай архив**, работай с логами напрямую через SSH.

Сбор занимает 30-60 секунд, запускай как фоновую задачу:
```bash
ssh root@<HOST> 'systemd-run --unit=wb-ai-job-$(cat /dev/urandom | tr -dc a-z0-9 | head -c8) --collect bash -c "wb-diag-collect /tmp/diag"'
```

`wb-diag-collect` берёт аргумент как **префикс** и сам дописывает `_SN_ДАТА.zip` — реальное имя заранее неизвестно.

После завершения — найди файл и скачай:
```bash
ssh root@<HOST> "ls /tmp/diag*.zip | tail -1"
```
Затем скопируй файл:
```bash
scp root@<HOST>:<путь из вывода ls> ./
```

## Принцип

Диагностируй -> читай документацию -> объясни причину -> предложи решение -> жди подтверждения. Не чини вслепую.
