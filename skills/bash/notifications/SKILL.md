---
name: notifications
description: Уведомления с контроллера Wiren Board — Telegram, Email, SMS из правил wb-rules. alarms.conf, Notify-API. Настройка email-релея, Telegram-бота.
allowed-tools: Bash Read Write WebFetch
---

# notifications

Отправка уведомлений с контроллера во внешние каналы из правил `wb-rules` (`Notify.*`) или через службу alarms (`alarms.conf`).

Подгружай при: «отправь телеграм когда…», «настрой email», «SMS при аварии», «не приходят уведомления», «alarms.conf», «Notify.sendTelegramMessage», «email-релей», «Telegram-бот для контроллера».

## Каналы

| Канал | API в wb-rules | Требует |
|-------|----------------|---------|
| Telegram | `Notify.sendTelegramMessage(token, chatId, text)` | Bot token у `@BotFather`, chat_id (ваш, группы или канала) |
| Email | `Notify.sendEmail(to, subject, body)` | Локальный MTA (`exim4`/`msmtp`) с настроенным релеем |
| SMS | `Notify.sendSMS(phone, body)` | Встроенный GSM-модем + симка с балансом + работающий ModemManager |

`Notify.*` — синхронные с точки зрения wb-rules: вызвал, забыл. Доставка асинхронная, **проверки доставки нет** — для критичных уведомлений делай retry/fallback в коде правила.

## Telegram

### Создание бота

1. В Telegram — `@BotFather` → `/newbot` → имя/username → получи **bot token** (`123456:ABC...`).
2. **chat_id** для личных сообщений — отправь боту любое сообщение, потом `curl https://api.telegram.org/bot<TOKEN>/getUpdates | jq '.result[].message.chat.id'`. Числовое значение — твой chat_id.
3. Для группы — добавь бота в группу, отправь сообщение, аналогично через `getUpdates`. chat_id группы будет с минусом (`-123456`).
4. Для канала — добавь бота как админа, попроси кого-то написать в канал (или forward), `getUpdates`.

### Из wb-rules

```js
defineRule("alert_on_overheat", {
  asSoonAs: function () { return dev["wb-msw-v4_20/Temperature"] > 40; },
  then: function () {
    Notify.sendTelegramMessage(
      "123456:ABC...",
      "987654321",
      "Перегрев: " + dev["wb-msw-v4_20/Temperature"] + "°C"
    );
  }
});
```

**НЕ зашивай токен в код** в production. Лучше через PersistentStorage:

```js
var ps = new PersistentStorage("notify_creds", {global: true});
// один раз через консоль или скрипт инициализации:
// ps["telegram_token"] = "123456:ABC...";
// ps["telegram_chat"] = "987654321";

defineRule("alert", {
  whenChanged: "wb-mwac_25/F1",
  then: function (newValue) {
    if (newValue) Notify.sendTelegramMessage(ps["telegram_token"], ps["telegram_chat"], "Протечка!");
  }
});
```

### Прямой curl (без wb-rules)

Для скриптов, таймеров, systemd-юнитов:

```bash
ssh root@<HOST> 'curl -s -m10 -X POST "https://api.telegram.org/bot<TOKEN>/sendMessage" \
  -d "chat_id=<CHAT_ID>" \
  -d "text=Сообщение из контроллера"'
```

В ответе `{"ok":true,"result":...}` — успех.

## Email

### Настройка локального MTA через msmtp (рекомендуется)

`msmtp-mta` лёгкий, ставится через apt:

```bash
ssh root@<HOST> 'apt-get install -y msmtp-mta'
```

Конфиг `/etc/msmtprc`:

```bash
ssh root@<HOST> 'cat > /etc/msmtprc' <<'EOF'
defaults
auth on
tls on
tls_trust_file /etc/ssl/certs/ca-certificates.crt
logfile /var/log/msmtp.log

account default
host smtp.gmail.com
port 587
from controller@example.com
user controller@example.com
password <пароль приложения>
EOF
ssh root@<HOST> 'chmod 0600 /etc/msmtprc'
```

