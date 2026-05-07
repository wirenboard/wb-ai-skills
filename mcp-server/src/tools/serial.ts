import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { type Ctx, resolveController, text, err, SN } from '../helpers.ts'
import { shellQuote } from '../lib/shell.ts'

type TplEntry = { type: string; 'mqtt-id': string; name: string; deprecated?: boolean; protocol?: string; hw?: Array<{ signature?: string }> }

export function registerSerialTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_modbus_templates_list', {
    description: 'wb-mqtt-serial Modbus device templates. Without filter — only a per-group summary (the full list of 250+ templates does not fit in chat). With filter — a flat list of matched entries: {type, mqtt-id, name, deprecated, group}. Case-insensitive search over type/mqtt-id/name. Deprecated entries are hidden by default — pass includeDeprecated=true to see them.',
    inputSchema: z.object({
      sn: SN,
      includeDeprecated: z.boolean().optional().default(false).describe('Include deprecated templates'),
      filter: z.string().optional().describe('Substring filter over type/mqtt-id/name (case-insensitive). Without filter only a per-group summary is returned.'),
    }),
  }, async ({ sn, includeDeprecated, filter }) => {
    const c = resolveController(ctx, sn)
    const r = await ctx.ssh.mqttRpc(c, 'wb-mqtt-serial', 'config', 'Load', {}, 15) as { types?: Array<{ name: string; types: TplEntry[] }> }
    if (!filter) {
      const groups: Array<{ name: string; count: number; deprecated: number }> = []
      let total = 0, totalDeprecated = 0
      for (const g of r.types ?? []) {
        const all = g.types ?? []
        const dep = all.filter((t) => t.deprecated).length
        const visible = includeDeprecated ? all.length : all.length - dep
        groups.push({ name: g.name, count: visible, deprecated: dep })
        total += visible
        totalDeprecated += dep
      }
      return text({ total, totalDeprecated, groups, hint: 'Pass filter="…" to get a flat list of matched entries. Search is case-insensitive.' })
    }
    const f = filter.toLowerCase()
    const flat: Array<{ type: string; 'mqtt-id': string; name: string; deprecated: boolean; group: string }> = []
    for (const g of r.types ?? []) {
      for (const t of g.types ?? []) {
        if (!includeDeprecated && t.deprecated) continue
        if (!((t.type ?? '').toLowerCase().includes(f) || (t['mqtt-id'] ?? '').toLowerCase().includes(f) || (t.name ?? '').toLowerCase().includes(f))) continue
        flat.push({ type: t.type, 'mqtt-id': t['mqtt-id'], name: t.name, deprecated: !!t.deprecated, group: g.name })
      }
    }
    return text({ count: flat.length, templates: flat })
  })

  server.registerTool('wb_modbus_template', {
    description: 'Modbus device template from /usr/share/wb-mqtt-serial/templates/config-<mqtt-id>.json. Resolves device_type via RPC wb-mqtt-serial/config/Load to find mqtt-id, then reads the file. Case-insensitive lookup over type or mqtt-id. By default (`view="summary"`) returns a compact channel list; for full contents with registers use `view="full"`. Filters: `enabledOnly`, `channelFilter`.',
    inputSchema: z.object({
      sn: SN,
      device_type: z.string().describe('Device type (WB-MR6C, WB-MSW_v.4, WB-MR6C v.3) or mqtt-id (wb-mr6c). Case-insensitive.'),
      view: z.enum(['summary', 'full', 'channels-only', 'meta-only']).optional().default('summary').describe('summary (default): {meta, channels:[{name,enabled,type,units,readonly,group}]}. full: the entire template JSON. channels-only: only the channels array. meta-only: only the header without channels/parameters.'),
      enabledOnly: z.boolean().optional().default(false).describe('Only enabled channels. Default: all.'),
      channelFilter: z.string().optional().describe('Substring filter over channel names (case-insensitive).'),
    }),
  }, async ({ sn, device_type, view, enabledOnly, channelFilter }) => {
    const c = resolveController(ctx, sn)
    const r = await ctx.ssh.mqttRpc(c, 'wb-mqtt-serial', 'config', 'Load', {}, 15) as { types?: Array<{ types: TplEntry[] }> }
    const q = device_type.toLowerCase()
    let mqttId: string | undefined
    for (const g of r.types ?? []) {
      for (const t of g.types ?? []) {
        if ((t.type ?? '').toLowerCase() === q || (t['mqtt-id'] ?? '').toLowerCase() === q) { mqttId = t['mqtt-id']; break }
      }
      if (mqttId) break
    }
    if (!mqttId) return err(`device_type="${device_type}" not found in wb-mqtt-serial config/Load.types — try wb_modbus_templates_list filter="${device_type}"`)
    if (!/^[A-Za-z0-9._-]+$/.test(mqttId)) return err(`mqtt-id "${mqttId}" contains disallowed characters — refusing to read template file`)
    const path = `/usr/share/wb-mqtt-serial/templates/config-${mqttId}.json`
    const cat = await ctx.ssh.exec(c, `cat ${shellQuote(path)}`)
    if (cat.code !== 0) return err(`cat ${path}: ${cat.stderr.trim()}`)
    let tpl: any
    try { tpl = JSON.parse(cat.stdout) } catch { return err(`Failed to parse ${path}`) }
    const channels: any[] = (tpl.device?.channels ?? []) as any[]
    const cf = channelFilter?.toLowerCase()
    const filtered = channels.filter((ch: any) => {
      if (enabledOnly && ch.enabled === false) return false
      if (cf && !(ch.name ?? '').toLowerCase().includes(cf)) return false
      return true
    })
    if (view === 'full') {
      const out = { ...tpl, device: { ...tpl.device, channels: filtered } }
      return text(out)
    }
    if (view === 'channels-only') {
      return text({ count: filtered.length, channels: filtered })
    }
    if (view === 'meta-only') {
      const { device, ...rest } = tpl
      const { channels: _, parameters: __, ...deviceMeta } = device ?? {}
      return text({ ...rest, device: deviceMeta })
    }
    // summary (default): compact channel list + meta
    const compact = filtered.map((ch: any) => ({
      name: ch.name,
      enabled: ch.enabled !== false,
      type: ch.type,
      units: ch.units,
      readonly: ch.readonly === true,
      group: ch.group,
      ...(ch.format ? { format: ch.format } : {}),
    }))
    return text({
      title: tpl.title,
      device_type: tpl.device_type,
      'mqtt-id': tpl.device?.id,
      group: tpl.group,
      hw: tpl.hw,
      channelCount: { total: channels.length, returned: compact.length, enabled: channels.filter((c: any) => c.enabled !== false).length },
      channels: compact,
    })
  })

  server.registerTool('wb_modbus_device_info', {
    description: 'Firmware parameters of a specific Modbus device: fw version, model string, parameters (debounce, modes, mappings). RPC wb-mqtt-serial/device/LoadConfig. This is NOT the channel list — for channels and template use wb_modbus_template.',
    inputSchema: z.object({
      sn: SN,
      device_id: z.string().optional().describe('Device ID in MQTT (wb-mr6c_138). One is enough; the other parameters are not needed.'),
      path: z.string().optional().describe('Port (/dev/ttyRS485-1) — if without device_id'),
      slave_id: z.number().optional(),
      device_type: z.string().optional(),
      baud_rate: z.number().optional(),
      parity: z.string().optional(),
      data_bits: z.number().optional(),
      stop_bits: z.number().optional(),
    }),
  }, async ({ sn, device_id, ...rest }) => {
    const params: Record<string, unknown> = device_id ? { device_id } : rest
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'wb-mqtt-serial', 'device', 'LoadConfig', params, 10))
  })

  server.registerTool('wb_modbus_probe', {
    description: 'Check Modbus device availability on the bus (quick ping)',
    inputSchema: z.object({
      sn: SN,
      path: z.string().describe('Port (/dev/ttyRS485-1)'),
      slave_id: z.number(),
      baud_rate: z.number().optional().default(9600),
      parity: z.string().optional().default('N'),
      data_bits: z.number().optional().default(8),
      stop_bits: z.number().optional().default(2),
    }),
  }, async ({ sn, path, slave_id, baud_rate, parity, data_bits, stop_bits }) => {
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'wb-mqtt-serial', 'device', 'Probe', {
      path, slave_id, baud_rate, parity, data_bits, stop_bits, total_timeout: 10000,
    }, 15))
  })

  server.registerTool('wb_modbus_ports', {
    description: 'Parameters of all RS-485 ports (baud, parity, stop bits, timeouts)',
    inputSchema: z.object({ sn: SN }),
  }, async ({ sn }) => {
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'wb-mqtt-serial', 'ports', 'Load', {}, 5))
  })

  server.registerTool('wb_modbus_scan', {
    description: 'Bus scan via wb-device-manager. Default scan_type="extended" — Fast Modbus (finds WB and Onokom devices in seconds). scan_type="standard" — regular Modbus (slower, but sees third-party devices). If port is not specified, auto-detect all `/dev/ttyRS485-*`. If baud_rate is not specified, iterates 115200 and 9600. Returns the final `/wb-device-manager/state` with the `devices` array.',
    inputSchema: z.object({
      sn: SN,
      port: z.string().optional().describe('Port (/dev/ttyRS485-1). Empty — all RS-485 ports automatically.'),
      baud_rate: z.number().optional().describe('Baud rate. Empty — iterate 115200 and 9600.'),
      data_bits: z.number().optional().default(8),
      parity: z.string().optional().default('N'),
      stop_bits: z.number().optional().default(2),
      scan_type: z.enum(['extended', 'standard']).optional().default('extended').describe('extended — Fast Modbus (WB+Onokom), standard — regular Modbus (sees third-party)'),
      timeout: z.number().optional().default(180).describe('Total timeout for the WHOLE scan (sec, default 180). Per port×baud — up to timeout/(N×M) seconds.'),
    }),
  }, async ({ sn, port, baud_rate, data_bits, parity, stop_bits, scan_type, timeout }) => {
    const c = resolveController(ctx, sn)
    // Baud configs to iterate
    const configs = baud_rate != null
      ? [{ baud_rate, data_bits, parity, stop_bits }]
      : [
          { baud_rate: 115200, data_bits, parity, stop_bits },
          { baud_rate: 9600, data_bits, parity, stop_bits },
        ]
    // Port list
    let ports: string[]
    if (port) ports = [port]
    else {
      const r = await ctx.ssh.exec(c, 'ls /dev/ttyRS485-* 2>/dev/null', 5000)
      ports = r.stdout.trim().split('\n').filter(Boolean)
      if (!ports.length) return err('No `/dev/ttyRS485-*` ports found on the controller')
    }
    const readState = async (): Promise<{ scanning?: boolean; progress?: number; devices?: unknown[]; error?: string } | null> => {
      const raw = await ctx.ssh.mqttRead(c, '/wb-device-manager/state', 3)
      if (!raw) return null
      try { return JSON.parse(raw) } catch { return null }
    }
    const deadline = Date.now() + timeout * 1000
    let preserve = false  // first start resets results
    for (const p of ports) {
      for (const cfg of configs) {
        if (Date.now() > deadline) return err(`Timeout ${timeout}s exhausted, scan did not finish. Progress — wb_mqtt_read /wb-device-manager/state`)
        const params = { scan_type, preserve_old_results: preserve, port: { path: p, ...cfg } }
        // Start; retry if a previous one is still in progress
        for (let attempt = 0; attempt < 6; attempt++) {
          try {
            await ctx.ssh.mqttRpc(c, 'wb-device-manager', 'bus-scan', 'Start', params, 10)
            break
          } catch (e) {
            const msg = e instanceof Error ? e.message : String(e)
            if (msg.includes('already executing') && attempt < 5) {
              await new Promise((r) => setTimeout(r, 5000))
              continue
            }
            throw e
          }
        }
        preserve = true  // subsequent configs/ports add to what's already found
        // Polling: wait for scanning=false
        const portDeadline = Math.min(deadline, Date.now() + 90 * 1000)  // no more than 90s per config
        while (Date.now() < portDeadline) {
          await new Promise((r) => setTimeout(r, 2000))
          const state = await readState()
          if (state && state.scanning === false) break
        }
      }
    }
    const finalState = await readState()
    return text({
      scanType: scan_type,
      ports,
      configsTried: configs,
      devices: finalState?.devices ?? [],
      raw: finalState,
    })
  })

  server.registerTool('wb_modbus_add_devices', {
    description: 'Add devices discovered by `wb_modbus_scan` to /etc/wb-mqtt-serial.conf. Reads retained `/wb-device-manager/state` (set by the scanner); for each device, resolves the template via RPC config/Load.types[].hw[].signature → device_type, reads the template file, and copies all default parameter values (p.default from device.parameters[]) into the device record — without this the driver schema validation fails on required parameters (typical case: WB-MAI6 in1_type..in6_type). The `paramDefaults` field in `added[]` shows the number of copied parameters. Already configured slave_ids are skipped. Does not change device settings themselves (baud/parity/stop_bits/slave_id) — use the `device/Setup` RPC separately for that.',
    inputSchema: z.object({
      sn: SN,
      enabled: z.boolean().optional().default(true).describe('Set enabled=true for added entries (default true).'),
      dryRun: z.boolean().optional().default(false).describe('Return the plan without writing (for confirmation).'),
    }),
  }, async ({ sn, enabled, dryRun }) => {
    const c = resolveController(ctx, sn)
    // 1. Read scan results
    const stateRaw = await ctx.ssh.mqttRead(c, '/wb-device-manager/state', 3)
    if (!stateRaw) return err('No scan data. Run wb_modbus_scan first.')
    let state: any
    try { state = JSON.parse(stateRaw) } catch { return err('Failed to parse /wb-device-manager/state JSON') }
    const stateDevices = Array.isArray(state?.devices) ? state.devices : []
    const scanned = stateDevices.filter((d: any) => !d.bootloader_mode && d.device_signature)
    // Dedup by path:slave_id (repeat scans may produce duplicates)
    const seen = new Set<string>()
    const uniq = scanned.filter((d: any) => {
      const k = `${d.port?.path}:${d.cfg?.slave_id}`
      if (seen.has(k)) return false
      seen.add(k); return true
    })
    if (!uniq.length) return err('Scan is empty (no non-bootloader devices).')
    // 2. Resolve signature → {device_type, mqtt-id} via RPC types
    const cfgLoad = await ctx.ssh.mqttRpc(c, 'wb-mqtt-serial', 'config', 'Load', {}, 15) as { config?: { ports?: any[] }, types?: Array<{ types: TplEntry[] }> }
    const sigInfo: Record<string, { type: string; mqttId: string }> = {}
    for (const g of cfgLoad.types ?? []) {
      for (const t of g.types ?? []) {
        for (const h of t.hw ?? []) {
          if (h.signature && !sigInfo[h.signature]) sigInfo[h.signature] = { type: t.type, mqttId: t['mqtt-id'] }
        }
      }
    }
    // 3. Load the confed config for writing (with schema)
    const confed = await ctx.ssh.mqttRpc(c, 'confed', 'Editor', 'Load', { path: '/etc/wb-mqtt-serial.conf' }, 10) as { content: { ports?: any[] } }
    const content = confed.content
    if (!Array.isArray(content.ports)) content.ports = []
    const ports: any[] = content.ports
    const idsByPort = new Map<string, Set<number>>()
    for (const p of ports) {
      const set = new Set<number>()
      for (const d of p.devices ?? []) set.add(Number(d.slave_id))
      idsByPort.set(p.path, set)
    }
    // 4. Template parameter defaults cache. Without defaults the schema validation fails
    //    on required parameters (typical case: WB-MAI6 in1_type..in6_type).
    const tplDefaultsCache = new Map<string, Record<string, unknown>>()
    const loadTplDefaults = async (mqttId: string): Promise<Record<string, unknown>> => {
      const cached = tplDefaultsCache.get(mqttId)
      if (cached) return cached
      if (!/^[A-Za-z0-9._-]+$/.test(mqttId)) return {}
      const r = await ctx.ssh.exec(c, `cat ${shellQuote(`/usr/share/wb-mqtt-serial/templates/config-${mqttId}.json`)}`)
      let defaults: Record<string, unknown> = {}
      if (r.code === 0) {
        try {
          const tpl = JSON.parse(r.stdout)
          const params = tpl.device?.parameters
          if (Array.isArray(params)) {
            for (const p of params) {
              if (p && typeof p.id === 'string' && 'default' in p && !(p.id in defaults)) {
                defaults[p.id] = p.default
              }
            }
          }
        } catch { /* ignore */ }
      }
      tplDefaultsCache.set(mqttId, defaults)
      return defaults
    }
    // 5. Plan
    const added: any[] = []
    const skipped: any[] = []
    for (const dev of uniq) {
      const portPath: string = dev.port?.path
      const slaveId = Number(dev.cfg?.slave_id)
      const sig: string = dev.device_signature
      const port = ports.find((p) => p.path === portPath)
      if (!port) { skipped.push({ slave_id: slaveId, reason: `port ${portPath} not in wb-mqtt-serial config` }); continue }
      const ids = idsByPort.get(portPath) ?? new Set<number>()
      if (ids.has(slaveId)) { skipped.push({ slave_id: slaveId, port: portPath, reason: 'slave_id already configured' }); continue }
      const info = sigInfo[sig]
      if (!info) { skipped.push({ slave_id: slaveId, port: portPath, signature: sig, reason: 'template for signature not found' }); continue }
      const defaults = await loadTplDefaults(info.mqttId)
      const newDevice: Record<string, unknown> = { device_type: info.type, slave_id: slaveId, enabled, ...defaults }
      port.devices = port.devices ?? []
      port.devices.push(newDevice)
      ids.add(slaveId)
      idsByPort.set(portPath, ids)
      added.push({ port: portPath, slave_id: slaveId, device_type: info.type, signature: sig, fw: dev.fw?.version, sn: dev.sn, paramDefaults: Object.keys(defaults).length })
    }
    if (dryRun || !added.length) {
      return text({ dryRun, added, skipped, message: added.length ? `Plan: add ${added.length} device(s). Run without dryRun to write.` : 'Nothing to add.' })
    }
    // 5. Save
    await ctx.ssh.mqttRpc(c, 'confed', 'Editor', 'Save', { path: '/etc/wb-mqtt-serial.conf', content }, 15)
    return text({ added, skipped, saved: true, message: `Added ${added.length} device(s), wb-mqtt-serial restarted via confed.` })
  })
}
