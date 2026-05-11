from __future__ import print_function

SYS_PREFIX = "/sys/class/leds/"


def set_brightness(led, val):
    with open(SYS_PREFIX + led + "/brightness", mode="wt", encoding="ascii") as file:
        file.write(f"{val}\n")


def set_blink(led, delay_on=100, delay_off=100):
    with open(SYS_PREFIX + led + "/trigger", mode="wt", encoding="ascii") as file:
        file.write("timer\n")

    with open(SYS_PREFIX + led + "/delay_on", mode="wt", encoding="ascii") as file:
        file.write(f"{delay_on}\n")
    with open(SYS_PREFIX + led + "/delay_off", mode="wt", encoding="ascii") as file:
        file.write(f"{delay_off}\n")


def blink_fast(led):
    set_blink(led, 50, 50)
