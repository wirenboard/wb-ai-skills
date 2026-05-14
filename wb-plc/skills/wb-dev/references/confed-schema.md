# JSON editor (confed) — schema reference

The WB web UI has a **pre-installed JSON editor** (`wb-mqtt-confed` + `homeui`). Any service can get a configuration page in the web interface for free by dropping a JSON Schema file into `/etc/wb-mqtt-confed/schemas/`.

Wiki: <https://wiki.wirenboard.com/wiki/JSON-editor-Wirenboard-Implementation-Features>

## How it works

`wb-mqtt-confed` watches the schemas directory. When the user opens the web UI → "Device configurations", it renders each schema as a form. On save, it writes the config file and restarts the service.

**If the config file is plain JSON** — no conversion scripts needed, confed reads/writes it directly.
**If the config is a custom format** — provide `toJSON`/`fromJSON` converter scripts.

## Schema file structure

Place the file at `/etc/wb-mqtt-confed/schemas/my-service.schema.json`:

```jsonc
{
  "$schema": "http://json-schema.org/draft-04/schema#",
  "type": "object",
  "title": "My Service Configuration",
  "configFile": {
    "path": "/etc/my-service/config.json",
    "service": "my-service",
    "restartDelayMS": 2000
  },
  "properties": {
    "server_url": {
      "type": "string",
      "title": "Server URL",
      "propertyOrder": 1
    },
    "poll_interval": {
      "type": "integer",
      "title": "Poll interval (s)",
      "default": 30,
      "propertyOrder": 2
    },
    "enabled": {
      "type": "boolean",
      "title": "Enable service",
      "default": true,
      "_format": "checkbox",
      "propertyOrder": 3
    }
  }
}
```

## `configFile` parameters

| Parameter | Required | Description |
|---|---|---|
| `path` | yes | Path to the config file on the controller |
| `service` | no | Service name (or list) to restart after save |
| `toJSON` | no | Command: config file → JSON for homeui (stdin → stdout) |
| `fromJSON` | no | Command: JSON from homeui → config file (stdin → stdout) |
| `restartDelayMS` | no | Delay before service restart in ms |
| `validate` | no | Validate JSON against schema before writing (default: true) |
| `hide` | no | Hide from "Device configurations" page (for internal schemas) |
| `needReload` | no | Reload config from confed after save |

## WB-specific schema extensions

| Extension | Effect |
|---|---|
| `"_format": "checkbox"` | Boolean rendered as checkbox |
| `"_format": "wb-autocomplete"` | Text field with MQTT device autocomplete |
| `"_format": "edWb"` | Dropdown for integer/string via `enum_values` |
| `"headerTemplate"` on array items | Item label in collapsed array row |
| `"propertyOrder"` | Controls field ordering in the form |

## Installing the schema via deb

In your package's `debian/install` (or `debian/<pkg>.install`):

```
debian/my-service.schema.json  etc/wb-mqtt-confed/schemas/
```

After placing the schema file, restart confed to pick it up:

```bash
ssh root@<HOST> 'systemctl restart wb-mqtt-confed'
```
