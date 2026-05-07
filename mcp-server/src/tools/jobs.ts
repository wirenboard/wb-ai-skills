import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { type Ctx, resolveController, text, SN } from '../helpers.ts'

export function registerJobTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_job_status', {
    description: 'Check the status of a background job (running/exited)',
    inputSchema: z.object({ sn: SN, jobId: z.string() }),
  }, async ({ sn, jobId }) => {
    return text(await ctx.ssh.jobStatus(resolveController(ctx, sn), jobId))
  })

  server.registerTool('wb_job_tail', {
    description: 'Read the log of a background job (incrementally)',
    inputSchema: z.object({
      sn: SN, jobId: z.string(),
      fromLine: z.number().optional().default(1),
      maxLines: z.number().optional().default(500),
    }),
  }, async ({ sn, jobId, fromLine, maxLines }) => {
    return text(await ctx.ssh.jobTail(resolveController(ctx, sn), jobId, fromLine, maxLines))
  })

  server.registerTool('wb_job_cancel', {
    description: 'Cancel a background job (SIGTERM → SIGKILL)',
    inputSchema: z.object({ sn: SN, jobId: z.string() }),
  }, async ({ sn, jobId }) => {
    const c = resolveController(ctx, sn)
    await ctx.ssh.jobCancel(c, jobId)
    return text({ ok: true, jobId })
  })
}
