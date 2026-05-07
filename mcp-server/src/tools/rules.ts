import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { type Ctx, resolveController, text, err, SN } from '../helpers.ts'

export function registerRulesTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_rules_list', {
    description: 'Список правил wb-rules (файлы .js, enabled/disabled)',
    inputSchema: z.object({ sn: SN }),
  }, async ({ sn }) => {
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'wbrules', 'Editor', 'List', {}, 5))
  })

  server.registerTool('wb_rules_load', {
    description: 'Прочитать содержимое правила (имя без .js)',
    inputSchema: z.object({
      sn: SN,
      name: z.string().describe('Имя правила без .js'),
    }),
  }, async ({ sn, name }) => {
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'wbrules', 'Editor', 'Load', { path: `${name}.js` }, 5))
  })

  server.registerTool('wb_rules_save', {
    description: 'Сохранить правило (валидация JS + перезагрузка движка). ES5 only!',
    inputSchema: z.object({
      sn: SN,
      name: z.string().describe('Имя правила без .js'),
      content: z.string().describe('JavaScript-код (ES5, var/function, без let/const/arrow)'),
    }),
  }, async ({ sn, name, content }) => {
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'wbrules', 'Editor', 'Save', { path: `${name}.js`, content }, 10))
  })

  server.registerTool('wb_rules_delete', {
    description: 'Удалить правило целиком через wbrules/Editor/Remove (необратимо!).',
    inputSchema: z.object({
      sn: SN,
      name: z.string().describe('Имя правила без .js'),
    }),
  }, async ({ sn, name }) => {
    const c = resolveController(ctx, sn)
    const r = await ctx.ssh.mqttRpc(c, 'wbrules', 'Editor', 'Remove', { path: `${name}.js` }, 5)
    if (r !== true) return err(`delete ${name}: unexpected result ${JSON.stringify(r)}`)
    return text({ ok: true, deleted: name })
  })

  server.registerTool('wb_rules_disable', {
    description: 'Выключить правило, не удаляя (переименовывает <name>.js → <name>.js.disabled). Включить обратно — текущая RPC-семантика ненадёжна, проще удалить .disabled и пересохранить через wb_rules_save.',
    inputSchema: z.object({
      sn: SN,
      name: z.string().describe('Имя правила без .js'),
    }),
  }, async ({ sn, name }) => {
    const c = resolveController(ctx, sn)
    const r = await ctx.ssh.mqttRpc(c, 'wbrules', 'Editor', 'ChangeState', { path: `${name}.js`, enabled: false }, 5)
    if (r !== true) return err(`disable ${name}: unexpected result ${JSON.stringify(r)}`)
    return text({ ok: true, disabled: name })
  })
}
