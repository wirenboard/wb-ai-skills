import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { type Ctx, resolveController, text, err, SN, LONG_COMMANDS_RE } from '../helpers.ts'

export function registerSshTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_ssh_exec', {
    description: 'Run a command on the controller (synchronously, up to 2 min). For long operations use wb_ssh_exec_async.',
    inputSchema: z.object({
      sn: SN,
      command: z.string().describe('Bash command'),
      timeout: z.number().optional().default(30000).describe('Timeout in ms (max 120000)'),
    }),
  }, async ({ sn, command, timeout }) => {
    if (LONG_COMMANDS_RE.test(command)) {
      return err(`Command "${command.slice(0, 60)}..." is a long operation. Use wb_ssh_exec_async.`)
    }
    const c = resolveController(ctx, sn)
    return text(await ctx.ssh.exec(c, command, Math.min(timeout, 120000)))
  })

  server.registerTool('wb_ssh_exec_async', {
    description: 'Start a background job via systemd-run (apt, docker, tar). Returns jobId.',
    inputSchema: z.object({
      sn: SN,
      command: z.string().describe('Bash command'),
      label: z.string().optional().describe('Job label'),
    }),
  }, async ({ sn, command, label }) => {
    const c = resolveController(ctx, sn)
    // DEBIAN_FRONTEND=noninteractive is exported on a separate line:
    // the prefix `DEBIAN_FRONTEND=... <command>` form breaks on control words (`for`, `while`, `if`),
    // and on a script file (the new async architecture) such a prefix form yields a syntax error.
    const cmd = command.includes('DEBIAN_FRONTEND')
      ? command
      : `export DEBIAN_FRONTEND=noninteractive\n${command}`
    return text(await ctx.ssh.jobStart(c, cmd, label))
  })

  server.registerTool('wb_read_file', {
    description: 'Read a file from the controller (up to 64 KB)',
    inputSchema: z.object({
      sn: SN,
      path: z.string().describe('Absolute path to the file'),
      maxBytes: z.number().optional().default(64000),
    }),
  }, async ({ sn, path, maxBytes }) => {
    const c = resolveController(ctx, sn)
    return text(await ctx.ssh.readFile(c, path, maxBytes))
  })

  server.registerTool('wb_write_file', {
    description: 'Write a file to the controller (SFTP). Make a backup before editing configs!',
    inputSchema: z.object({
      sn: SN,
      path: z.string().describe('Absolute path'),
      content: z.string().describe('File contents'),
    }),
  }, async ({ sn, path, content }) => {
    const c = resolveController(ctx, sn)
    await ctx.ssh.writeFile(c, path, content)
    return text({ ok: true, path })
  })
}
