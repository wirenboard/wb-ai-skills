import { z } from 'zod'
import type { SshPool } from './lib/ssh.ts'
import type { Discovery } from './lib/discovery.ts'
import { defaultHost, type Controller } from './lib/types.ts'

export type Ctx = {
  ssh: SshPool
  discovery: Discovery
}

/** Найти контроллер по SN/host. Если не нашли в реестре — пробуем зарезолвить через
 *  defaultHost(sn) (`wirenboard-<SN>.local`). Это позволяет вызвать `wb_probe sn=NEW`
 *  без предварительного `wb_discover` или `wb_add_controller`. Если SN полностью
 *  чужой и mDNS не найдёт его — ssh-команда дальше упадёт с понятной ошибкой. */
export function resolveController(ctx: Ctx, sn: string): Controller {
  const c = ctx.discovery.findByKey(sn)
  if (c) return c
  return { sn: sn.toUpperCase(), host: defaultHost(sn), addresses: [], source: 'mdns', lastSeen: 0 }
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
