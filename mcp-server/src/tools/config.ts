import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { type Ctx, resolveController, text, SN } from '../helpers.ts'

export function registerConfigTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_confed_load', {
    description: 'Load a config via confed RPC (with validation and schema). Path: /etc/wb-mqtt-serial.conf, /etc/wb-hardware.conf, etc.',
    inputSchema: z.object({
      sn: SN,
      path: z.string().describe('Path to the config (/etc/wb-mqtt-serial.conf, /etc/wb-hardware.conf)'),
    }),
  }, async ({ sn, path }) => {
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'confed', 'Editor', 'Load', { path }, 10))
  })

  server.registerTool('wb_confed_save', {
    description: 'Save a config via confed RPC (validation + service restart). content is either a JSON object or a JSON string (it will be parsed; passing a string as the RPC content directly is unsafe — confed would write it escaped, breaking the config).',
    inputSchema: z.object({
      sn: SN,
      path: z.string().describe('Path to the config'),
      content: z.unknown().describe('Config contents: JSON object OR a string containing JSON (will be parsed)'),
    }),
  }, async ({ sn, path, content }) => {
    let payload: unknown = content
    if (typeof content === 'string') {
      try { payload = JSON.parse(content) } catch (e) {
        return text({ error: `content is a string but not valid JSON: ${(e as Error).message}` })
      }
    }
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'confed', 'Editor', 'Save', { path, content: payload }, 15))
  })
}
