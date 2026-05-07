---
name: network
description: Сетевая конфигурация контроллера Wiren Board — NetworkManager, wb-connection-manager, ethernet/wifi/4G/OpenVPN, static IP, failover, DNS. Hotspot настройки.
allowed-tools: Bash Read Write WebFetch
---

# network

Сетевая подсистема WB: **NetworkManager** управляет физическими соединениями (eth0/eth1/wlan0/ppp0/...), **wb-connection-manager** делает между ними приоритет и автоматический failover. Конфиг `/etc/wb-connection-manager.conf` (через `confed`) — единая точка правды для UI Web-интерфейса.

Подгружай при: «настрой 4G», «дай инет через sim1», «WiFi-точка», «не пингуется наружу», «static IP», «настроить DNS», «не цепляется eth1», «модем не подключается», «failover не работает», «OpenVPN клиент», «настройки сети».

**Не путай с `/troubleshooting`** (общая диагностика «что-то сломалось»). Этот скилл — для целевой настройки.

## Архитектура

```
┌─────────────────────────────────────────────────┐
│  /etc/wb-connection-manager.conf  (confed UI)   │
│  └─ data:    физические интерфейсы              │
│  └─ ui:      приоритеты, типы, видимое в Web UI │
└────────────────────┬────────────────────────────┘
                     │ wb-connection-manager
                     ▼
┌─────────────────────────────────────────────────┐
│  NetworkManager (nmcli)                          │
│  └─ /etc/NetworkManager/system-connections/*.nmconnection │
│  └─ управляет ip / route / dns                  │
└─────────────────────────────────────────────────┘
```

**wb-connection-manager** делает switching: если eth0 упал, переключается на eth1 / wifi / 4G по приоритету из конфига. Сам по себе он не создаёт connections — это делает NetworkManager.

## Базовые команды

```bash
ssh root@<HOST> 'ip -j -4 addr show'                                  # интерфейсы и IP (JSON)
ssh root@<HOST> 'ip -4 route show'                                    # таблица маршрутов
ssh root@<HOST> 'ip -4 route show default'                            # текущий default
ssh root@<HOST> 'nmcli -t -f NAME,UUID,TYPE,DEVICE,STATE connection show'   # все соединения
ssh root@<HOST> 'nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device'     # все устройства
ssh root@<HOST> 'cat /etc/resolv.conf'                                # DNS
```

**Активный uplink** = соединение со state `activated` и default route через него.

```bash
ssh root@<HOST> 'ip -4 route show default | head -1'
# default via 192.168.2.1 dev eth0 ...
```

## Подключиться к WiFi-сети

```bash
ssh root@<HOST> 'nmcli device wifi list ifname wlan1'                          # сканировать
ssh root@<HOST> 'nmcli device wifi connect "<SSID>" password "<pwd>" ifname wlan1'  # подключиться
ssh root@<HOST> 'nmcli connection modify "<SSID>" connection.autoconnect yes'  # автоконнект при загрузке
```

`wlan1` — внешний USB-донгл если есть. `wlan0` обычно занят под точку доступа `wb-ap`. Если только один WiFi-чип — отключи AP на время:

```bash
ssh root@<HOST> 'nmcli connection down wb-ap'
```

## Настроить точку доступа (hotspot)

На контроллере уже есть готовый профиль `wb-ap` (SSID `WirenBoard-<SN>`, IP `192.168.42.1/24`, NAT). Изменить:

```bash
ssh root@<HOST> 'nmcli connection modify wb-ap 802-11-wireless.ssid "MyAP"'
ssh root@<HOST> 'nmcli connection modify wb-ap 802-11-wireless-security.key-mgmt wpa-psk wifi-sec.psk "MyPassword123"'
ssh root@<HOST> 'nmcli connection up wb-ap'
```

Открытая сеть → `802-11-wireless-security.key-mgmt none`.

## Static IP вместо DHCP

```bash
ssh root@<HOST> 'nmcli connection modify wb-eth0 \
  ipv4.method manual \
  ipv4.addresses 192.168.10.50/24 \
  ipv4.gateway 192.168.10.1 \
  ipv4.dns "192.168.10.1 8.8.8.8"'
ssh root@<HOST> 'nmcli connection up wb-eth0'
```

Вернуть DHCP: `ipv4.method auto`, обнулить `ipv4.addresses ""`, `ipv4.gateway ""`, `ipv4.dns ""`.

## 4G/GSM (sim1/sim2)

WB7/WB8 имеет встроенный GSM-модем + два слота под SIM. Соединения `wb-gsm-sim1` / `wb-gsm-sim2` уже преднастроены.

```bash
ssh root@<HOST> 'nmcli connection show wb-gsm-sim1 | grep -E "gsm|connection"'      # параметры
ssh root@<HOST> 'mmcli -L'                                                          # список модемов
ssh root@<HOST> 'mmcli -m 0'                                                        # детали (signal, IMEI, registration)
ssh root@<HOST> 'mmcli -m 0 --signal-get'                                           # уровень сигнала
ssh root@<HOST> 'mmcli -m 0 --location-get'                                         # сота, если включено
```

**APN**, если оператор требует ручной — `nmcli connection modify wb-gsm-sim1 gsm.apn "internet"`. PIN — `gsm.pin "1234"`.

**Активировать** конкретную SIM:

```bash
ssh root@<HOST> 'nmcli connection up wb-gsm-sim1'
```

`wb-connection-manager` сам переключается между uplinks по приоритету, но руками — через `nmcli connection up <name>`.

