---
name: history
description: Historical data and statistics from WB controllers — queries to wb-mqtt-db via RPC.
allowed-tools: Bash Read WebFetch
---

# history

Historical data from Wiren Board controllers. The `wb-mqtt-db` service logs MQTT channels into SQLite.

The skill fetches data and computes simple statistics. Chart rendering is a separate task (see "Visualization" below).

## Step 1 — find channels

**Never guess names.** RPC `get_values` accepts pairs `[device_id, control_name]`. To get both:

```bash
# All retained channels in one pass (fast, see the full device-control table at once).
# IMPORTANT: -F '%t\t%p' — TAB as separator. Control names often contain spaces
# (CPU Temperature, Input 0, Input 0 counter), and -v would split by the first space,
# truncating the control name. With TAB this doesn't happen.
ssh root@<HOST> "mosquitto_sub -F '%t\\t%p' -t '/devices/+/controls/+' -W 3 -C 500" \
  | awk -F'\t' '{ split($1, a, "/"); print a[3] "\t" a[5] }' | sort -u
```

If you only need device names without controls — `mosquitto_sub -t '/devices/+/meta/name' -C 50 -W 3` (faster, less data, but **device_id** there isn't equal to `meta/name` — `meta/name` is a human description; the actual device_id is taken from the second field of the topic `/devices/<device_id>/...`).

Names often have spaces: `CPU Temperature`, `Board Temperature`, `Input 0`, `Input 0 counter` — use them verbatim. Don't guess — go and read via `mosquitto_sub` with `-F '%t\t%p'`.

## Step 2 — query data via RPC

`$(...)` in `ssh ... bash -c '...'` is escaped on the host, not on the controller — a typical source of `Parse error -32700`. The simple and reliable path is a heredoc on the remote side:

```bash
ssh root@<HOST> 'bash -s' <<'EOF'
ID=$(cat /dev/urandom | tr -dc a-z0-9 | head -c8)
SINCE=$(date -d "1 hour ago" +%s)
mosquitto_sub -t "/rpc/v1/db_logger/history/get_values/${ID}/reply" -C 1 -W 30 &
SUB_PID=$!
sleep 0.3
mosquitto_pub -t "/rpc/v1/db_logger/history/get_values/${ID}" -m '{
  "id": "'"${ID}"'",
  "params": {
    "channels": [
      ["hwmon", "CPU Temperature"],
      ["hwmon", "Board Temperature"],
      ["wb-mr6c_2", "K1"]
    ],
    "timestamp": {"gt": '"${SINCE}"'},
    "min_interval": 0,
    "limit": 200
  }
}'
wait $SUB_PID
EOF
```

`<<'EOF'` (with single quotes) — required so that `$ID`, `$SINCE`, `$(...)` are expanded on the controller, not locally. The `channels` list is **an array of pairs**: query all channels of interest in one RPC call (`limit` applies per-channel, not in total). This is both faster (single round-trip) and more convenient for building comparative charts.

Parameter `timestamp.gt` — UNIX timestamp (seconds):
- For an hour: `$(date -d "1 hour ago" +%s)`
- For a day: `$(date -d "24 hours ago" +%s)`
- For a week: `$(date -d "7 days ago" +%s)`
- For a month: `$(date -d "30 days ago" +%s)`

## Decimation and response format

| Range | min_interval | limit |
|----------|-------------|-------|
| ≤ 1 hour | 0 | 200 |
| ≤ 24 hours | 60 | 500 |
| > 24 hours | 600 | 1000 |

Each response point is a **bucket**, not a single measurement. Fields: `t` (bucket start timestamp), `value` (smoothed average), `min`, `max`. Even with `min_interval=0` the server groups points into its own internal buckets (~120 s on the standard wb-mqtt-db config) — so 30 "points" per hour is normal.

To find **spikes and peaks**, look at `max` (or `max - min` within a bucket), not at `value` of neighboring points: `value` is smoothed and will miss transient spikes of 5-10 °C lasting <1 minute.

## Verifying wb-mqtt-db

```bash
ssh root@<HOST> 'systemctl is-active wb-mqtt-db'
```
If `inactive` — **don't install it yourself**, report to the user and agree: the package needs to be installed via `apt install wb-mqtt-db`, but this changes controller state and should go through the `/software-install` skill (with disk space recon and a background job).

## Visualization: different units on one chart

It's **not pointless** — just needs to be drawn correctly. Standard strategies:

| How many distinct units | What to do |
|----------------------|-----------|
| 1 (e.g. two temperatures in `°C`) | One Y axis, both lines on it |
| 2 (e.g. `°C` + `%`) | Dual Y axis: left axis for one unit, right for the other. In Vega-Lite — `resolve: {scale: {y: 'independent'}}` with `axis.orient` `left`/`right` on two layers |
| 3+ | Normalize each channel to `[0;1]` (by its `min..max` over the period), draw in shared coordinates, original ranges in the legend. Alternative: faceted plot (subplot per unit) |

Rendering from bash is laborious. Options:
- **Mermaid `xychart-beta`** (since v10) — renders directly in Markdown (Claude Code, GitHub, any Markdown viewer with Mermaid). Free, no external deps. **Single Y axis only** — fits series with the same unit or a single series. Bar/line marks. **Doesn't fit** for comparing two different units.
  ```mermaid
  xychart-beta
      title "CPU Temperature, °C, last hour"
      x-axis [16:55, 17:10, 17:25, 17:40, 17:55]
      y-axis "°C" 65 --> 85
      line [69.9, 71.1, 75.3, 76.0, 70.5]
  ```
- **Python + matplotlib** on the host (don't load the controller): get JSON via RPC → `json.load` → `ax.twinx()` for the second axis. Full control over two axes, normalization, faceted plots.
- **Vega-Lite / any UI with built-in rendering** — if the user has an external tool, hand it the RPC JSON result, it'll draw with the desired axis logic.

For a summary in a bash session without graphic output, min/max/avg + ASCII sparkline is usually enough:

```bash
# unicode sparkline for the value series (input — list of numbers separated by spaces):
echo "$values" | python3 -c 'import sys; v=[float(x) for x in sys.stdin.read().split()]; lo,hi=min(v),max(v); s=" ▁▂▃▄▅▆▇█"; print("".join(s[1+int((x-lo)/(hi-lo)*(len(s)-2))] if hi>lo else s[1] for x in v))'
```

## Pitfalls

- Don't truncate channel names: `"CPU"` ≠ `"CPU Temperature"`.
- If `wb-mqtt-db` was just installed — there's no past data.
- `value` is bucket-smoothed, `min`/`max` show real peaks — to find spikes, always look at `max`.
- `limit` applies per-channel — with 5 channels and `limit:200` you get up to 1000 points (200×5).