Для Gmail — нужен **App Password** (не обычный пароль аккаунта), включить 2FA, потом сгенерить app password.

Тест:

```bash
ssh root@<HOST> 'echo -e "Subject: test\n\nbody" | msmtp recipient@example.com'
```

### Из wb-rules

```js
Notify.sendEmail("user@example.com", "Авария", "Свет в подвале не выключается");
```

`Notify.sendEmail` использует системный `sendmail`/`mail` — msmtp-mta перехватывает.

## SMS

Через встроенный GSM-модем (`mmcli`) — нужна симка с балансом. На WB7/WB8 — встроенный модем, на старых — внешний WB-MOD-MODEM.

### Из wb-rules

```js
Notify.sendSMS("+71234567890", "Текст не более 70 символов для одного SMS на кириллице");
```

### Прямой mmcli

```bash
ssh root@<HOST> 'mmcli -m 0 --messaging-create-sms="text=\"Hello\",number=\"+71234567890\""'
# вернёт path вроде /org/freedesktop/ModemManager1/SMS/123
ssh root@<HOST> 'mmcli -s /org/freedesktop/ModemManager1/SMS/123 --send'
```

**Кириллица** в SMS = 70 символов на сообщение, латиница = 160. Длинные SMS режутся на части (multipart) — каждая часть тарифицируется отдельно.

## alarms.conf — централизованные алармы

`/etc/wb-rules/alarms.conf` — JSON, описывающий алармы декларативно. Загружается из правила:

```js
Alarms.load("/etc/wb-rules/alarms.conf");
```

Формат:

```json
{
  "deviceName": "alarms",
  "deviceTitle": "Alarms",
  "recipients": [
    {"type": "telegram", "token": "<TOKEN>", "chatId": "<CHAT_ID>"},
    {"type": "email", "to": "user@example.com"},
    {"type": "sms", "phone": "+71234567890"}
  ],
  "alarms": [
    {
      "name": "leak",
      "cell": "wb-mwac_25/F1",
      "expectedValueParameter": false,
      "alarmMessage": "Протечка в подвале!",
      "noAlarmMessage": "Протечка устранена",
      "interval": 600
    }
  ]
}
```

`interval` — секунды между повторами уведомления, пока аларм активен. Без него — одно уведомление при срабатывании.

`expectedValueParameter` — нормальное значение, аларм когда **не равно** ему. Альтернативно `minValueParameter`/`maxValueParameter` для пороговых.

После правки `alarms.conf` — `systemctl restart wb-rules`.

## Грабли

- **Хардкод токена** — попадёт в git/бэкап. Через `PersistentStorage` или `wb_read_file` секрет-файла.
- **Telegram chat_id для канала** — отрицательный, начинается с `-100`. Не путай с личным.
- **Gmail без App Password** — обычный пароль не работает с 2FA, нужен app password.
- **MTA не настроен** — `Notify.sendEmail` молча проглотит. `journalctl -u wb-rules -p err` покажет если sendmail не нашёлся.
- **SMS-кириллица** — 70 символов на одно SMS, превышение = multipart, тарификация ×N.
- **Нет интернета** — Telegram и email отвалятся. SMS работает (через GSM), но если модем под uplink — пакеты потеряются на момент отправки SMS.
- **alarms.conf без рестарта wb-rules** — изменения не подхватятся.
- **Множественные алармы без `interval`** — спам.

## Документация

- Telegram Bot API: <https://core.telegram.org/bots/api>
- msmtp: <https://marlam.de/msmtp/>
- ModemManager SMS: <https://www.freedesktop.org/wiki/Software/ModemManager/>
- WB wiki — alarms: <https://wirenboard.com/wiki/Wb-rules#Alarms>
