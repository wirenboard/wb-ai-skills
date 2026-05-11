# coding: utf-8
import subprocess
import time


class ADC:
    N_SAMPLES = 30

    def setup(self):
        subprocess.call("killall -9 wb-homa-adc", shell=True)

    def set_scale(self, channel, scale):
        with open(
            f"/sys/bus/iio/devices/iio:device0/in_voltage{channel}_scale", mode="wt", encoding="ascii"
        ) as file:
            file.write(scale + "\n")

    def get_available_scales(self, channel):
        return (
            open(f"/sys/bus/iio/devices/iio:device0/in_voltage{channel}_scale_available", encoding="ascii")
            .read()
            .strip()
            .split()
        )

    def read_mux_value(self, mux_ch):
        subprocess.call(f"wb-adc-set-mux {mux_ch}", shell=True)
        time.sleep(100e-3)
        return self.read_phys_ch_value(1)

    def read_mux_value_with_source(self, mux_ch, current):

        subprocess.call(f"wb-adc-set-mux {mux_ch}", shell=True)
        time.sleep(100e-3)
        subprocess.call(f"lradc-set-current {current}uA", shell=True)
        time.sleep(10e-3)

        value = self.read_phys_ch_value(1)
        subprocess.call("lradc-set-current off", shell=True)

        return value

    def read_phys_ch_value(self, channel):
        values = []
        for _ in range(self.N_SAMPLES):
            with open(f"/sys/bus/iio/devices/iio:device0/in_voltage{channel}_raw", encoding="ascii") as file:
                v = int(file.read())
            values.append(v)
            # ~ time.sleep(20)
        return 1.0 * sum(values) / len(values)