**Если модем не виден** (`mmcli -L` пустой):
1. `dmesg | grep -i 'modem\|qmi\|cdc-wdm\|usbserial' | tail -20` — увидел ли ядро.
2. `systemctl status ModemManager` — драйвер живой?
3. `lsusb` — модем перечислен среди USB-устройств?
4. На WB7/WB8 — питание модема и SIM. См. wiki «WB-MOD-MODEM» / встроенный модем модели контроллера.

## OpenVPN клиент

Файл `<name>.ovpn` от провайдера VPN:

```bash
scp client.ovpn root@<HOST>:/tmp/
ssh root@<HOST> 'nmcli connection import type openvpn file /tmp/client.ovpn'
ssh root@<HOST> 'nmcli connection modify <name> +vpn.data username=<user>'
ssh root@<HOST> 'nmcli connection modify <name> +vpn.secrets password=<pwd>'
ssh root@<HOST> 'nmcli connection up <name>'
```

Включить автоконнект — `connection.autoconnect yes`. Проверка — `ip -4 addr show tun0`, `curl -s ifconfig.me`.

`/etc/NetworkManager/system-connections/*.nmconnection` хранит секреты в plaintext — права 0600, доступ только root.

## DNS

`/etc/resolv.conf` обычно symlink на `/run/NetworkManager/resolv.conf` или похожий — менять руками **бесполезно**, перезатрётся.

Через nmcli:

```bash
ssh root@<HOST> 'nmcli connection modify <conn> ipv4.dns "8.8.8.8 1.1.1.1"'
ssh root@<HOST> 'nmcli connection modify <conn> ipv4.ignore-auto-dns yes'   # игнорировать DNS из DHCP
ssh root@<HOST> 'nmcli connection up <conn>'
```

Без `ignore-auto-dns` ваш DNS добавится **в конец** списка — DHCP-DNS будет первым.

## wb-connection-manager: приоритеты и failover

Просмотр текущих приоритетов через confed:

```bash
ssh root@<HOST> 'CID=ai-$(date +%s); mosquitto_sub -t "/rpc/v1/confed/Editor/Load/$CID/reply" -C 1 -W 5 & sleep 0.2; mosquitto_pub -t "/rpc/v1/confed/Editor/Load/$CID" -m "{\"id\":1,\"params\":{\"path\":\"/etc/wb-connection-manager.conf\"}}"; wait' \
  | jq '.result.content.ui.con_switch.connections'
```

`connections` — упорядоченный список `connection_uuid` от высшего приоритета к низшему. Failover идёт по нему.

Правка через `confed/Editor/Save` (см. `/wb-mqtt-serial` для общего паттерна — формат тот же).

**Логи**: `journalctl -u wb-connection-manager -n 50 --no-pager` — что переключалось и почему.

## Диагностика «нет интернета»

1. **Линк** — `ip -4 addr show <iface>` — есть IP?
2. **Default route** — `ip -4 route show default` — есть?
3. **Pinger** — `ping -c1 -W2 8.8.8.8` (без DNS) и `ping -c1 -W2 google.com` (с DNS).
4. **DNS** — `cat /etc/resolv.conf`, `nslookup google.com`.
5. **Логи NM** — `journalctl -u NetworkManager -n 50 --no-pager`.
6. **Логи wb-connection-manager** — `journalctl -u wb-connection-manager -n 30 --no-pager` — переключения failover.
7. **Если 4G** — `mmcli -m 0 --signal-get`, `mmcli -m 0 | grep -E 'state|registration'`.

## NetworkManager profiles vs wb-connection-manager.conf

NM-профили живут в `/etc/NetworkManager/system-connections/*.nmconnection`. **Файлы обновляются автоматически** при `nmcli connection modify`. Прямая правка возможна, но требует `chmod 0600` и `systemctl restart NetworkManager`.

`/etc/wb-connection-manager.conf` — слой поверх для UI и приоритетов. Если правишь NM напрямую, помни: confed-конфиг не пересоздаётся, и Web UI может показывать устаревшее.

**Рекомендация**: примитивные изменения (SSID, password, static IP) — через `nmcli`. Изменения приоритетов / структурные — через `wb_confed_save` `/etc/wb-connection-manager.conf`.

## Грабли

- **Не проверил линк** перед DNS — типичная ошибка диагностики. Сначала `ip addr`, потом `ping IP`, потом `ping имя`.
- **Правка `/etc/resolv.conf`** руками — затирается NM. Только через `nmcli ipv4.dns`.
- **Поднятие VPN ломает доступ к WB-AP** — если VPN ставит default через себя, локальная сеть отвалится. `connection.autoconnect-priority` или ручной запуск.
- **`wlan0` под AP** — нельзя одновременно использовать как клиент. Для WiFi-клиента нужен второй WiFi-адаптер (USB).
- **APN провайдера** — без правильного `gsm.apn` модем не получит IP. Проверь у оператора.
- **PIN** — некоторые операторы требуют. Без PIN модем `Locked`.
- **Failover «прыгает»** — низкий уровень GSM-сигнала, плохой WiFi. Лог wb-connection-manager покажет, на чём заклинивает.
- **NM не запускается** — `systemctl status NetworkManager`, kernel mismatch (см. `/troubleshooting`).
- **Кастомный nmconnection не переживёт FIT** — backup через `/controller-backup`.

## Документация

- NetworkManager: <https://networkmanager.dev/docs/>
- nmcli reference: `man nmcli`, <https://www.networkmanager.dev/docs/api/latest/nmcli.html>
- ModemManager: <https://www.freedesktop.org/wiki/Software/ModemManager/>
- WB wiki сеть: <https://wirenboard.com/wiki/Network>
