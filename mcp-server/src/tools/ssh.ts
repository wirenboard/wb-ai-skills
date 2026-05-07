import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { type Ctx, resolveController, text, err, SN, LONG_COMMANDS_RE } from '../helpers.ts'

export function registerSshTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_ssh_exec', {
    description: 'Выполнить команду на контроллере (синхронно, до 2 мин). Для долгих операций используй wb_ssh_exec_async.',
    inputSchema: z.object({
      sn: SN,
      command: z.string().describe('Bash-команда'),
      timeout: z.number().optional().default(30000).describe('Таймаут в мс (макс 120000)'),
    }),
  }, async ({ sn, command, timeout }) => {
    if (LONG_COMMANDS_RE.test(command)) {
      return err(`Команда "${command.slice(0, 60)}..." — долгая операция. Используй wb_ssh_exec_async.`)
    }
    const c = resolveController(ctx, sn)
    return text(await ctx.ssh.exec(c, command, Math.min(timeout, 120000)))
  })

  server.registerTool('wb_ssh_exec_async', {
    description: 'Запустить фоновую задачу через systemd-run (apt, docker, tar). Возвращает jobId.',
    inputSchema: z.object({
      sn: SN,
      command: z.string().describe('Bash-команда'),
      label: z.string().optional().describe('Метка задачи'),
    }),
  }, async ({ sn, command, label }) => {
    const c = resolveController(ctx, sn)
    // DEBIAN_FRONTEND=noninteractive экспортируется отдельной строкой:
    // префикс `DEBIAN_FRONTEND=... <команда>` ломается на control-словах (`for`, `while`, `if`),
    // плюс на script-файле (новая архитектура async) такая префиксная форма даёт syntax error.
    const cmd = command.includes('DEBIAN_FRONTEND')
      ? command
      : `export DEBIAN_FRONTEND=noninteractive\n${command}`
    return text(await ctx.ssh.jobStart(c, cmd, label))
  })

  server.registerTool('wb_read_file', {
    description: 'Прочитать файл с контроллера (до 64 КБ)',
    inputSchema: z.object({
      sn: SN,
      path: z.string().describe('Абсолютный путь к файлу'),
      maxBytes: z.number().optional().default(64000),
    }),
  }, async ({ sn, path, maxBytes }) => {
    const c = resolveController(ctx, sn)
    return text(await ctx.ssh.readFile(c, path, maxBytes))
  })

  server.registerTool('wb_write_file', {
    description: 'Записать файл на контроллер (SFTP). Сделай бэкап перед правкой конфигов!',
    inputSchema: z.object({
      sn: SN,
      path: z.string().describe('Абсолютный путь'),
      content: z.string().describe('Содержимое файла'),
    }),
  }, async ({ sn, path, content }) => {
    const c = resolveController(ctx, sn)
    await ctx.ssh.writeFile(c, path, content)
    return text({ ok: true, path })
  })
}
