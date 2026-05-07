import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { type Ctx, resolveController, text, SN } from '../helpers.ts'

/** WB MQTT Conventions error codes (https://github.com/wirenboard/conventions):
 *  `r` — read error / device reports error; `w` — write error; `p` — period miss.
 *  Combinations возможны: "rw", "rp", "rwp". Пустая строка/null = нет ошибок. */
type ErrorFlags = { raw: string; read: boolean; write: boolean; periodMiss: boolean; unknown?: string }

function parseErrorFlags(raw: string | undefined): ErrorFlags | undefined {
  if (raw == null || raw === '') return undefined
  const flags: ErrorFlags = { raw, read: false, write: false, periodMiss: false }
  let unknown = ''
  for (const ch of raw) {
    if (ch === 'r') flags.read = true
    else if (ch === 'w') flags.write = true
    else if (ch === 'p') flags.periodMiss = true
    else unknown += ch
  }
  if (unknown) flags.unknown = unknown
  return flags
}

type Control = {
  name: string
  value?: string         // при error.read=true это last-known-good (по WB convention)
  type?: string
  units?: string
  readonly?: boolean
  order?: number
  min?: number
  max?: number
  precision?: number
  error?: ErrorFlags
  title?: unknown
  meta?: Record<string, unknown>
}

type Device = {
  id: string
  name?: string
  driver?: string
  error?: ErrorFlags
  controlCount: number
  controls: Control[]
}

function parseMetaJson(s: string): Record<string, unknown> | null {
  try { return JSON.parse(s) } catch { return null }
}

