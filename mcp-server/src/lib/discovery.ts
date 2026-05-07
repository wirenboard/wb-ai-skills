import { spawn } from 'node:child_process'
import { promises as dns } from 'node:dns'
import { type Controller, parseSn, defaultHost, isUsableAddress } from './types.ts'
import { ManualStore } from './store.ts'

/** Run a command with stdout captured, killed after timeoutMs. */
function exec(cmd: string, args: string[], timeoutMs: number): Promise<string> {
  return new Promise((resolve) => {
    const p = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'ignore'] })
    let out = ''
    p.stdout?.on('data', (d) => { out += String(d) })
    const t = setTimeout(() => p.kill('SIGTERM'), timeoutMs)
    p.on('close', () => { clearTimeout(t); resolve(out) })
    p.on('error', () => { clearTimeout(t); resolve(out) })
  })
}

export class Discovery {
  private controllers = new Map<string, Controller>()
  private store: ManualStore
  private timer: ReturnType<typeof setInterval> | null = null

  constructor(storePath?: string) {
    this.store = new ManualStore(storePath)
    for (const e of this.store.list()) {
      this.controllers.set(e.sn, {
        sn: e.sn, host: e.host, addresses: [],
        source: 'manual', lastSeen: e.addedAt,
      })
    }
  }

  start(intervalMs: number) {
    const ms = Math.max(1000, intervalMs)
    if (this.timer) clearInterval(this.timer)
    this.timer = setInterval(() => void this.refresh(), ms)
    void this.refresh()
  }

  stop() {
    if (this.timer) { clearInterval(this.timer); this.timer = null }
  }

  list(): Controller[] {
    return [...this.controllers.values()].sort((a, b) => a.sn.localeCompare(b.sn))
  }

  get(sn: string): Controller | undefined {
    return this.controllers.get(sn.toUpperCase())
  }

  /** Find by SN (registry) or by hostname/IP among known controllers.
   *  Не создаёт новых записей — для добавления используй `addManual`. */
  findByKey(snOrHost: string): Controller | undefined {
    const upper = snOrHost.toUpperCase()
    const byKey = this.controllers.get(upper)
    if (byKey) return byKey
    for (const c of this.controllers.values()) {
      if (c.host === snOrHost || c.addresses.includes(snOrHost)) return c
    }
    return undefined
  }

  addManual(host: string): Controller {
    const sn = parseSn(host) ?? host.toUpperCase()
    const entry = this.store.add(sn, host)
    const c: Controller = {
      sn, host, addresses: [], source: 'manual', lastSeen: entry.addedAt,
    }
    this.controllers.set(sn, c)
    return c
  }

  async refresh() {
    await Promise.all([this.resolveKnown(), this.avahiBrowse()])
  }

  /** dns.lookup for known .local hosts; merges results, drops link-local. */
  private async resolveKnown() {
    const probes = [...this.controllers.values()]
      .filter((c) => c.host.endsWith('.local'))
      .map(async (c) => {
        try {
          const addrs = await dns.lookup(c.host, { all: true, family: 0 })
          const usable = addrs.map((a) => a.address).filter(isUsableAddress)
          c.addresses = mergeAddresses(c.addresses, usable)
          c.reachable = usable.length > 0
          if (c.reachable) c.lastSeen = Date.now()
        } catch {
          c.reachable = false
        }
      })
    await Promise.all(probes)
  }

  /** Linux: avahi-browse all service types, filter by hostname starting with `wirenboard-`. */
  private async avahiBrowse() {
    if (process.platform !== 'linux') return
    // -a: all types, -r: resolve, -p: parsable. No -t: stay in browse mode for the whole window.
    const out = await exec('avahi-browse', ['-a', '-r', '-p'], 5000)
    for (const line of out.split('\n')) {
      if (!line.startsWith('=')) continue
      const f = line.split(';')
      // =;iface;proto;name;type;domain;hostname;address;port;txt
      const proto = f[2]
      const hostname = f[6]?.trim()
      const addr = f[7]?.trim()
      if (!hostname || !hostname.startsWith('wirenboard-')) continue
      const sn = parseSn(hostname)
      if (!sn) continue
      const existing = this.controllers.get(sn)
      const incoming = addr && isUsableAddress(addr) ? [addr] : []
      const merged: Controller = {
        sn,
        host: hostname,
        addresses: mergeAddresses(existing?.addresses ?? [], incoming),
        source: existing?.source === 'manual' ? 'manual' : 'mdns',
        reachable: true,
        lastSeen: Date.now(),
        fw: existing?.fw,
      }
      this.controllers.set(sn, merged)
      // proto used to ignore IPv6 link-local that arrives separately — filtering happens in isUsableAddress.
      void proto
    }
  }
}

function mergeAddresses(existing: string[], incoming: string[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const a of [...existing, ...incoming]) {
    if (seen.has(a)) continue
    seen.add(a)
    out.push(a)
  }
  return out
}

export { defaultHost, parseSn }
