"""Plugin registry — maps command names to (module_path, help_text).

Regenerate via ``make registry`` (runs ``python3 -m wb_cli._gen_registry``).
"""

# {name: (module_path, help_text)}
BUILTIN_PLUGINS: dict = {
    "audit": ("wb_cli.commands.audit", "quick system health check: failed units, disk, memory"),
    "cloud": ("wb_cli.commands.cloud", "Wiren Board cloud agent: link status and connection info"),
    "confed": ("wb_cli.commands.confed", "configuration editor: load and save service configs via confed"),
    "devices": (
        "wb_cli.commands.devices",
        "devices on the controller: list, controls, set values, inventory",
    ),
    "history": ("wb_cli.commands.history", "historical data: time-series values and Mermaid charts"),
    "info": ("wb_cli.commands.info", "controller identity: serial number, firmware, board revision, uptime"),
    "job": ("wb_cli.commands.job_cmd", "background tasks: run, status, tail, cancel, wait, list"),
    "modbus": (
        "wb_cli.commands.modbus._plugin",
        "RS-485 / Modbus: scan, probe, templates, device-info, ports, add-devices",
    ),
    "mqtt": ("wb_cli.commands.mqtt_cmd", "raw MQTT: read retained, write, list topics"),
    "plugins": ("wb_cli.commands.plugins", "list installed wb-cli plugins"),
    "rules": ("wb_cli.commands.rules", "automation rules / scenarios: list, load, save, disable, delete"),
    "serial-debug": (
        "wb_cli.commands.serial_debug",
        "RS-485 bus debug: enable debug logging, capture, then restore",
    ),
    "snapshot": (
        "wb_cli.commands.snapshot",
        "system state snapshots: save current state, diff against baseline",
    ),
}
