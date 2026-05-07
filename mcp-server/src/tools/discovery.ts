import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { type Ctx, resolveController, text, SN } from '../helpers.ts'

export function registerDiscoveryTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_discover', {
    description: 'Find Wiren Board controllers on the local network (mDNS + manual)',
    inputSchema: z.object({}),
  }, async () => {
    const list = ctx.discovery.list()
    return text(list.map(c => ({
      sn: c.sn, host: c.host, addresses: c.addresses,
      source: c.source, reachable: c.reachable, fw: c.fw,
    })))
  })

  server.registerTool('wb_probe', {
    description: 'Check controller reachability and fetch system information',
    inputSchema: z.object({ sn: SN }),
  }, async ({ sn }) => {
    const c = resolveController(ctx, sn)
    return text(await ctx.ssh.getInfo(c))
  })

  server.registerTool('wb_add_controller', {
    description: 'Add a controller manually by hostname or IP',
    inputSchema: z.object({
      host: z.string().describe('Hostname or IP'),
    }),
  }, async ({ host }) => {
    const c = ctx.discovery.addManual(host)
    return text({ sn: c.sn, host: c.host, source: c.source })
  })
}
