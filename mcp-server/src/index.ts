/**
 * WB MCP Server — MCP tools for Wiren Board controllers.
 * Self-contained: discovery/ssh/audit live in ./lib, no external deps beyond
 * @modelcontextprotocol/sdk and zod.
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'

import { SshPool } from './lib/ssh.ts'
import { Discovery } from './lib/discovery.ts'

import type { Ctx } from './helpers.ts'
import { registerDiscoveryTools } from './tools/discovery.ts'
import { registerSshTools } from './tools/ssh.ts'
import { registerJobTools } from './tools/jobs.ts'
import { registerMqttTools } from './tools/mqtt.ts'
import { registerDeviceTools } from './tools/devices.ts'
import { registerConfigTools } from './tools/config.ts'
import { registerRulesTools } from './tools/rules.ts'
import { registerHistoryTools } from './tools/history.ts'
import { registerAuditTools } from './tools/audit.ts'
import { registerSerialTools } from './tools/serial.ts'
import { registerDiagnosticTools } from './tools/diagnostics.ts'

const SSH_USER = process.env['WB_SSH_USER'] ?? 'root'
const SSH_KEY = process.env['WB_SSH_KEY'] ?? ''
// Password used only when key is not provided (default fallback for stock controllers).
const SSH_PASSWORD = SSH_KEY ? '' : (process.env['WB_SSH_PASSWORD'] ?? 'wirenboard')
const DISCOVERY_INTERVAL = Number(process.env['WB_DISCOVERY_INTERVAL']) || 15000

async function main() {
  const ssh = new SshPool({ user: SSH_USER, password: SSH_PASSWORD || undefined, keyPath: SSH_KEY || undefined })
  const discovery = new Discovery()
  discovery.start(DISCOVERY_INTERVAL)

  const ctx: Ctx = { ssh, discovery }

  const server = new McpServer({ name: 'wiren-board', version: '0.1.0' })

  registerDiscoveryTools(server, ctx)
  registerSshTools(server, ctx)
  registerJobTools(server, ctx)
  registerMqttTools(server, ctx)
  registerDeviceTools(server, ctx)
  registerConfigTools(server, ctx)
  registerRulesTools(server, ctx)
  registerHistoryTools(server, ctx)
  registerAuditTools(server, ctx)
  registerSerialTools(server, ctx)
  registerDiagnosticTools(server, ctx)

  const transport = new StdioServerTransport()
  await server.connect(transport)
  console.error(`[wb-mcp] Started: ${SSH_USER}@*, discovery ${DISCOVERY_INTERVAL}ms`)
}

main().catch((e) => {
  console.error('[wb-mcp] Fatal:', e)
  process.exit(1)
})
