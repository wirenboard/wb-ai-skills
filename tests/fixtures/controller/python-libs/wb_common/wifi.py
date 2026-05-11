# coding: utf-8

import os


def get_wlan_ifaces():
    ifaces = os.listdir("/sys/class/net/")
    wlan_ifaces = [x for x in ifaces if x.startswith("wlan")]
    return wlan_ifaces


def get_wlan_mac():
    ifaces = get_wlan_ifaces()
    if ifaces:
        try:
            return open(f"/sys/class/net/{ifaces[0]}/address", encoding="ascii").read().strip()
        except:  # pylint:disable=bare-except
            return None
    else:
        return None
