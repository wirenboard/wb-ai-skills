import os
import time


class Beeper:
    PWM_DIR_TEMPLATE = "/sys/class/pwm/pwmchip0/"

    def __init__(self, pwm_num):
        self.pwm_num = pwm_num
        self.pwm_dir = os.path.join(self.PWM_DIR_TEMPLATE, f"pwm{pwm_num}")

    def set(self, enabled):
        with open(os.path.join(self.pwm_dir, "enable"), mode="w", encoding="ascii") as file:
            file.write(("1" if enabled else "0") + "\n")

    def setup(self, period=250000, duty_cycle=125000):
        if not os.path.exists(self.pwm_dir):
            with open(os.path.join(self.PWM_DIR_TEMPLATE, "export"), mode="w", encoding="ascii") as file:
                file.write(f"{self.pwm_num}\n")
        with open(os.path.join(self.pwm_dir, "period"), mode="w", encoding="ascii") as file:
            file.write(f"{period}\n")
        with open(os.path.join(self.pwm_dir, "duty_cycle"), mode="w", encoding="ascii") as file:
            file.write(f"{duty_cycle}\n")
        self.set(0)

    def beep(self, duration, repeat=1):
        try:  # To prevent from stucking in '1' state
            for i in range(repeat):
                if i != 0:
                    time.sleep(duration)
                self.set(1)
                time.sleep(duration)
                self.set(0)
        finally:
            self.set(0)

    def test(self):
        self.beep(0.1, 3)


# Initiallizing beeper to call directly from imported module
# example: import beeper; beeper.beep(1, 2)
_beeper = Beeper(os.environ["WB_PWM_BUZZER"])
_beeper.setup()

setup = _beeper.setup
test = _beeper.test
beep = _beeper.beep
