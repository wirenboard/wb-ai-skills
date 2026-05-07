import { z } from 'zod'
import type { SshPool } from './lib/ssh.ts'
import type { Discovery } from './lib/discovery.ts'
import { defaultHost, type Controller } from './lib/types.ts'

export type Ctx = {
  ssh: SshPool
  discovery: Discovery
}

/** Find a controller by SN/host. If it isn't in the registry, try resolving via
 *  defaultHost(sn) (`wirenboard-<SN>.local`). This lets you call `wb_probe sn=NEW`
 *  without a prior `wb_discover` or `wb_add_controller`. If the SN is entirely
 *  foreign and mDNS can't find it, the ssh command downstream will fail with a clear error. */
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

export const SN = z.string().describe('Controller serial number (e.g. A25NDEMJ)')

export const LONG_COMMANDS_RE = /\b(apt\s+(update|install|upgrade|dist-upgrade|remove|purge)|docker\s+(run|pull|build|compose)|wb-release\s+-[ty])/
