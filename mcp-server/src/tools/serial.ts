import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { type Ctx, resolveController, text, err, SN } from '../helpers.ts'

type TplEntry = { type: string; 'mqtt-id': string; name: string; deprecated?: boolean; protocol?: string; hw?: Array<{ signature?: string }> }

export function registerSerialTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_modbus_templates_list', {
    description: 'Шаблоны Modbus-устройств wb-mqtt-serial. Без filter — только сводка по группам (полный список 250+ шаблонов в чате не помещается). С filter — плоский список matched: {type, mqtt-id, name, deprecated, group}. Поиск регистронезависимый по type/mqtt-id/name. По умолчанию deprecated скрыты — includeDeprecated=true чтобы увидеть.',
    inputSchema: z.object({
      sn: SN,
      includeDeprecated: z.boolean().optional().default(false).describe('Включить устаревшие шаблоны'),
      filter: z.string().optional().describe('Подстрока для фильтра по type/mqtt-id/name (регистронезависимо). Без filter возвращается только сводка по группам.'),
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
      return text({ total, totalDeprecated, groups, hint: 'Передай filter="…" чтобы получить плоский список matched. Поиск регистронезависимый.' })
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
    description: 'Шаблон Modbus-устройства из /usr/share/wb-mqtt-serial/templates/config-<mqtt-id>.json. По device_type через RPC wb-mqtt-serial/config/Load находит mqtt-id, читает файл. Регистронезависимый поиск по type или mqtt-id. По умолчанию (`view="summary"`) возвращает компактный список каналов; для полного содержимого с регистрами — `view="full"`. Фильтры: `enabledOnly`, `channelFilter`.',
    inputSchema: z.object({
      sn: SN,
      device_type: z.string().describe('Тип устройства (WB-MR6C, WB-MSW_v.4, WB-MR6C v.3) или mqtt-id (wb-mr6c). Регистронезависимо.'),
      view: z.enum(['summary', 'full', 'channels-only', 'meta-only']).optional().default('summary').describe('summary (default): {meta, channels:[{name,enabled,type,units,readonly,group}]}. full: весь JSON шаблона. channels-only: только массив channels. meta-only: только заголовок без channels/parameters.'),
      enabledOnly: z.boolean().optional().default(false).describe('Только enabled-каналы. По умолчанию все.'),
      channelFilter: z.string().optional().describe('Подстрока для фильтра имён каналов (регистронезависимо).'),
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
    if (!mqttId) return err(`device_type="${device_type}" не найден в wb-mqtt-serial config/Load.types — попробуй wb_modbus_templates_list filter="${device_type}"`)
    const path = `/usr/share/wb-mqtt-serial/templates/config-${mqttId}.json`
    const cat = await ctx.ssh.exec(c, `cat ${path}`)
    if (cat.code !== 0) return err(`cat ${path}: ${cat.stderr.trim()}`)
    let tpl: any
    try { tpl = JSON.parse(cat.stdout) } catch { return err(`Не удалось распарсить ${path}`) }
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
    description: 'Параметры прошивки конкретного Modbus-устройства: fw-версия, model-string, параметры (debounce, modes, mappings). RPC wb-mqtt-serial/device/LoadConfig. Это НЕ список каналов — для каналов и шаблона используй wb_modbus_template.',
    inputSchema: z.object({
      sn: SN,
      device_id: z.string().optional().describe('ID устройства в MQTT (wb-mr6c_138). Достаточно одного, остальные параметры не нужны.'),
      path: z.string().optional().describe('Порт (/dev/ttyRS485-1) — если без device_id'),
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
    description: 'Проверить доступность Modbus-устройства на шине (быстрый пинг)',
    inputSchema: z.object({
      sn: SN,
      path: z.string().describe('Порт (/dev/ttyRS485-1)'),
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
    description: 'Параметры всех RS-485 портов (baud, parity, stop bits, таймауты)',
    inputSchema: z.object({ sn: SN }),
  }, async ({ sn }) => {
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'wb-mqtt-serial', 'ports', 'Load', {}, 5))
  })

  server.registerTool('wb_modbus_scan', {
    description: 'Сканирование шины через wb-device-manager. По умолчанию scan_type="extended" — Fast Modbus (находит WB и Onokom устройства, секунды). scan_type="standard" — обычный Modbus (медленнее, но видит сторонние устройства). Если port не указан — авто-обнаружение всех `/dev/ttyRS485-*`. Если baud_rate не указан — перебирает 115200 и 9600. Возвращает финальный `/wb-device-manager/state` с массивом `devices`.',
    inputSchema: z.object({
      sn: SN,
      port: z.string().optional().describe('Порт (/dev/ttyRS485-1). Без — все RS-485 порты автоматически.'),
      baud_rate: z.number().optional().describe('Скорость. Без — перебор 115200 и 9600.'),
      data_bits: z.number().optional().default(8),
      parity: z.string().optional().default('N'),
      stop_bits: z.number().optional().default(2),
      scan_type: z.enum(['extended', 'standard']).optional().default('extended').describe('extended — Fast Modbus (WB+Onokom), standard — обычный Modbus (видит стороннее)'),
      timeout: z.number().optional().default(180).describe('Общий таймаут на ВСЁ сканирование (сек, default 180). На каждый порт×baud — до timeout/(N×M) секунд.'),
    }),
  }, async ({ sn, port, baud_rate, data_bits, parity, stop_bits, scan_type, timeout }) => {
    const c = resolveController(ctx, sn)
    // Конфиги baud для перебора
    const configs = baud_rate != null
      ? [{ baud_rate, data_bits, parity, stop_bits }]
      : [
          { baud_rate: 115200, data_bits, parity, stop_bits },
          { baud_rate: 9600, data_bits, parity, stop_bits },
        ]
    // Список портов
    let ports: string[]
    if (port) ports = [port]
    else {
      const r = await ctx.ssh.exec(c, 'ls /dev/ttyRS485-* 2>/dev/null', 5000)
      ports = r.stdout.trim().split('\n').filter(Boolean)
      if (!ports.length) return err('Не найдено `/dev/ttyRS485-*` портов на контроллере')
    }
    const readState = async (): Promise<{ scanning?: boolean; progress?: number; devices?: unknown[]; error?: string } | null> => {
      const raw = await ctx.ssh.mqttRead(c, '/wb-device-manager/state', 3)
      if (!raw) return null
      try { return JSON.parse(raw) } catch { return null }
    }
    const deadline = Date.now() + timeout * 1000
    let preserve = false  // первый старт сбрасывает результаты
    for (const p of ports) {
      for (const cfg of configs) {
        if (Date.now() > deadline) return err(`Таймаут ${timeout}s исчерпан, scan не завершён. Прогресс — wb_mqtt_read /wb-device-manager/state`)
        const params = { scan_type, preserve_old_results: preserve, port: { path: p, ...cfg } }
        // Старт; retry если предыдущий ещё в процессе
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
        preserve = true  // последующие конфиги/порты добавляют к найденному
        // Polling: ждём scanning=false
        const portDeadline = Math.min(deadline, Date.now() + 90 * 1000)  // не более 90с на конфиг
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
    description: 'Добавить устройства, найденные `wb_modbus_scan`, в /etc/wb-mqtt-serial.conf. Читает retained `/wb-device-manager/state` (устанавливается сканером), для каждого устройства находит шаблон через RPC config/Load.types[].hw[].signature → device_type, добавляет в соответствующий port.devices. Уже сконфигурированные slave_id пропускаются. Не меняет настройки устройства (baud/parity/stop_bits/slave_id) — для этого используй `device/Setup` RPC отдельно.',
    inputSchema: z.object({
      sn: SN,
      enabled: z.boolean().optional().default(true).describe('Поставить enabled=true для добавленных (по умолчанию true).'),
      dryRun: z.boolean().optional().default(false).describe('Вернуть план без записи (для подтверждения).'),
    }),
  }, async ({ sn, enabled, dryRun }) => {
    const c = resolveController(ctx, sn)
    // 1. Прочитать результаты скана
    const stateRaw = await ctx.ssh.mqttRead(c, '/wb-device-manager/state', 3)
    if (!stateRaw) return err('Нет данных скана. Сначала выполни wb_modbus_scan.')
    let state: any
    try { state = JSON.parse(stateRaw) } catch { return err('Не удалось распарсить /wb-device-manager/state JSON') }
    const scanned = (state.devices ?? []).filter((d: any) => !d.bootloader_mode && d.device_signature)
    // Дедуп по path:slave_id (повторные сканы могут дублировать)
    const seen = new Set<string>()
    const uniq = scanned.filter((d: any) => {
      const k = `${d.port?.path}:${d.cfg?.slave_id}`
      if (seen.has(k)) return false
      seen.add(k); return true
    })
    if (!uniq.length) return err('Скан пустой (нет non-bootloader устройств).')
    // 2. Resolve signature → device_type через RPC types
    const cfgLoad = await ctx.ssh.mqttRpc(c, 'wb-mqtt-serial', 'config', 'Load', {}, 15) as { config?: { ports?: any[] }, types?: Array<{ types: TplEntry[] }> }
    const sigToType: Record<string, string> = {}
    for (const g of cfgLoad.types ?? []) {
      for (const t of g.types ?? []) {
        for (const h of t.hw ?? []) {
          if (h.signature && !sigToType[h.signature]) sigToType[h.signature] = t.type
        }
      }
    }
    // 3. Загрузить confed-конфиг для записи (с schema)
    const confed = await ctx.ssh.mqttRpc(c, 'confed', 'Editor', 'Load', { path: '/etc/wb-mqtt-serial.conf' }, 10) as { content: { ports?: any[] } }
    const content = confed.content
    const ports: any[] = content.ports ?? (content.ports = [])
    const idsByPort = new Map<string, Set<number>>()
    for (const p of ports) {
      const set = new Set<number>()
      for (const d of p.devices ?? []) set.add(Number(d.slave_id))
      idsByPort.set(p.path, set)
    }
    // 4. План
    const added: any[] = []
    const skipped: any[] = []
    for (const dev of uniq) {
      const portPath: string = dev.port?.path
      const slaveId = Number(dev.cfg?.slave_id)
      const sig: string = dev.device_signature
      const port = ports.find((p) => p.path === portPath)
      if (!port) { skipped.push({ slave_id: slaveId, reason: `порт ${portPath} не в конфиге wb-mqtt-serial` }); continue }
      const ids = idsByPort.get(portPath) ?? new Set<number>()
      if (ids.has(slaveId)) { skipped.push({ slave_id: slaveId, port: portPath, reason: 'slave_id уже сконфигурирован' }); continue }
      const deviceType = sigToType[sig]
      if (!deviceType) { skipped.push({ slave_id: slaveId, port: portPath, signature: sig, reason: 'шаблон для signature не найден' }); continue }
      const newDevice = { device_type: deviceType, slave_id: slaveId, enabled }
      port.devices = port.devices ?? []
      port.devices.push(newDevice)
      ids.add(slaveId)
      idsByPort.set(portPath, ids)
      added.push({ port: portPath, slave_id: slaveId, device_type: deviceType, signature: sig, fw: dev.fw?.version, sn: dev.sn })
    }
    if (dryRun || !added.length) {
      return text({ dryRun, added, skipped, message: added.length ? `План: добавить ${added.length} устройств(а). Запусти без dryRun для записи.` : 'Нечего добавлять.' })
    }
    // 5. Сохранить
    await ctx.ssh.mqttRpc(c, 'confed', 'Editor', 'Save', { path: '/etc/wb-mqtt-serial.conf', content }, 15)
    return text({ added, skipped, saved: true, message: `Добавлено ${added.length} устройств(а), wb-mqtt-serial перезапущен через confed.` })
  })
}
