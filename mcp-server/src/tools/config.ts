import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { type Ctx, resolveController, text, SN } from '../helpers.ts'

export function registerConfigTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_confed_load', {
    description: 'Загрузить конфиг через confed RPC (с валидацией и schema). Путь: /etc/wb-mqtt-serial.conf, /etc/wb-hardware.conf и др.',
    inputSchema: z.object({
      sn: SN,
      path: z.string().describe('Путь к конфигу (/etc/wb-mqtt-serial.conf, /etc/wb-hardware.conf)'),
    }),
  }, async ({ sn, path }) => {
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'confed', 'Editor', 'Load', { path }, 10))
  })

  server.registerTool('wb_confed_save', {
    description: 'Сохранить конфиг через confed RPC (валидация + рестарт сервиса). content — либо JSON-объект, либо JSON-строка (она будет распарсена; передавать строку как content RPC не безопасно — confed запишет её эскейпнутой, ломая конфиг).',
    inputSchema: z.object({
      sn: SN,
      path: z.string().describe('Путь к конфигу'),
      content: z.unknown().describe('Содержимое конфига: JSON-объект ИЛИ строка с JSON (будет распарсена)'),
    }),
  }, async ({ sn, path, content }) => {
    let payload: unknown = content
    if (typeof content === 'string') {
      try { payload = JSON.parse(content) } catch (e) {
        return text({ error: `content — строка, но не валидный JSON: ${(e as Error).message}` })
      }
    }
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'confed', 'Editor', 'Save', { path, content: payload }, 15))
  })
}
