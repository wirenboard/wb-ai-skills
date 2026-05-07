import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { runAudit, runSnapshot, runDiffSnapshot } from '../lib/audit.ts'
import { type Ctx, resolveController, text, SN } from '../helpers.ts'

export function registerAuditTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_audit', {
    description: 'Аудит контроллера — доп. пакеты, сервисы, кастомные файлы, изменённые конфиги',
    inputSchema: z.object({ sn: SN }),
  }, async ({ sn }) => {
    return text(await runAudit(ctx.ssh, resolveController(ctx, sn)))
  })

  server.registerTool('wb_state_save', {
    description: 'Сохранить слепок состояния системы контроллера для последующего сравнения через wb_state_diff',
    inputSchema: z.object({ sn: SN }),
  }, async ({ sn }) => {
    return text(await runSnapshot(ctx.ssh, resolveController(ctx, sn)))
  })

  server.registerTool('wb_state_diff', {
    description: 'Сравнить текущее состояние системы со слепком — что добавилось/убавилось (пакеты, сервисы, файлы)',
    inputSchema: z.object({
      sn: SN,
      beforePath: z.string().describe('Путь к слепку на контроллере (из wb_state_save)'),
    }),
  }, async ({ sn, beforePath }) => {
    return text(await runDiffSnapshot(ctx.ssh, resolveController(ctx, sn), beforePath))
  })
}
