import os
import re
import subprocess

# get_mac() has been moved to test_suite, because it uses wb-gen-serial,
# which depends on this (wb-common) package (avoid circular dependency)


def get_cpuinfo_serial():
    with open("/proc/cpuinfo", encoding="utf-8") as f:
        data = f.read()
    matches = re.findall(r"^Serial\s+: ([0-9a-f]+)$", data, re.M)
    if len(matches) > 0:
        return matches[0]
    return None


def _devmem(address):
    r = subprocess.check_output(f"busybox devmem 0x{address:x} 32", shell=True)
    return int(r, 16)


def get_wb7_cpu_serial():
    r3 = _devmem(0x1C1B20C)
    r2 = _devmem(0x1C1B208)
    r1 = _devmem(0x1C1B204)

    return format(r3, "08x") + format(r2, "08x") + format((r1 >> 16) & 0xFFFF, "04x")


def get_mmc_serial():
    mmc_prefix = "/sys/class/mmc_host/mmc0/"
    if os.path.exists(mmc_prefix):
        for entry in os.listdir(mmc_prefix):
            if entry.startswith("mmc"):
                serial_fname = mmc_prefix + entry + "/serial"
                if os.path.exists(serial_fname):
                    with open(serial_fname, encoding="utf-8") as f:
                        serial = f.read().strip()
                    if serial.startswith("0x"):
                        serial = serial[2:]
                    return serial
    return None


def get_eth_mac(num=0):
    netdev_path = os.path.realpath(f"/sys/class/net/eth{num}")
    of_node_path = os.path.realpath(netdev_path + "/../../of_node")

    mac_path = of_node_path + "/local-mac-address"
    if os.path.exists(mac_path):
        with open(mac_path, "rb") as f:
            mac = bytearray(f.read(6))

        # Check if default address was set by U-Boot (no EEPROM and unprogrammed OTP)
        if mac[:3] == bytearray([0x00, 0x04, 0x00]):
            return None

        return "".join(map(lambda b: format(b, "02x"), mac))

    return None


if __name__ == "__main__":
    print("/proc/cpuinfo serial: ", get_cpuinfo_serial())
    # print "WB serial (eth mac): ", get_mac()
