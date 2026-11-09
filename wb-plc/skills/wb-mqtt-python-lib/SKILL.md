---
name: wb-mqtt-python-lib
description: "Writing Python services for Wiren Board on wb-mqtt-python-lib (import wb_mqtt_lib, deb python3-wb-mqtt-lib) — asyncio Client, own devices and controls published by the WB MQTT convention, reading and commanding devices of other drivers, on_value / on_command handlers, reconnect, background tasks, raw topics outside the convention. Use when user writes, reviews or ports a Python daemon or integration that publishes devices to MQTT on a WB controller, mentions wb_mqtt_lib / wb-mqtt-python-lib / python3-wb-mqtt-lib, or wants to replace paho, aiomqtt or wb_common MQTT code in a WB Python service. NOT for wb-rules JS automation (wb-rules), NOT for C++/Go daemons or general Debian packaging (wb-dev)."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# wb-mqtt-python-lib — Python services on the WB MQTT library

Asyncio library for Wiren Board Python services. It holds one MQTT connection, publishes the service's devices by the [WB MQTT convention](https://github.com/wirenboard/conventions), reads devices of other drivers and reconnects on its own. Python 3.13 and Debian trixie only, built on aiomqtt 2.x.

Canonical docs are the library README (Russian, about 700 lines), as plain Markdown at <https://raw.githubusercontent.com/wirenboard/wb-mqtt-python-lib/main/README.md>. This skill holds the rules and behaviour a service gets wrong without reading it. Signatures, `create_control` arguments, the value per control type, the full handler and error tables are in the README — fetch it and read the section the task needs.

## Quick Start

```python
import asyncio
import contextlib
import signal
from typing import Any

from wb_mqtt_lib import BrokerDisconnectedError, Client, Control, ControlType


async def relay_command(control: Control, value: Any) -> None:
    # Drive the hardware here. The library does not change the value by a command
    await control.set_value(value)


async def run() -> None:
    async with Client(driver="wb-mqtt-example") as client:  # waits for the broker
        try:
            device = await client.create_device("example", title={"en": "Example", "ru": "Пример"})
            relay = await device.create_control("relay", control_type=ControlType.SWITCH, value=False)
            relay.on_command(relay_command)
            await asyncio.Future()  # works until SIGTERM cancels the task
        finally:
            with contextlib.suppress(BrokerDisconnectedError):
                await client.remove_driver_devices()  # devices outlive close() otherwise


async def main() -> None:
    # Without a SIGTERM handler systemd kills Python before finally runs
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signal_number, task.cancel)
    with contextlib.suppress(asyncio.CancelledError):
        await run()


asyncio.run(main())
```

## Hard rules — never violate without explicit user OK

- **One driver name — one client.** A client treats every device with its driver name as its own. `create_device` erases leftovers of that driver and `remove_driver_devices()` deletes all of them, so a dev copy of a service started against a controller under the production driver name wipes the live service's devices.
- **`create_device(..., force=True)` erases whatever sits under the name, devices of other drivers included.** Use it only when the user confirmed the name is to be taken over (driver renamed, an old version left a device without a driver).
- **Don't write a value topic of your own control through `client.raw`.** The object won't see it and keeps the old value. Change own devices through `Control` / `Device` objects. Commands to `/on` through `raw` are fine.

## Connecting the library to a service

The library ships as the deb package `python3-wb-mqtt-lib`, built from `main` into the unstable channel of the WB repo. Versions are alpha for now (`X.Y.Z~alphaN`), the API may change between them.

```
# debian/control of the service. Add to Build-Depends too if the tests import the library
Depends: ${python3:Depends}, ${misc:Depends}, python3-wb-mqtt-lib (>= <version>)
```

```python
from wb_mqtt_lib import Client, ControlType
```

## Concept map

| Task | wb_mqtt_lib | wb-rules analogue |
|---|---|---|
| Publish own device | `await client.create_device(name, title=...)` + `await device.create_control(name, control_type=..., value=...)` | `defineVirtualDevice` |
| Change own value | `await control.set_value(v)` | `dev["d/c"] = v` |
| React to a user command | `control.on_command(handler)`, handler calls `set_value` itself | the engine applies `/on` of a virtual control itself |
| Read a device of another driver | `control = await client.get_control("wb-mr6c_10/K1")`, `control.value` | `dev["wb-mr6c_10/K1"]` |
| Command to another driver | `await control.set_value(True)` → goes to `/on` | `dev["wb-mr6c_10/K1"] = true` |
| React to changes | `control.on_value(handler)` / `device.on_control_value(handler)` | `whenChanged` |
| Wait for a reply | `await asyncio.gather(c.wait_value(True, timeout=5), c.set_value(True))` | — |
| Periodic or long work | `client.start_task(coroutine)` | `setInterval`, `cron` |
| Topics outside the convention | `client.raw.subscribe / read / publish / unsubscribe` | `trackMqtt`, `publish` |
| Clean up on exit | `await client.remove_driver_devices()` | — |

