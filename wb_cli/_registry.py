"""Plugin registry — maps command names to (module_path, help_text).

Regenerate via ``make registry`` (runs ``python3 -m wb_cli._gen_registry``).
"""

# {name: (module_path, help_text)}
BUILTIN_PLUGINS: dict = {
    "audit": ("wb_cli.commands.audit", "quick health check (failed units, identity)"),
    "cloud": ("wb_cli.commands.cloud", "report whether the Wiren Board cloud agent is up"),
    "confed": ("wb_cli.commands.confed", "read and write service config files through wb-mqtt-confed"),
    "dev": ("wb_cli.commands.dev", "list controls (all / one device) and read or write a single one"),
    "history": ("wb_cli.commands.history", "time-series history of a control's values"),
    "info": ("wb_cli.commands.info", "what this controller is: serial, firmware, board, uptime"),
    "job": ("wb_cli.commands.job_cmd", "run long-running commands in the background, watch them, fetch logs"),
    "modbus": (
        "wb_cli.commands.modbus._plugin",
        "RS-485 / Modbus: scan, probe, templates, device-info, ports, add-devices",
    ),
    "modbus-fw": (
        "wb_cli.commands.modbus_fw",
        "firmware update of Modbus devices (check, update, restore, watch)",
    ),
    "mqtt": ("wb_cli.commands.mqtt_cmd", "raw MQTT: read retained, write, list topics"),
    "plugins": ("wb_cli.commands.plugins", "list every plugin this wb-cli build knows about"),
    "rules": (
        "wb_cli.commands.rules",
        "manage wb-rules automation scripts (list / read / save / disable / delete)",
    ),
    "serial-debug": (
        "wb_cli.commands.serial_debug",
        "turn on RS-485 debug logging, capture for N seconds, then restore",
    ),
    "snapshot": ("wb_cli.commands.snapshot", "save controller state to disk and compare snapshots later"),
}
