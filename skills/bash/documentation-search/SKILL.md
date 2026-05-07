---
name: documentation-search
description: Searching Wiren Board documentation — wiki, GitHub, web search. Source order and strategies.
allowed-tools: Bash Read WebFetch WebSearch
---

# documentation-search

Searching Wiren Board documentation. **First check whether the answer is on the controller** (`/usr/share/wb-mqtt-serial/templates/`, `dpkg -l`, RPC `device/LoadConfig`, local file) — on the hardware, the documentation matches the installed firmware; the internet may have docs for a different version.

## Order: external search → specific URLs → fallback

### 1. WebSearch with `site:` — main path

**Search via Google/Bing works on the WB wiki better than the built-in `Special:Search`** (that one often misses Russian queries). Use with a `site:` filter:

```
WebSearch 'site:wiki.wirenboard.com <query>'
WebSearch 'site:github.com/wirenboard <query>'
```

Take the URL from the top of the result — then `WebFetch <URL>` reads the page. One `WebSearch` usually gives a good lead; if nothing turned up — reformulate (synonyms, English), but **don't spend more than 2-3 calls** on a single topic.

Examples:
- `WebSearch 'site:wiki.wirenboard.com WB-MR6C broadcast group of channels'`
- `WebSearch 'site:wiki.wirenboard.com modbus relay management'`
- `WebSearch 'site:github.com/wirenboard/wb-rules defineRule cron'`

### 2. WebFetch a specific page — when the URL is known in advance

Direct navigation is faster and doesn't burn the search quota:

```
WebFetch https://wiki.wirenboard.com/wiki/<Page>
```

**The correct domain is `wiki.wirenboard.com`, not `wirenboard.com/wiki`.** The latter redirects (HTTP 301) and burns one WebFetch for nothing. Names are `Snake_Case` / `CamelCase`, spaces → `_`.

Common pages:
- A specific module: `https://wiki.wirenboard.com/wiki/WB-MR6C` (or `WB-MR6C_v.2_Modbus_Relay_Modules`, `WB-MR6C_v.3_...`).
- A topic: `https://wiki.wirenboard.com/wiki/Wb-rules`, `https://wiki.wirenboard.com/wiki/Modbus`.
- Lists/indices: `https://wiki.wirenboard.com/wiki/Service:RecentChanges`.
- Firmware changelog: `https://wiki.wirenboard.com/wiki/Firmware_Changelog`.

### 3. GitHub — sources, templates, READMEs

```
WebFetch https://github.com/wirenboard/<repo>/blob/main/README.md
```

For **raw content** (without HTML wrapping) → `raw.githubusercontent.com`:

```
WebFetch https://raw.githubusercontent.com/wirenboard/wb-rules/master/README.md
```

File names in `templates/<repo>` are unpredictable (often `config-<lowercased-id>.json` with suffixes `-v2`, `-nc`, etc.) — **don't guess**. List files via the GitHub API:

```bash
curl -s 'https://api.github.com/repos/wirenboard/wb-mqtt-serial/contents/templates' | jq -r '.[].name' | grep -i mr6c
```

Or, if `gh` is available:

```bash
gh api repos/wirenboard/wb-mqtt-serial/contents/templates --jq '.[].name'
```

Pages like `https://github.com/.../tree/main/<dir>` are JS SPAs, `WebFetch` returns near-empty markdown without a listing. Don't use.

## When the answer isn't in public docs

A real case from this check: there's no consolidated "how to make a broadcast command for all WB-MR6C" in public docs — it's assembled from `Modbus.md` (broadcast = address 0) + `Relay_Module_Modbus_Management` (registers 100-121 for on/off/toggle). If there's no single ready-made page on the topic — assemble the answer from 2-3 pages and explicitly tell the user that there's no consolidated guide and you assembled it yourself.

## Pitfalls

- **The `wirenboard.com/wiki/...` domain 301-redirects** to `wiki.wirenboard.com/wiki/...`. Any `WebFetch` to the old domain is a wasted call. The master skill `wiren-board` also uses the correct domain.
- **`Special:Search` on the WB wiki is weaker than Google** for Russian queries. Don't use as the primary search.
- **`github.com/.../tree/...` pages** are JS SPAs, not parseable by `WebFetch`. Use the GitHub API or `raw.githubusercontent.com` for individual files.
- **`raw.githubusercontent.com/<repo>/main/<path>`** — branch may be called `master`, not `main`. If 404 — try `master`.
- **wb-mqtt-serial templates** are easier to pull from the controller (`/usr/share/wb-mqtt-serial/templates/`) than from the repo — on the hardware the version matches the installed firmware.
- **WebSearch limit** — heuristically capped at 2-3 calls per topic; if nothing was found — the user must clarify the question or supply a direct URL.
