---
name: notifications
description: Уведомления с Wiren Board через MCP — Telegram, Email, SMS из правил wb-rules, alarms.conf, Notify-API.
allowed-tools: Bash Read Write WebFetch
---

# notifications (MCP)

Уведомления через каналы Telegram/Email/SMS из `wb-rules` (`Notify.*`) или централизованного `alarms.conf`. Тонкий маршрутизатор поверх `wb_*` tools.

Подгружай при: «отправь телеграм когда…», «настрой email», «SMS при аварии», «не приходят уведомления», «alarms.conf», «Notify.sendTelegramMessage».

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Отправить тестовый Telegram (без правил) | `wb_ssh_exec` `curl ... api.telegram.org/bot.../sendMessage` |
| Установить msmtp-mta (для email) | `wb_ssh_exec_async` `apt-get install -y msmtp-mta` |
| Записать `/etc/msmtprc` | `wb_write_file path=/etc/msmtprc` + `wb_ssh_exec chmod 0600 ...` |
| Тестовый email | `wb_ssh_exec` `echo "Subject: t\n\nbody" \| msmtp <to>` |
| Создать SMS через mmcli | `wb_ssh_exec` `mmcli -m 0 --messaging-create-sms=...; mmcli -s <path> --send` |
| Записать правило с `Notify.*` | `wb_rules_save` |
| Записать `/etc/wb-rules/alarms.conf` | `wb_write_file path=/etc/wb-rules/alarms.conf` |
| Перезагрузить wb-rules после правки alarms.conf | `wb_systemd_unit unit=wb-rules action=restart` |
| Логи попыток отправки | `wb_logs unit=wb-rules grep="(?i)notify|telegram|email|sms"` |

## Каналы

| Канал | API в правиле | Требует |
|-------|---------------|---------|
| Telegram | `Notify.sendTelegramMessage(token, chatId, text)` | Bot token + chat_id |
| Email | `Notify.sendEmail(to, subject, body)` | Локальный MTA (msmtp-mta) с релеем |
| SMS | `Notify.sendSMS(phone, body)` | Встроенный GSM-модем + симка |

## Сценарий: настроить Telegram уведомления

1. Создать бота через `@BotFather` → bot token.
2. Получить chat_id (см. bash-двойник, `getUpdates`).
3. Хранить секреты в PersistentStorage (не в коде):

   ```js
   var ps = new PersistentStorage("notify_creds", {global: true});
   ps["telegram_token"] = "...";
   ps["telegram_chat"] = "...";
   ```

4. Создать правило через `wb_rules_save` с `Notify.sendTelegramMessage(ps["telegram_token"], ps["telegram_chat"], "...")`.

## Сценарий: настроить email через msmtp

```
wb_ssh_exec_async sn=<SN> cmd='DEBIAN_FRONTEND=noninteractive apt-get install -y msmtp-mta'
wb_write_file sn=<SN> path=/etc/msmtprc content='<конфиг>'
wb_ssh_exec sn=<SN> cmd='chmod 0600 /etc/msmtprc'
wb_ssh_exec sn=<SN> cmd='echo -e "Subject: test\n\ntest" | msmtp <recipient>'
```

Шаблон `/etc/msmtprc` для Gmail (App Password обязательно):

```
defaults
auth on
tls on
tls_trust_file /etc/ssl/certs/ca-certificates.crt

account default
host smtp.gmail.com
port 587
from controller@example.com
user controller@example.com
password <App Password>
```

## Сценарий: alarms.conf

`wb_write_file path=/etc/wb-rules/alarms.conf` + `wb_systemd_unit unit=wb-rules action=restart`. Формат — см. bash-двойник.

В правиле один раз:

```js
Alarms.load("/etc/wb-rules/alarms.conf");
```

## Грабли

- **Хардкод токена** — секреты через `PersistentStorage` или отдельный конфиг-файл, не в коде правила.
- **Telegram chat_id для канала** — с `-100` префиксом.
- **Gmail без App Password** — не работает.
- **MTA не настроен** — `Notify.sendEmail` тихо проваливается; смотри `wb_logs unit=wb-rules grep=email`.
- **SMS-кириллица** — 70 символов = 1 SMS, многобайтные = multipart с ×N тарификацией.
- **alarms.conf без рестарта wb-rules** — изменения не подхватятся.
- **Доставка не подтверждается** — для критичных уведомлений делай retry в коде.

## Связанные скиллы

- `/wb-rules` — синтаксис и принципы правил с уведомлениями.
- `/network` — нет интернета → нет Telegram/email; SMS через GSM работает.
- `/services` — msmtp/exim как systemd-юниты.

Подробности (bot setup через BotFather, App Password, формат alarms.conf) — bash-двойник `/notifications`.

## Документация

- Telegram Bot API: <https://core.telegram.org/bots/api>
- msmtp: <https://marlam.de/msmtp/>
- WB wiki — alarms: <https://wirenboard.com/wiki/Wb-rules#Alarms>
