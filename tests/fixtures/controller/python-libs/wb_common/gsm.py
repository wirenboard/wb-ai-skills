# coding: utf-8
from __future__ import print_function

import os
import subprocess


def gsm_decode(hexstr):
    return os.popen(f"echo {hexstr} | xxd -r -ps | iconv -f=UTF-16BE -t=UTF-8").read()


def init_gsm():
    retcode = subprocess.call("wb-gsm restart_if_broken", shell=True)
    if retcode != 0:
        raise RuntimeError("gsm init failed")


def init_baudrate():
    retcode = subprocess.call("wb-gsm init_baud", shell=True)
    if retcode != 0:
        raise RuntimeError("gsm init baudrate failed")


def gsm_get_imei():
    try:
        result = subprocess.run(
            "wb-gsm imei", shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        raise RuntimeError("get imei failed")  # pylint:disable=raise-missing-from


def split_imei(imei):
    imei = str(imei)
    if not imei.isdigit():
        raise RuntimeError("imei is not a numerical")

    if len(imei) != 15:
        raise RuntimeError("wrong imei len")

    prefix = imei[:8]
    sn = imei[8:14]
    crc = imei[14]

    return int(prefix), int(sn), int(crc)
