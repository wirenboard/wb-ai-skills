import json
import threading

import paho.mqtt.client as mqtt
from jsonrpc.exceptions import JSONRPCException

# ~ from concurrent.futures import Future
from .protocol import MQTTRPC10Response

# ~ from concurrent.futures._base import TimeoutError


class TimeoutError(Exception):  # pylint: disable=redefined-builtin
    pass


class MQTTRPCError(Exception):
    """Represents error raised by server"""

    def __init__(self, message, code, data):
        super().__init__(f"{message} [{code}]: {data}")
        self.rpc_message = message
        self.code = code
        self.data = data


class AsyncResult:
    def __init__(self):
        self._event = threading.Event()
        self._result = None
        self._exception = None

    def set_result(self, result):
        self._result = result
        self._event.set()

    def set_exception(self, exception):
        self._exception = exception
        self._event.set()

    def _get_result(self):
        if self._exception:
            raise self._exception
        return self._result

    def result(self, timeout=None):
        if self._event.wait(timeout):
            return self._get_result()
        raise TimeoutError()

    def exception(self, timeout=None):
        if self._event.wait(timeout):
            return self._exception
        raise TimeoutError()


class TMQTTRPCClient:
    def __init__(self, client):
        self.client = client
        self.counter = 0
        self.futures = {}
        self.subscribes = set()
        if isinstance(self.client._client_id, bytes):
            self.rpc_client_id = self.client._client_id.decode().replace("/", "_")
        else:
            self.rpc_client_id = str(self.client._client_id).replace("/", "_")

    def on_mqtt_message(  # pylint: disable=unused-argument, inconsistent-return-statements
        self, mosq, obj, msg
    ):
        """return True if the message was indeed an rpc call"""

        if not mqtt.topic_matches_sub(f"/rpc/v1/+/+/+/{self.rpc_client_id}/reply", msg.topic):
            return

        parts = msg.topic.split("/")
        driver_id = parts[3]
        service_id = parts[4]
        method_id = parts[5]

        json_str = msg.payload.decode("utf8")

        try:
            result = MQTTRPC10Response.from_json(json_str)
        except JSONRPCException as err:
            try:
                data = json.loads(json_str)
            except Exception:  # pylint: disable=broad-except
                data = None
            if isinstance(data, dict) and data.get("id") is not None:
                future = self.futures.pop(
                    (driver_id, service_id, method_id, data["id"]), None  # pylint: disable=protected-access
                )
                if future is not None:
                    future.set_exception(err)
            return True

        future = self.futures.pop(
            (driver_id, service_id, method_id, result._id), None  # pylint: disable=protected-access
        )
        if future is None:
            return True

        if result.error:
            future.set_exception(
                MQTTRPCError(
                    result.error["message"],
                    result.error["code"],
                    result.error["data"] if "data" in result.error else None,
                )
            )

        future.set_result(result.result)
        return True

    def call(self, driver, service, method, params, timeout=None):  # pylint: disable=too-many-arguments
        future = self.call_async(driver, service, method, params)

        try:
            result = future.result(1e100 if timeout is None else timeout)
        except TimeoutError as err:
            # delete callback
            self.futures.pop((driver, service, method, future.packet_id), None)
            raise err
        return result

    def call_async(
        self, driver, service, method, params, result_future=AsyncResult
    ):  # pylint: disable=too-many-arguments
        self.counter += 1
        payload = {"params": params, "id": self.counter}

        result = result_future()
        result.packet_id = self.counter  # pylint: disable=attribute-defined-outside-init
        self.futures[(driver, service, method, self.counter)] = result

        topic = f"/rpc/v1/{driver}/{service}/{method}/{self.rpc_client_id}"

        subscribe_key = (driver, service, method)
        if subscribe_key not in self.subscribes:
            self.subscribes.add(subscribe_key)
            self.client.subscribe(f"{topic}/reply")

        self.client.publish(topic, json.dumps(payload))

        return result
