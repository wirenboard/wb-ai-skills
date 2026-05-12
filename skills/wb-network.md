---
name: wb-network
description: Network configuration of a Wiren Board controller — NetworkManager, wb-connection-manager, ethernet/wifi/4G/OpenVPN, static IP, failover, DNS. Hotspot setup.
allowed-tools: Bash Read Write WebFetch
---

# network

WB networking subsystem: **NetworkManager** manages physical connections (eth0/eth1/wlan0/ppp0/...), **wb-connection-manager** prioritizes them and does automatic failover. Config `/etc/wb-connection-manager.conf` (via `confed`) is the single source of truth for the web UI.

Load this on: "set up 4G", "give me internet via sim1", "WiFi access point", "no external ping", "static IP", "set DNS", "eth1 doesn't connect", "modem won't connect", "failover not working", "OpenVPN client", "network settings".

**Don't confuse with `/wb-troubleshooting`** (general "something broke" diagnostics). This skill is for targeted setup.

> **wb-cli note:** Network configuration mostly uses standard Linux tools (`nmcli`, `ip`, `mmcli`). `wb-cli` is useful here only for loading/saving `wb-connection-manager.conf` via confed: `wb-cli confed load /etc/wb-connection-manager.conf` and `wb-cli confed save /etc/wb-connection-manager.conf '<json>'`.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  /etc/wb-connection-manager.conf  (confed UI)   │
│  └─ data:    physical interfaces                │
│  └─ ui:      priorities, types, visible in WebUI│
└────────────────────┬────────────────────────────┘
                     │ wb-connection-manager
                     ▼
