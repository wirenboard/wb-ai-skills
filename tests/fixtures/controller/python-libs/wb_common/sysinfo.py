from __future__ import print_function

import os


def get_fw_version():
    try:
        return open("/etc/wb-fw-version", encoding="utf-8").read().strip()
    except Exception:  # pylint:disable=broad-exception-caught
        return None


def get_wb_version():
    return os.environ["WB_VERSION"]
