---
name: network
description: Wiren Board controller network configuration via MCP — NetworkManager + wb-connection-manager. ethernet/wifi/4G/OpenVPN, static IP, failover, DNS. Hotspot settings.
allowed-tools: Bash Read Write WebFetch
---

# network (MCP)

WB networking subsystem via MCP tools `wb_network_status` + `wb_confed_load/save` for `/etc/wb-connection-manager.conf` + `wb_ssh_exec` for `nmcli` commands.

Load this when: "configure 4G", "give internet via sim1", "WiFi access point", "doesn't ping out", "static IP", "configure DNS", "won't pick up eth1", "modem won't connect", "failover broken", "OpenVPN client".

## Tool routing

| Intent | Tool |
|--------|------|
| Network summary (interfaces, NM connections, default route) | `wb_network_status` (opt. `pingTarget=8.8.8.8` for internet check) |
| wb-connection-manager config (priorities, failover) | `wb_confed_load path=/etc/wb-connection-manager.conf` |
| Save wb-connection-manager config | `wb_confed_save` |
| nmcli commands (modify connection, up/down) | `wb_ssh_exec` `nmcli ...` |
| Scan WiFi | `wb_ssh_exec` `nmcli device wifi list ifname wlan1` |
| Modem control (mmcli) | `wb_ssh_exec` `mmcli -L`/`mmcli -m 0` |
| Logs of NM / wb-connection-manager / ModemManager | `wb_logs unit=NetworkManager` / `wb_logs unit=wb-connection-manager` / `wb_logs unit=ModemManager` |

## Scenario: current network state

```
wb_network_status sn=<SN> pingTarget=8.8.8.8
```

Returns: `interfaces[]`, `defaultRoute`, `nmConnections[]`, `nmDevices[]`, `ping {lossPct, reachable}`. One call covers "is there a link / is there a default / is there internet".

## Scenario: connect to WiFi

```
wb_ssh_exec sn=<SN> cmd='nmcli device wifi list ifname wlan1'
wb_ssh_exec sn=<SN> cmd='nmcli device wifi connect "<SSID>" password "<pwd>" ifname wlan1'
wb_ssh_exec sn=<SN> cmd='nmcli connection modify "<SSID>" connection.autoconnect yes'
```

If there's only one WiFi chip (`wlan0` under AP) — first `nmcli connection down wb-ap`, otherwise drama.

## Scenario: configure a hotspot

The `wb-ap` profile is already there. Tweak SSID and password:

```
wb_ssh_exec sn=<SN> cmd='nmcli connection modify wb-ap 802-11-wireless.ssid "MyAP" 802-11-wireless-security.key-mgmt wpa-psk 802-11-wireless-security.psk "MyPassword123"'
wb_ssh_exec sn=<SN> cmd='nmcli connection up wb-ap'
```

## Scenario: static IP

```
wb_ssh_exec sn=<SN> cmd='nmcli connection modify wb-eth0 ipv4.method manual ipv4.addresses 192.168.10.50/24 ipv4.gateway 192.168.10.1 ipv4.dns "192.168.10.1 8.8.8.8"'
wb_ssh_exec sn=<SN> cmd='nmcli connection up wb-eth0'
```

DHCP back — `ipv4.method auto`, clear `ipv4.addresses`/`ipv4.gateway`/`ipv4.dns` with empty strings.

## Scenario: 4G/GSM

```
wb_ssh_exec sn=<SN> cmd='mmcli -L'                       # is there a modem
wb_ssh_exec sn=<SN> cmd='mmcli -m 0'                     # signal, registration, IMEI
wb_ssh_exec sn=<SN> cmd='nmcli connection modify wb-gsm-sim1 gsm.apn "internet" gsm.pin "1234"'
wb_ssh_exec sn=<SN> cmd='nmcli connection up wb-gsm-sim1'
```

`wb-gsm-sim1` / `wb-gsm-sim2` — preconfigured profiles for two SIMs.

## Scenario: OpenVPN client

```
wb_write_file sn=<SN> path=/tmp/client.ovpn content=<.ovpn contents>
wb_ssh_exec sn=<SN> cmd='nmcli connection import type openvpn file /tmp/client.ovpn'
wb_ssh_exec sn=<SN> cmd='nmcli connection modify <name> +vpn.data username=<user> +vpn.secrets password=<pwd>'
wb_ssh_exec sn=<SN> cmd='nmcli connection up <name>'
```

## Scenario: "no internet"

1. `wb_network_status pingTarget=8.8.8.8` — link, default route, ping.
2. If ping is OK but `nslookup` doesn't work — DNS:
   ```
   wb_ssh_exec sn=<SN> cmd='cat /etc/resolv.conf; nslookup google.com'
   ```
3. Failover switching logs:
   ```
   wb_logs sn=<SN> unit=wb-connection-manager since="1h ago" lines=30
   ```
4. If 4G — `mmcli -m 0 | grep -E 'state|registration|signal'`.

## Failover and priorities

`wb_confed_load /etc/wb-connection-manager.conf` → `content.ui.con_switch.connections` — ordered array of UUIDs from highest to lowest priority. To edit — change order and `wb_confed_save`.

## Gotchas

- **Editing `/etc/resolv.conf` by hand** — overwritten by NM. Only via `nmcli ipv4.dns`.
- **VPN breaks access to WB-AP** — if VPN sets a default route through itself, the local network falls off. Use `connection.autoconnect-priority` or manual VPN start.
- **`wlan0` under AP** — can't be a client at the same time, need a second WiFi adapter.
- **Provider's APN** — without correct `gsm.apn` the modem won't get an IP.
- **`ipv4.ignore-auto-dns`** — without it your DNS is appended at the end of the list, DHCP DNS is first.
- **Failover "flaps"** — low GSM signal, poor WiFi. wb-connection-manager logs will show.
- **NM profiles in `/etc/NetworkManager/system-connections/*.nmconnection` won't survive FIT** — backup via `/controller-backup`.

## Related skills

- `/troubleshooting` — general "doesn't work" diagnostics.
- `/services` — custom `*.service` for running VPN/scripts.
- `/controller-backup` — saving NM profiles before FIT.
- `/wb-cloud` — cloud agent over the internet.

Details (nmcli syntax, OpenVPN, mmcli) — bash-flavor twin `/network`.

## Documentation

- NetworkManager: <https://networkmanager.dev/docs/>
- ModemManager: <https://www.freedesktop.org/wiki/Software/ModemManager/>
- WB wiki: <https://wirenboard.com/wiki/Network>
