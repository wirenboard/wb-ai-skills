---
name: wb-notifications
description: Notifications from Wiren Board via MCP — Telegram, Email, SMS from wb-rules, alarms.conf, Notify API.
allowed-tools: Bash Read Write WebFetch
---

# notifications (MCP)

Notifications via Telegram/Email/SMS channels from `wb-rules` (`Notify.*`) or centralized `alarms.conf`. Thin router on top of `wb_*` tools.

Load this when: "send Telegram when…", "configure email", "SMS on alarm", "notifications don't arrive", "alarms.conf", "Notify.sendTelegramMessage".

## Tool routing

| Intent | Tool |
|--------|------|
| Send a test Telegram (without rules) | `wb_ssh_exec` `curl ... api.telegram.org/bot.../sendMessage` |
| Install msmtp-mta (for email) | `wb_ssh_exec_async` `apt-get install -y msmtp-mta` |
| Write `/etc/msmtprc` | `wb_write_file path=/etc/msmtprc` + `wb_ssh_exec chmod 0600 ...` |
| Test email | `wb_ssh_exec` `echo "Subject: t\n\nbody" \| msmtp <to>` |
| Create SMS via mmcli | `wb_ssh_exec` `mmcli -m 0 --messaging-create-sms=...; mmcli -s <path> --send` |
| Write a rule with `Notify.*` | `wb_rules_save` |
| Write `/etc/wb-rules/alarms.conf` | `wb_write_file path=/etc/wb-rules/alarms.conf` |
| Reload wb-rules after editing alarms.conf | `wb_systemd_unit unit=wb-rules action=restart` |
| Logs of send attempts | `wb_logs unit=wb-rules grep="(?i)notify|telegram|email|sms"` |

## Channels

| Channel | Rule API | Requires |
|---------|----------|----------|
| Telegram | `Notify.sendTelegramMessage(token, chatId, text)` | Bot token + chat_id |
| Email | `Notify.sendEmail(to, subject, body)` | Local MTA (msmtp-mta) with relay |
| SMS | `Notify.sendSMS(phone, body)` | Built-in GSM modem + SIM |

## Scenario: configure Telegram notifications

1. Create a bot via `@BotFather` → bot token.
2. Get chat_id (see bash-flavor twin, `getUpdates`).
3. Store secrets in PersistentStorage (not in code):

   ```js
   var ps = new PersistentStorage("notify_creds", {global: true});
   ps["telegram_token"] = "...";
   ps["telegram_chat"] = "...";
   ```

4. Create a rule via `wb_rules_save` with `Notify.sendTelegramMessage(ps["telegram_token"], ps["telegram_chat"], "...")`.

## Scenario: configure email via msmtp

```
wb_ssh_exec_async sn=<SN> cmd='DEBIAN_FRONTEND=noninteractive apt-get install -y msmtp-mta'
wb_write_file sn=<SN> path=/etc/msmtprc content='<config>'
wb_ssh_exec sn=<SN> cmd='chmod 0600 /etc/msmtprc'
wb_ssh_exec sn=<SN> cmd='echo -e "Subject: test\n\ntest" | msmtp <recipient>'
```

Template `/etc/msmtprc` for Gmail (App Password mandatory):

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

## Scenario: alarms.conf

`wb_write_file path=/etc/wb-rules/alarms.conf` + `wb_systemd_unit unit=wb-rules action=restart`. Format — see bash-flavor twin.

In a rule, once:

```js
Alarms.load("/etc/wb-rules/alarms.conf");
```

## Gotchas

- **Hardcoded token** — secrets via `PersistentStorage` or a separate config file, not in rule code.
- **Telegram chat_id for a channel** — with `-100` prefix.
- **Gmail without App Password** — doesn't work.
- **MTA not configured** — `Notify.sendEmail` silently fails; check `wb_logs unit=wb-rules grep=email`.
- **SMS Cyrillic** — 70 chars = 1 SMS, multibyte = multipart with ×N tariffing.
- **alarms.conf without wb-rules restart** — changes won't be picked up.
- **Delivery isn't confirmed** — for critical notifications add retry in code.

## Related skills

- `/wb-rules` — syntax and principles of rules with notifications.
- `/wb-network` — no internet → no Telegram/email; SMS over GSM works.
- `/wb-services` — msmtp/exim as systemd units.

Details (bot setup via BotFather, App Password, alarms.conf format) — bash-flavor twin `/wb-notifications`.

## Documentation

- Telegram Bot API: <https://core.telegram.org/bots/api>
- msmtp: <https://marlam.de/msmtp/>
- WB wiki — alarms: <https://wirenboard.com/wiki/Wb-rules#Alarms>
