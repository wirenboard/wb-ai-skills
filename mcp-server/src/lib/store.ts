import { existsSync, mkdirSync, readFileSync, writeFileSync, renameSync } from 'node:fs'
import { dirname } from 'node:path'
import { homedir } from 'node:os'

export type ManualEntry = { sn: string; host: string; addedAt: number }

const DEFAULT_PATH = `${homedir()}/.wb-mcp/controllers.json`

export class ManualStore {
  private path: string
  private entries: Map<string, ManualEntry> = new Map()

  constructor(path: string = DEFAULT_PATH) {
    this.path = path
    this.load()
  }

  list(): ManualEntry[] {
    return [...this.entries.values()]
  }

  add(sn: string, host: string): ManualEntry {
    const e: ManualEntry = { sn, host, addedAt: Date.now() }
    this.entries.set(sn, e)
    this.save()
    return e
  }

  remove(sn: string): boolean {
    const ok = this.entries.delete(sn)
    if (ok) this.save()
    return ok
  }

  private load() {
    if (!existsSync(this.path)) return
    try {
      const raw = JSON.parse(readFileSync(this.path, 'utf8')) as ManualEntry[]
      for (const e of raw) this.entries.set(e.sn, e)
    } catch (e) {
      console.error(`[wb-mcp] failed to load ${this.path}: ${e}`)
    }
  }

  private save() {
    // Atomic write: first to a sibling temp file, then rename.
    // Protects against partial writes if SIGINT/kill arrives mid-save.
    mkdirSync(dirname(this.path), { recursive: true })
    const tmp = `${this.path}.tmp.${process.pid}`
    writeFileSync(tmp, JSON.stringify([...this.entries.values()], null, 2))
    renameSync(tmp, this.path)
  }
}