Full tables are in the README sections «Клиент», «Свои устройства», «Поля объектов», «Обработчики событий», «Работа с MQTT вне конвенции» and «Ошибки».

## Behaviour to rely on

- **`set_value` of an own control publishes to MQTT on every call, also the same value, and `on_value` then gets `value == previous`.** A handler that needs only changes compares `value` with `previous`.
- **`on_value` of a foreign control fires on every value its driver publishes, a repeated one too.** Only the same value resent by the broker after a reconnect is no event.
- **A command does not change the value.** `on_command` gets the parsed value, the handler validates it (another service may send a number out of range) and calls `set_value`. A command with no handler assigned at that moment is lost. A retained message in `/on` is erased, not executed.
- **Handlers fire at assignment with the current state.** `on_value` gets the current value with `previous=None`, `on_added` fires if the object exists. No separate initial read is needed. `previous is None` skips the first call — except `pushbutton`, which has no value and always `previous=None`.
- **Every handler has its own queue.** Events come in order, the next call starts after the previous returns. Long work goes to `client.start_task(...)`, otherwise events pile up. A slow handler may see `control.value` newer than its `value` argument.
- **Handlers outlive `remove()` and a vanished control** and work again when it reappears. Declare a handler once at module or class level. A function defined inside a function that runs per device is a new object every time and stacks up duplicates.
- **Objects are by name.** `get_control` returns an object even if the control does not exist yet (`exists` is False, `on_added` fires later).
- **Without the broker link** own changes and retained `raw` publications raise nothing, the library keeps the last payload of each topic and publishes it after reconnect. Calls that need the broker (`create_device`, `get_control`, `remove_driver_devices`), commands to other drivers, `pushbutton` presses and non-retained `raw.publish` raise `BrokerDisconnectedError` at once.
- **Errors of a control.** On a failed read call `set_error(ControlErrorFlags.READ)` and leave the value. The next `set_value` clears `READ` itself.
- **`close()` leaves own devices in the broker.** Call `remove_driver_devices()` before it if they must disappear.

## Pitfalls

- **`async with Client(...)` waits for the broker forever.** Bound it with `await asyncio.wait_for(client.connect(), timeout=30)`. A rejected login on the first connect raises `LoginRejectedError` and the client stops trying.
- **The broker must speak MQTT 5.** Besides the default controller socket, `broker_url` takes `unix:///path`, `tcp://host:port` and `ws://host:port/path`, none of them encrypted.
- **Deprecated control types (`temperature`, `voltage`) can't be created.** Use `ControlType.VALUE` with `units`. Foreign controls of such types read as `value` with the convention units.
- **`precision` rounds what goes out and what `control.value` holds** — 21.54 with `precision=0.1` becomes 21.5 for everyone.
- **`set_value(None)` erases the value.** An empty string is no valid `text` value.
- **No MQTT-RPC, persistent storage, Last Will or Home Assistant discovery** in the library yet.

## What the agent does NOT do

- **Re-implement the WB convention on paho or aiomqtt next to the library** (own `/meta` JSON, own `/on` subscriptions, own retained cleanup). If the library lacks something, say so and use `client.raw` deliberately.
- **Call `set_value` of a control from its own `on_value`** — the handler calls itself forever.
- **Promise bullseye support.** aiomqtt 2.x is not in bullseye, the library runs on trixie only.

## When to ask the user

- Porting an existing service changes its driver or device names — the old devices stay in the broker until removed, ask whether to clean them with `force=True` or by hand.
- Whether the service's devices should disappear on stop (`remove_driver_devices()` in `finally`) or stay with their last values.
- The task needs MQTT-RPC, persistent storage or Last Will — build it on `client.raw` in the service or wait for the library.
- The service must also run on bullseye controllers.

## Documentation

- Library repo, README and design notes in `docs/dev-note-arc42.md`: <https://github.com/wirenboard/wb-mqtt-python-lib>
- WB MQTT convention: <https://github.com/wirenboard/conventions>
- Writing and packaging WB daemons in general: the `wb-dev` skill
