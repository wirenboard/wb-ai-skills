#! /usr/bin/python3
# pylint: disable=invalid-name

import argparse
import json
import sys

from wb_common.mqtt_client import DEFAULT_BROKER_URL, MQTTClient

from mqttrpc.client import (  # pylint: disable=redefined-builtin
    TimeoutError,
    TMQTTRPCClient,
)


def main():
    parser = argparse.ArgumentParser(
        description="Sample RPC client", add_help=True, formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "-b",
        "--broker",
        dest="broker_url",
        type=str,
        help="MQTT broker url",
        default=DEFAULT_BROKER_URL,
    )
    parser.add_argument("-d", "--driver", dest="driver", type=str, help="Driver name", required=True)
    parser.add_argument("-s", "--service", dest="service", type=str, help="Service name", required=True)
    parser.add_argument("-m", "--method", dest="method", type=str, help="Method name", required=True)
    parser.add_argument("-a", "--args", dest="args", type=json.loads, help="Method arguments", default={})
    parser.add_argument("-t", "--timeout", dest="timeout", type=int, help="Timeout in seconds", default=10)
    args = parser.parse_args()

    try:
        mqtt_client = MQTTClient("mqtt-rpc-client", args.broker_url)
        rpc_client = TMQTTRPCClient(mqtt_client)
        mqtt_client.on_message = rpc_client.on_mqtt_message
        mqtt_client.start()

        resp = rpc_client.call(args.driver, args.service, args.method, args.args, args.timeout)
        print(json.dumps(resp))
    except TimeoutError:
        print("Request timed out")
        sys.exit(124)
    except Exception as e:  # pylint: disable=broad-except
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        mqtt_client.stop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
