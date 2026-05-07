---
name: wb-history
description: Data history and statistics from WB controllers via MCP — wb_history (points + min/max/avg from wb-mqtt-db).
allowed-tools: Bash Read WebFetch
---

# history (MCP)

Data history from Wiren Board controllers. The `wb-mqtt-db` service logs MQTT channels into SQLite. The `wb_history` MCP tool encapsulates the `db_logger/history/get_values` RPC.

## Tool routing

| Intent | Tool |
|--------|------|
| Points per channel for a period | `wb_history` (sn, channels — array of pairs, time-range, min_interval, limit) |
| **Chart** | `wb_history_chart` — by default returns inline Mermaid `xychart-beta` (line, single Y-axis); switch to `format="svg"` (or pass `outputPath`) for Vega-Lite SVG with bar/area/point/histogram/heatmap/boxplot, dual Y-axis, normalization |
| min/max/avg for a period | aggregate received `min`/`max`/`value` of buckets locally |
| List of devices | `wb_mqtt_devices` |
| List of device controls | `wb_mqtt_controls` |
| Is wb-mqtt-db alive | `wb_failed` (failed?), `wb_logs unit=wb-mqtt-db` |
| Package check | `wb_ssh_exec` `dpkg -l wb-mqtt-db; systemctl is-active wb-mqtt-db` |

## Step 1 — find channels

**Never guess names.** RPC accepts `[device_id, control_name]` pairs:

- `wb_mqtt_devices sn=<SN>` — all devices.
- `wb_mqtt_controls sn=<SN> device=<device_id>` — channels of a device.

Names often contain spaces: `CPU Temperature`, `Board Temperature` — use verbatim.

## Step 2 — request data (multi-channel in one call)

```
wb_history sn=<SN> channels=[["hwmon","CPU Temperature"],["hwmon","Board Temperature"],["wb-mr6c_2","K1"]] from=<unix_ts> to=<unix_ts> min_interval=0 limit=200
```

`channels` is an **array of pairs**: request all channels of interest in one RPC at once. `limit` is applied per-channel (not total). It's both faster and more convenient for building comparison charts.

Period parameters (timestamp, seconds):

| Period | from |
|--------|------|
| Last hour | `now - 3600` |
| Last day | `now - 86400` |
| Last week | `now - 604800` |
| Last month | `now - 2592000` |

## Decimation and response format

| Range | min_interval | limit |
|-------|--------------|-------|
| ≤ 1 hour | 0 | 200 |
| ≤ 24 hours | 60 | 500 |
| > 24 hours | 600 | 1000 |

Each point is a **bucket**, not a single measurement. Fields: `t` (bucket start timestamp), `value` (smoothed average), `min`, `max`. Even with `min_interval=0` the server aggregates ~120 sec — so 30 points per hour is normal.

To find **spikes and peaks**, look at `max` (or `max - min` within the bucket), not at `value` of neighboring buckets: `value` is smoothed and will miss transient peaks of 5-10 units lasting <1 minute.

## Visualization: different units on one chart

This is **not pointless** — it just needs to be drawn correctly. Standard strategies:

| Number of different units | What to do |
|---------------------------|-----------|
| 1 (e.g. two temperatures in `°C`) | One Y scale, both lines on it |
| 2 (`°C` + `%`) | Dual Y scale: left axis for one unit, right for the other |
| 3+ | Normalize each channel into `[0;1]` (by its own `min..max`), with original ranges in the legend. Alternative: faceted (subplot per unit) |

Render options — use `wb_history_chart` for both:

- **Default — Mermaid `xychart-beta`.** Inline in chat. Linear, single Y-axis (Mermaid limitation), downsampled to ~30 points for readability. **Start with this.**
  ```
  wb_history_chart sn=<SN> channels=[["hwmon","CPU Temperature"]] period=24h title="CPU temp, last 24h" ylabel="°C"
  # → returns {format:"mermaid", mermaid: "xychart-beta\n  title ...", totalPoints, ...}
  # the `mermaid` string can be wrapped in ```mermaid ... ``` and rendered inline in Claude Code chat
  ```

- **Vega-Lite SVG** — only when the user asks for a richer chart, a non-line type, dual Y-axis, or wants to save to a file. Pass `format="svg"` or set `outputPath`. Supports `line`, `bar`, `area`, `point`, `histogram`, `heatmap`, `boxplot`. Axis logic:
   - 1 unit → one Y scale.
   - 2 units → dual axis (`resolve.scale.y: independent`, left+right).
   - 3+ units → normalization to [0;1], original ranges in legend.

  ```
  wb_history_chart sn=<SN> channels=[["hwmon","CPU Temperature"],["hwmon","Board Temperature"]] period=1h format=svg chartType=line title="Temps last hour"
  # → returns {format:"svg", svg, svgBytes, totalPoints, ...}; SVG inline (if <200 KB)
  wb_history_chart sn=<SN> channels=[...] period=24h format=svg chartType=heatmap outputPath=/tmp/cpu.svg
  # → writes to file, response only contains {ok, format:"svg", outputPath, ...}
  ```

  **When to use `outputPath`:** if a day/week passed across 3+ channels, the SVG can be >200 KB — the MCP server will refuse the inline response. Save to file and give the user the path.

- **Conversation flow.** Render Mermaid first; only when the user asks for "pretty"/"save as SVG"/"heatmap"/"two units side-by-side" — switch to `format="svg"`. Don't dump SVG by default.

Mermaid format reference (rendered by Claude Code automatically when wrapped in ```mermaid```):
  ```mermaid
  xychart-beta
      title "CPU Temperature, °C"
      x-axis [16:55, 17:10, 17:25, 17:40, 17:55]
      y-axis "°C" 65 --> 85
      line [69.9, 71.1, 75.3, 76.0, 70.5]
  ```

- **Python + matplotlib** or external UI — if a different style/format is needed. Pass the JSON result of `wb_history`, process locally.

For a bash summary, min/max/avg + ASCII sparkline is enough.

## Checking wb-mqtt-db

```
wb_ssh_exec sn=<SN> cmd='systemctl is-active wb-mqtt-db'
```

If `inactive` — **don't install yourself**, report to the user and coordinate: installation goes through `/wb-software-install` (we recommend not native via apt, but leaving wb-mqtt-db as a stock package — it's in the WB repo).

If `wb_history` returns empty — verify that:
- `wb-mqtt-db` is alive (`wb_failed`, `wb_logs unit=wb-mqtt-db`).
- The channel isn't excluded in `/etc/wb-mqtt-db.conf` (read via `wb_read_file`).
- `wb-mqtt-db` wasn't installed recently — no past data.

## Gotchas

- Don't truncate channel names: `"CPU"` ≠ `"CPU Temperature"`.
- If `wb-mqtt-db` was installed recently — no past data.
- `value` is bucket-smoothed, `min`/`max` show real peaks — for spike search look at `max`.
- `limit` is per-channel — with 5 channels and `limit:200` up to 1000 points returned.
- Large ranges without `min_interval` flood the response — specify decimation.
