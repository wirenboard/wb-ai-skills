import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { type Ctx, resolveController, text, err, SN } from '../helpers.ts'

export function registerRulesTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_rules_list', {
    description: 'List wb-rules rules (.js files, enabled/disabled)',
    inputSchema: z.object({ sn: SN }),
  }, async ({ sn }) => {
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'wbrules', 'Editor', 'List', {}, 5))
  })

  server.registerTool('wb_rules_load', {
    description: 'Read the contents of a rule (name without .js)',
    inputSchema: z.object({
      sn: SN,
      name: z.string().describe('Rule name without .js'),
    }),
  }, async ({ sn, name }) => {
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'wbrules', 'Editor', 'Load', { path: `${name}.js` }, 5))
  })

  server.registerTool('wb_rules_save', {
    description: 'Save a rule (JS validation + engine reload). ES5 only!',
    inputSchema: z.object({
      sn: SN,
      name: z.string().describe('Rule name without .js'),
      content: z.string().describe('JavaScript code (ES5, var/function, no let/const/arrow)'),
    }),
  }, async ({ sn, name, content }) => {
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'wbrules', 'Editor', 'Save', { path: `${name}.js`, content }, 10))
  })

  server.registerTool('wb_rules_delete', {
    description: 'Delete a rule entirely via wbrules/Editor/Remove (irreversible!).',
    inputSchema: z.object({
      sn: SN,
      name: z.string().describe('Rule name without .js'),
    }),
  }, async ({ sn, name }) => {
    const c = resolveController(ctx, sn)
    const r = await ctx.ssh.mqttRpc(c, 'wbrules', 'Editor', 'Remove', { path: `${name}.js` }, 5)
    if (r !== true) return err(`delete ${name}: unexpected result ${JSON.stringify(r)}`)
    return text({ ok: true, deleted: name })
  })

  server.registerTool('wb_rules_disable', {
    description: 'Disable a rule without deleting it (renames <name>.js → <name>.js.disabled). To re-enable: the current RPC semantics are unreliable; easier to remove the .disabled and re-save via wb_rules_save.',
    inputSchema: z.object({
      sn: SN,
      name: z.string().describe('Rule name without .js'),
    }),
  }, async ({ sn, name }) => {
    const c = resolveController(ctx, sn)
    const r = await ctx.ssh.mqttRpc(c, 'wbrules', 'Editor', 'ChangeState', { path: `${name}.js`, enabled: false }, 5)
    if (r !== true) return err(`disable ${name}: unexpected result ${JSON.stringify(r)}`)
    return text({ ok: true, disabled: name })
  })
}
