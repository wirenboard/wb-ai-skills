export type Controller = {
  sn: string
  host: string
  addresses: string[]
  source: 'mdns' | 'manual'
  reachable?: boolean
  fw?: string
  lastSeen: number
}

export type ExecResult = {
  stdout: string
  stderr: string
  code: number
}

export type SshAuth = {
  user: string
  password?: string
  keyPath?: string
}

export const SN_FROM_HOST = /^wirenboard-([A-Za-z0-9]+)(?:\.local)?\.?$/

export function parseSn(host: string): string | null {
  const m = host.trim().match(SN_FROM_HOST)
  return m && m[1] ? m[1].toUpperCase() : null
}

export function defaultHost(sn: string): string {
  return `wirenboard-${sn.toLowerCase()}.local`
}

/** Reject IPv6 link-local — useless for SSH from a different host. */
export function isUsableAddress(addr: string): boolean {
  if (!addr) return false
  const lower = addr.toLowerCase()
  return !(lower.startsWith('fe80:') || lower.startsWith('fe80::'))
}