┌─────────────────────────────────────────────────┐
│  NetworkManager (nmcli)                          │
│  └─ /etc/NetworkManager/system-connections/*.nmconnection │
│  └─ manages ip / route / dns                    │
└─────────────────────────────────────────────────┘
```

**wb-connection-manager** does the switching: if eth0 is down, switches to eth1 / wifi / 4G by priority from the config. By itself it doesn't create connections — that's NetworkManager's job.

## Basic commands

```bash
ssh root@<HOST> 'ip -j -4 addr show'                                  # interfaces and IPs (JSON)
ssh root@<HOST> 'ip -4 route show'                                    # routing table
ssh root@<HOST> 'ip -4 route show default'                            # current default
ssh root@<HOST> 'nmcli -t -f NAME,UUID,TYPE,DEVICE,STATE connection show'   # all connections
ssh root@<HOST> 'nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device'     # all devices
ssh root@<HOST> 'cat /etc/resolv.conf'                                # DNS
```

**Active uplink** = connection in `activated` state with default route through it.

```bash
ssh root@<HOST> 'ip -4 route show default | head -1'
# default via 192.168.2.1 dev eth0 ...
```

## Connect to a WiFi network

```bash
ssh root@<HOST> 'nmcli device wifi list ifname wlan1'                          # scan
ssh root@<HOST> 'nmcli device wifi connect "<SSID>" password "<pwd>" ifname wlan1'  # connect
ssh root@<HOST> 'nmcli connection modify "<SSID>" connection.autoconnect yes'  # autoconnect at boot
```

`wlan1` — external USB dongle if present. `wlan0` is usually used by the `wb-ap` access point. If there's only one WiFi chip — disable AP for the duration:

```bash
ssh root@<HOST> 'nmcli connection down wb-ap'
```

## Configure access point (hotspot)

The controller already has a ready `wb-ap` profile (SSID `WirenBoard-<SN>`, IP `192.168.42.1/24`, NAT). Modify:

```bash
ssh root@<HOST> 'nmcli connection modify wb-ap 802-11-wireless.ssid "MyAP"'
ssh root@<HOST> 'nmcli connection modify wb-ap 802-11-wireless-security.key-mgmt wpa-psk wifi-sec.psk "MyPassword123"'
ssh root@<HOST> 'nmcli connection up wb-ap'
```

Open network → `802-11-wireless-security.key-mgmt none`.

## Static IP instead of DHCP

```bash
ssh root@<HOST> 'nmcli connection modify wb-eth0 \
  ipv4.method manual \
  ipv4.addresses 192.168.10.50/24 \
  ipv4.gateway 192.168.10.1 \
  ipv4.dns "192.168.10.1 8.8.8.8"'
ssh root@<HOST> 'nmcli connection up wb-eth0'
```

Back to DHCP: `ipv4.method auto`, clear `ipv4.addresses ""`, `ipv4.gateway ""`, `ipv4.dns ""`.

## 4G/GSM (sim1/sim2)

WB7/WB8 has a built-in GSM modem + two SIM slots. Connections `wb-gsm-sim1` / `wb-gsm-sim2` are pre-configured.

```bash
ssh root@<HOST> 'nmcli connection show wb-gsm-sim1 | grep -E "gsm|connection"'      # parameters
ssh root@<HOST> 'mmcli -L'                                                          # modem list
ssh root@<HOST> 'mmcli -m 0'                                                        # details (signal, IMEI, registration)
ssh root@<HOST> 'mmcli -m 0 --signal-get'                                           # signal strength
ssh root@<HOST> 'mmcli -m 0 --location-get'                                         # cell, if enabled
```

**APN**, if the operator requires manual — `nmcli connection modify wb-gsm-sim1 gsm.apn "internet"`. PIN — `gsm.pin "1234"`.

**Activate** a specific SIM:

```bash
ssh root@<HOST> 'nmcli connection up wb-gsm-sim1'
```

`wb-connection-manager` switches between uplinks by priority on its own, but manually — via `nmcli connection up <name>`.

**If the modem is not visible** (`mmcli -L` empty):
1. `dmesg | grep -i 'modem\|qmi\|cdc-wdm\|usbserial' | tail -20` — did the kernel see it.
2. `systemctl status ModemManager` — is the driver alive?
3. `lsusb` — is the modem listed among USB devices?
4. On WB7/WB8 — modem and SIM power. See wiki "WB-MOD-MODEM" / built-in modem of the controller model.

## OpenVPN client

`<name>.ovpn` file from the VPN provider:

```bash
scp client.ovpn root@<HOST>:/tmp/
ssh root@<HOST> 'nmcli connection import type openvpn file /tmp/client.ovpn'
ssh root@<HOST> 'nmcli connection modify <name> +vpn.data username=<user>'
ssh root@<HOST> 'nmcli connection modify <name> +vpn.secrets password=<pwd>'
ssh root@<HOST> 'nmcli connection up <name>'
```

Enable autoconnect — `connection.autoconnect yes`. Verify — `ip -4 addr show tun0`, `curl -s ifconfig.me`.

`/etc/NetworkManager/system-connections/*.nmconnection` stores secrets in plaintext — perms 0600, root only.

## DNS

`/etc/resolv.conf` is usually a symlink to `/run/NetworkManager/resolv.conf` or similar — editing by hand is **pointless**, will be overwritten.

Via nmcli:

```bash
ssh root@<HOST> 'nmcli connection modify <conn> ipv4.dns "8.8.8.8 1.1.1.1"'
ssh root@<HOST> 'nmcli connection modify <conn> ipv4.ignore-auto-dns yes'   # ignore DNS from DHCP
ssh root@<HOST> 'nmcli connection up <conn>'
```

Without `ignore-auto-dns` your DNS is added **at the end** of the list — DHCP DNS will be first.

## wb-connection-manager: priorities and failover

View current priorities via confed:

```bash
ssh root@<HOST> wb-cli confed load /etc/wb-connection-manager.conf
```

Parse the result (JSON) — look at `.config.ui.con_switch.connections` — ordered list of `connection_uuid` from highest to lowest priority. Failover follows it.

Save edited config:

```bash
ssh root@<HOST> 'wb-cli confed save /etc/wb-connection-manager.conf '"'"'<updated-json>'"'"''
```

**Logs**: `journalctl -u wb-connection-manager -n 50 --no-pager` — what switched and why.

## Diagnosing "no internet"

1. **Link** — `ip -4 addr show <iface>` — is there an IP?
2. **Default route** — `ip -4 route show default` — exists?
3. **Pinger** — `ping -c1 -W2 8.8.8.8` (no DNS) and `ping -c1 -W2 google.com` (with DNS).
4. **DNS** — `cat /etc/resolv.conf`, `nslookup google.com`.
5. **NM logs** — `journalctl -u NetworkManager -n 50 --no-pager`.
6. **wb-connection-manager logs** — `journalctl -u wb-connection-manager -n 30 --no-pager` — failover switches.
7. **If 4G** — `mmcli -m 0 --signal-get`, `mmcli -m 0 | grep -E 'state|registration'`.

## NetworkManager profiles vs wb-connection-manager.conf

NM profiles live in `/etc/NetworkManager/system-connections/*.nmconnection`. **The files are updated automatically** on `nmcli connection modify`. Direct editing is possible but requires `chmod 0600` and `systemctl restart NetworkManager`.

`/etc/wb-connection-manager.conf` is a layer on top for UI and priorities. If you edit NM directly, remember: the confed config isn't regenerated, and the web UI may show stale data.

**Recommendation**: simple changes (SSID, password, static IP) — via `nmcli`. Priority/structural changes — via `wb_confed_save` `/etc/wb-connection-manager.conf`.

## Pitfalls

- **Didn't check the link** before DNS — typical diagnostic mistake. First `ip addr`, then `ping IP`, then `ping name`.
- **Editing `/etc/resolv.conf`** by hand — overwritten by NM. Only via `nmcli ipv4.dns`.
- **Bringing up VPN breaks WB-AP access** — if VPN sets default through itself, the local network goes away. `connection.autoconnect-priority` or manual start.
- **`wlan0` under AP** — can't be used as a client at the same time. For a WiFi client a second WiFi adapter (USB) is required.
- **Provider's APN** — without the right `gsm.apn` the modem won't get an IP. Check with the operator.
- **PIN** — some operators require it. Without PIN the modem is `Locked`.
- **Failover "bouncing"** — low GSM signal, bad WiFi. wb-connection-manager log shows what's stuck.
- **NM doesn't start** — `systemctl status NetworkManager`, kernel mismatch (see `/wb-troubleshooting`).
- **Custom nmconnection won't survive FIT** — backup via `/wb-controller-backup`.

## Documentation

- NetworkManager: <https://networkmanager.dev/docs/>
- nmcli reference: `man nmcli`, <https://www.networkmanager.dev/docs/api/latest/nmcli.html>
- ModemManager: <https://www.freedesktop.org/wiki/Software/ModemManager/>
- WB wiki networking: <https://wirenboard.com/wiki/Network>
