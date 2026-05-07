---
name: network
description: Сетевая конфигурация контроллера Wiren Board через MCP — NetworkManager + wb-connection-manager. ethernet/wifi/4G/OpenVPN, static IP, failover, DNS. Hotspot настройки.
allowed-tools: Bash Read Write WebFetch
---

# network (MCP)

Сетевая подсистема WB через MCP-tools `wb_network_status` + `wb_confed_load/save` для `/etc/wb-connection-manager.conf` + `wb_ssh_exec` для `nmcli` команд.

Подгружай при: «настрой 4G», «дай инет через sim1», «WiFi-точка», «не пингуется наружу», «static IP», «настроить DNS», «не цепляется eth1», «модем не подключается», «failover не работает», «OpenVPN клиент».

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Сводка по сети (интерфейсы, NM-соединения, default route) | `wb_network_status` (опц. `pingTarget=8.8.8.8` для проверки инета) |
| Конфиг wb-connection-manager (приоритеты, failover) | `wb_confed_load path=/etc/wb-connection-manager.conf` |
| Сохранить конфиг wb-connection-manager | `wb_confed_save` |
| nmcli команды (modify connection, up/down) | `wb_ssh_exec` `nmcli ...` |
| Сканировать WiFi | `wb_ssh_exec` `nmcli device wifi list ifname wlan1` |
| Управление модемом (mmcli) | `wb_ssh_exec` `mmcli -L`/`mmcli -m 0` |
| Логи NM / wb-connection-manager / ModemManager | `wb_logs unit=NetworkManager` / `wb_logs unit=wb-connection-manager` / `wb_logs unit=ModemManager` |

## Сценарий: текущее состояние сети

```
wb_network_status sn=<SN> pingTarget=8.8.8.8
```

Возвращает: `interfaces[]`, `defaultRoute`, `nmConnections[]`, `nmDevices[]`, `ping {lossPct, reachable}`. Один вызов закрывает «есть линк / есть default / есть инет».

## Сценарий: подключиться к WiFi

```
wb_ssh_exec sn=<SN> cmd='nmcli device wifi list ifname wlan1'
wb_ssh_exec sn=<SN> cmd='nmcli device wifi connect "<SSID>" password "<pwd>" ifname wlan1'
wb_ssh_exec sn=<SN> cmd='nmcli connection modify "<SSID>" connection.autoconnect yes'
```

Если только один WiFi-чип (`wlan0` под AP) — сначала `nmcli connection down wb-ap`, иначе drama.

## Сценарий: настроить hotspot

Профиль `wb-ap` уже есть. Поправить SSID и пароль:

```
wb_ssh_exec sn=<SN> cmd='nmcli connection modify wb-ap 802-11-wireless.ssid "MyAP" 802-11-wireless-security.key-mgmt wpa-psk 802-11-wireless-security.psk "MyPassword123"'
wb_ssh_exec sn=<SN> cmd='nmcli connection up wb-ap'
```

## Сценарий: static IP

```
wb_ssh_exec sn=<SN> cmd='nmcli connection modify wb-eth0 ipv4.method manual ipv4.addresses 192.168.10.50/24 ipv4.gateway 192.168.10.1 ipv4.dns "192.168.10.1 8.8.8.8"'
wb_ssh_exec sn=<SN> cmd='nmcli connection up wb-eth0'
```

DHCP обратно — `ipv4.method auto`, обнулить `ipv4.addresses`/`ipv4.gateway`/`ipv4.dns` пустыми строками.

## Сценарий: 4G/GSM

```
wb_ssh_exec sn=<SN> cmd='mmcli -L'                       # есть ли модем
wb_ssh_exec sn=<SN> cmd='mmcli -m 0'                     # сигнал, registration, IMEI
wb_ssh_exec sn=<SN> cmd='nmcli connection modify wb-gsm-sim1 gsm.apn "internet" gsm.pin "1234"'
wb_ssh_exec sn=<SN> cmd='nmcli connection up wb-gsm-sim1'
```

`wb-gsm-sim1` / `wb-gsm-sim2` — преднастроенные профили под две SIM.

## Сценарий: OpenVPN клиент

```
wb_write_file sn=<SN> path=/tmp/client.ovpn content=<содержимое .ovpn>
wb_ssh_exec sn=<SN> cmd='nmcli connection import type openvpn file /tmp/client.ovpn'
wb_ssh_exec sn=<SN> cmd='nmcli connection modify <name> +vpn.data username=<user> +vpn.secrets password=<pwd>'
wb_ssh_exec sn=<SN> cmd='nmcli connection up <name>'
```

## Сценарий: «нет интернета»

1. `wb_network_status pingTarget=8.8.8.8` — линк, default route, ping.
2. Если ping ОК но `nslookup` не работает — DNS:
   ```
   wb_ssh_exec sn=<SN> cmd='cat /etc/resolv.conf; nslookup google.com'
   ```
3. Логи переключений failover:
   ```
   wb_logs sn=<SN> unit=wb-connection-manager since="1h ago" lines=30
   ```
4. Если 4G — `mmcli -m 0 | grep -E 'state|registration|signal'`.

## Failover и приоритеты

`wb_confed_load /etc/wb-connection-manager.conf` → `content.ui.con_switch.connections` — упорядоченный массив UUID от высшего приоритета к низшему. Правка — поменять порядок и `wb_confed_save`.

## Грабли

- **Правка `/etc/resolv.conf` руками** — затирается NM. Только через `nmcli ipv4.dns`.
- **VPN ломает доступ к WB-AP** — если VPN ставит default через себя, локальная сеть отвалится. Используй `connection.autoconnect-priority` или ручной запуск VPN.
- **`wlan0` под AP** — одновременно как клиент нельзя, нужен второй WiFi-адаптер.
- **APN провайдера** — без правильного `gsm.apn` модем не получит IP.
- **`ipv4.ignore-auto-dns`** — без него ваш DNS добавится в конец списка, DHCP-DNS будет первым.
- **Failover «прыгает»** — низкий GSM-сигнал, плохой WiFi. Логи wb-connection-manager покажут.
- **NM-профили в `/etc/NetworkManager/system-connections/*.nmconnection` не переживут FIT** — backup через `/controller-backup`.

## Связанные скиллы

- `/troubleshooting` — общая диагностика «не работает».
- `/services` — кастомные `*.service` для запуска VPN/скриптов.
- `/controller-backup` — сохранение NM-профилей перед FIT.
- `/wb-cloud` — облачный агент через интернет.

Подробности (синтаксис nmcli, OpenVPN, mmcli) — bash-двойник `/network`.

## Документация

- NetworkManager: <https://networkmanager.dev/docs/>
- ModemManager: <https://www.freedesktop.org/wiki/Software/ModemManager/>
- WB wiki: <https://wirenboard.com/wiki/Network>