export function registerDeviceTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_mqtt_devices', {
    description: 'Список MQTT-устройств на контроллере (только id → human name). Не путать с wb_discover (тот ищет контроллеры в сети). Для полной картины с контролами — wb_mqtt_inventory.',
    inputSchema: z.object({ sn: SN }),
  }, async ({ sn }) => {
    const topics = await ctx.ssh.mqttListTopics(resolveController(ctx, sn), '/devices/+/meta/name', 3)
    const devices: Record<string, string> = {}
    for (const { topic, payload } of topics) {
      const m = topic.match(/^\/devices\/([^/]+)\/meta\/name$/)
      if (m) devices[m[1]!] = payload.trim()
    }
    return text(devices)
  })

  server.registerTool('wb_mqtt_controls', {
    description: 'Список контролов одного MQTT-устройства (raw топики со значениями). Для структурированной картины со всеми meta — wb_mqtt_inventory с device-фильтром.',
    inputSchema: z.object({
      sn: SN,
      device: z.string().describe('ID устройства (например wb-mr6c_7)'),
    }),
  }, async ({ sn, device }) => {
    return text(await ctx.ssh.mqttListTopics(resolveController(ctx, sn), `/devices/${device}/controls/+`, 3))
  })

  server.registerTool('wb_mqtt_inventory', {
    description: 'Сводная картина MQTT-устройств: id, name, driver, error, для каждого — список контролов с value/type/units/readonly/order/error. Один вызов вместо N+1 запросов через wb_mqtt_devices+wb_mqtt_controls. Поле `error` парсится по WB MQTT Conventions (r=read, w=write, p=period miss; комбинации возможны). При `error.read=true` value-топик содержит last-known-good значение. Возвращает также сводку всех ошибок отдельным массивом `errors`. По умолчанию includeEmpty=false (устройства без контролов скрыты).',
    inputSchema: z.object({
      sn: SN,
      device: z.string().optional().describe('Фильтр по device_id (substring, регистронезависимо). Без — все устройства.'),
      timeout: z.number().optional().default(3).describe('Таймаут сбора в секундах'),
      includeEmpty: z.boolean().optional().default(false).describe('Включить устройства без контролов (только meta).'),
      includeMeta: z.boolean().optional().default(false).describe('Включить полный raw meta-объект для каждого контрола (по умолчанию только распакованные поля).'),
    }),
  }, async ({ sn, device, timeout, includeEmpty, includeMeta }) => {
    const topics = await ctx.ssh.mqttListTopics(resolveController(ctx, sn), '/devices/#', timeout)
    const devices = new Map<string, Device>()
    const ensureDev = (id: string): Device => {
      let d = devices.get(id)
      if (!d) { d = { id, controlCount: 0, controls: [] }; devices.set(id, d) }
      return d
    }
    const ensureCtrl = (dev: Device, name: string): Control => {
      let c = dev.controls.find((c) => c.name === name)
      if (!c) { c = { name }; dev.controls.push(c); dev.controlCount = dev.controls.length }
      return c
    }
    const filt = device?.toLowerCase()
    for (const { topic, payload } of topics) {
      // /devices/<id>/meta/<key>?  /devices/<id>/controls/<ctrl>(/meta(/<key>)?)?
      const dev = topic.match(/^\/devices\/([^/]+)\/(.+)$/)
      if (!dev) continue
      const id = dev[1]!
      if (filt && !id.toLowerCase().includes(filt)) continue
      const rest = dev[2]!
      const d = ensureDev(id)
      const metaMatch = rest.match(/^meta(?:\/(.+))?$/)
      if (metaMatch) {
        const key = metaMatch[1]
        if (!key) {
          // /meta — full JSON object
          const obj = parseMetaJson(payload)
          if (obj) {
            if (typeof obj.name === 'string') d.name = obj.name
            if (typeof obj.driver === 'string') d.driver = obj.driver
            if (typeof obj.error === 'string') d.error = parseErrorFlags(obj.error)
          }
        } else if (key === 'name') d.name = payload
        else if (key === 'driver') d.driver = payload
        else if (key === 'error') d.error = parseErrorFlags(payload)
        continue
      }
      const ctrlMatch = rest.match(/^controls\/(.+)$/)
      if (!ctrlMatch) continue
      const ctrlPart = ctrlMatch[1]!
      // Имя контрола может содержать '/' только в виде /meta или /meta/<key>; иначе это control name (с пробелами).
      const subMatch = ctrlPart.match(/^(.+?)\/meta(?:\/(.+))?$/)
      if (subMatch) {
        const ctrlName = subMatch[1]!
        const metaKey = subMatch[2]
        const c = ensureCtrl(d, ctrlName)
        if (!metaKey) {
          // /meta — full JSON
          const obj = parseMetaJson(payload)
          if (obj) {
            if (typeof obj.type === 'string') c.type = obj.type
            if (typeof obj.units === 'string') c.units = obj.units
            if (typeof obj.readonly === 'boolean') c.readonly = obj.readonly
            if (typeof obj.order === 'number') c.order = obj.order
            if (typeof obj.min === 'number') c.min = obj.min
            if (typeof obj.max === 'number') c.max = obj.max
            if (typeof obj.precision === 'number') c.precision = obj.precision
            if (typeof obj.error === 'string') c.error = parseErrorFlags(obj.error)
            if (obj.title !== undefined) c.title = obj.title
            if (includeMeta) c.meta = obj
          }
        } else {
          const c2 = c
          if (metaKey === 'type') c2.type = payload
          else if (metaKey === 'units') c2.units = payload
          else if (metaKey === 'readonly') c2.readonly = payload === '1' || payload === 'true'
          else if (metaKey === 'order') c2.order = Number(payload)
          else if (metaKey === 'min') c2.min = Number(payload)
          else if (metaKey === 'max') c2.max = Number(payload)
          else if (metaKey === 'precision') c2.precision = Number(payload)
          else if (metaKey === 'error') c2.error = parseErrorFlags(payload)
        }
      } else {
        // /devices/<id>/controls/<ctrlName> — value
        const c = ensureCtrl(d, ctrlPart)
        c.value = payload
      }
    }
    let arr = [...devices.values()]
    if (!includeEmpty) arr = arr.filter((d) => d.controls.length > 0)
    arr.sort((a, b) => a.id.localeCompare(b.id))
    for (const d of arr) {
      d.controls.sort((a, b) => (a.order ?? 999) - (b.order ?? 999) || a.name.localeCompare(b.name))
    }
    // Сводка ошибок — что с проблемами (по WB convention: r/w/p или их комбинации)
    const errors: Array<{ device: string; control?: string; flags: ErrorFlags }> = []
    for (const d of arr) {
      if (d.error) errors.push({ device: d.id, flags: d.error })
      for (const c of d.controls) {
        if (c.error) errors.push({ device: d.id, control: c.name, flags: c.error })
      }
    }
    return text({
      count: arr.length,
      errorCount: errors.length,
      errors,
      devices: arr,
    })
  })
}
