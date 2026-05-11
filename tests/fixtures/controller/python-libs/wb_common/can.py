# coding: utf-8
from __future__ import print_function

import binascii
import subprocess
import threading


class CanPort:
    def __init__(self, iface="can0", bitrate=115200):
        self.iface = iface
        self.bitrate = bitrate

        self.receive_ready = threading.Event()
        self.receive_thread = None

        self._frames = None

    def setup(self):
        # re-initialize iface
        subprocess.call(f"ifconfig {self.iface} down", shell=True)
        subprocess.call(f"ip link set {self.iface} type can bitrate 125000", shell=True)
        subprocess.call(f"ifconfig {self.iface} up", shell=True)

    def send(self, addr, data):
        addr_str = hex(addr)[2:][:3].zfill(3)
        data_str = binascii.hexlify(data)
        subprocess.call(f"cansend {self.iface} {addr_str}#{data_str}", shell=True)

    def receive(self, timeout_ms=1000):

        try:
            result = subprocess.run(
                f"candump {self.iface} -s0 -L -T {timeout_ms}",
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError:
            raise RuntimeError("candump failed")  # pylint:disable=raise-missing-from

        stdout_str = result.stdout.strip()
        frames = []
        for line in stdout_str.split("\n"):
            line = line.strip()
            if line:
                parts = line.split(" ")
                if len(parts) == 3:
                    packet = parts[2]
                    addr_str, data_str = packet.split("#")
                    addr = int(addr_str, 16)
                    data = binascii.unhexlify(data_str)
                    frames.append((addr, data))
        return frames

    def _receiver_work(self, timeout_ms):
        frames = self.receive(timeout_ms)
        self._frames = frames

    def start_receive(self, timeout_ms=1000):
        self.receive_thread = threading.Thread(target=self._receiver_work, args=(timeout_ms,))
        self.receive_thread.start()

    def get_received_data(self):
        self.receive_thread.join()
        return self._frames
