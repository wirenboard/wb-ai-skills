import { z } from 'zod'
import type { SshPool } from './lib/ssh.ts'
import type { Discovery } from './lib/discovery.ts'
import type { Controller } from './lib/types.ts'

export type Ctx = {
  ssh: SshPool
  discovery: Discovery
}

export function resolveController(ctx: Ctx, sn: string): Controller {
  const c = ctx.discovery.get(sn) ?? ctx.discovery.getOrCreate(sn)
  if (!c) throw new Error(`Контроллер ${sn} не найден. Используй wb_discover для поиска.`)
  return c
}

export function text(data: unknown) {
  const s = typeof data === 'string' ? data : JSON.stringify(data, null, 2)
  return { content: [{ type: 'text' as const, text: s }] }
}

export function err(msg: string) {
  return { content: [{ type: 'text' as const, text: msg }], isError: true as const }
}

export const SN = z.string().describe('Серийный номер контроллера (например A25NDEMJ)')

export const LONG_COMMANDS_RE = /\b(apt\s+(update|install|upgrade|dist-upgrade|remove|purge)|docker\s+(run|pull|build|compose)|wb-release\s+-[ty])/
