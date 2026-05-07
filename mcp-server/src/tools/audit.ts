import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { runAudit, runSnapshot, runDiffSnapshot } from '../lib/audit.ts'
import { type Ctx, resolveController, text, SN } from '../helpers.ts'

export function registerAuditTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_audit', {
    description: 'Controller audit — extra packages, services, custom files, modified configs',
    inputSchema: z.object({ sn: SN }),
  }, async ({ sn }) => {
    return text(await runAudit(ctx.ssh, resolveController(ctx, sn)))
  })

  server.registerTool('wb_state_save', {
    description: 'Save a snapshot of the controller system state for later comparison via wb_state_diff',
    inputSchema: z.object({ sn: SN }),
  }, async ({ sn }) => {
    return text(await runSnapshot(ctx.ssh, resolveController(ctx, sn)))
  })

  server.registerTool('wb_state_diff', {
    description: 'Compare current system state with a snapshot — what was added/removed (packages, services, files)',
    inputSchema: z.object({
      sn: SN,
      beforePath: z.string().describe('Path to the snapshot on the controller (from wb_state_save)'),
    }),
  }, async ({ sn, beforePath }) => {
    return text(await runDiffSnapshot(ctx.ssh, resolveController(ctx, sn), beforePath))
  })
}
