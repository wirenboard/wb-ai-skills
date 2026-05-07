import type { Controller } from './types.ts'
import type { SshPool } from './ssh.ts'

// `printf '\n===...\n'` (instead of `echo`) guarantees a newline BEFORE the marker —
// otherwise `cat /usr/lib/wb-release` (no trailing \n) glues into the next marker:
// "REPO_PREFIX====WB-AUDIT===manual" — and the /^…$/m regex misses it.
const AUDIT_SCRIPT = [
  'printf "\\n===WB-AUDIT===fw\\n"; cat /etc/wb-fw-version 2>/dev/null || true',
  'printf "\\n===WB-AUDIT===release\\n"; cat /usr/lib/wb-release 2>/dev/null || true',
  'printf "\\n===WB-AUDIT===manual\\n"; apt-mark showmanual 2>/dev/null | sort',
  'printf "\\n===WB-AUDIT===installed\\n"; dpkg-query -W -f="${Package}\\n" 2>/dev/null | sort',
  'printf "\\n===WB-AUDIT===enabled\\n"; systemctl list-unit-files --state=enabled --no-legend 2>/dev/null | awk \'{print $1}\' | sort',
  'printf "\\n===WB-AUDIT===units\\n"; find /etc/systemd/system -maxdepth 2 -name "*.service" -type f 2>/dev/null | sort',
  'printf "\\n===WB-AUDIT===cron\\n"; for d in /etc/cron.d /etc/cron.hourly /etc/cron.daily /etc/cron.weekly /var/spool/cron/crontabs; do ls -A "$d" 2>/dev/null | grep -v "^\\.placeholder$" | sed "s|^|$d/|"; done',
  'printf "\\n===WB-AUDIT===opt\\n"; ls -A /opt 2>/dev/null',
  'printf "\\n===WB-AUDIT===localbin\\n"; ls -A /usr/local/bin 2>/dev/null',
  'printf "\\n===WB-AUDIT===localsbin\\n"; ls -A /usr/local/sbin 2>/dev/null',
  'printf "\\n===WB-AUDIT===symlinks\\n"; for p in /etc/wb-rules /etc/wb-rules-modules /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.d; do echo "$p|$(readlink -f $p 2>/dev/null)"; done',
  'printf "\\n===WB-AUDIT===mntdata\\n"; shopt -s nullglob dotglob; for d in /mnt/data/*/; do case "$(basename "$d")" in etc|var|root|snapshots|backups|uploads|.docker|ai|.wb-restore|.wb-update|lost+found) continue;; *) du -sh "$d" 2>/dev/null;; esac; done; shopt -u dotglob',
  'printf "\\n===WB-AUDIT===dpkg\\n"; dpkg --verify 2>/dev/null | grep -v -E "/usr/share/(doc|locale|man|lintian|gtk-doc|gnome|info|help)"',
  'printf "\\n===WB-AUDIT===end\\n"',
].join('; ')

export type ReleaseInfo = { name?: string; suite?: string; target?: string; repoPrefix?: string; raw: string }

export type AuditResult = {
  fw: string
  release: ReleaseInfo
  manualPackages: string[]
  installedPackages: string[]
  enabledUnits: string[]
  customUnits: string[]
  cron: string[]
  opt: string[]
  localBin: string[]
  localSbin: string[]
  symlinks: { path: string; target: string }[]
  mntDataDirs: string[]
  dpkgChanged: string[]
}

function parseRelease(s: string): ReleaseInfo {
  const out: ReleaseInfo = { raw: s }
  // Strip quotes if present: RELEASE_NAME="bullseye" → bullseye.
  const unquote = (v: string): string => v.replace(/^["']|["']$/g, '')
  for (const line of s.split('\n')) {
    const eq = line.indexOf('=')
    if (eq < 0) continue
    const k = line.slice(0, eq).trim()
    const v = unquote(line.slice(eq + 1).trim())
    if (k === 'RELEASE_NAME') out.name = v
    else if (k === 'SUITE') out.suite = v
    else if (k === 'TARGET') out.target = v
    else if (k === 'REPO_PREFIX') out.repoPrefix = v
  }
  return out
}

function parseSections(stdout: string): Record<string, string> {
  const sections: Record<string, string> = {}
  const re = /^===WB-AUDIT===([a-z]+)$/m
  const parts = stdout.split(re)
  // parts: [before-first, key1, body1, key2, body2, ...]
  for (let i = 1; i < parts.length; i += 2) {
    const key = parts[i]
    const body = (parts[i + 1] ?? '').trim()
    if (key) sections[key] = body
  }
  return sections
}

function lines(s: string | undefined): string[] {
  if (!s) return []
  return s.split('\n').map((l) => l.trim()).filter(Boolean)
}

export async function runAudit(ssh: SshPool, c: Controller): Promise<AuditResult> {
  const r = await ssh.exec(c, AUDIT_SCRIPT, 60_000)
  const s = parseSections(r.stdout)
  const symlinks = lines(s['symlinks']).map((l) => {
    const [path, target] = l.split('|')
    return { path: path ?? '', target: target ?? '' }
  })
  return {
    fw: s['fw'] ?? '',
    release: parseRelease(s['release'] ?? ''),
    manualPackages: lines(s['manual']),
    installedPackages: lines(s['installed']),
    enabledUnits: lines(s['enabled']),
    customUnits: lines(s['units']),
    cron: lines(s['cron']),
    opt: lines(s['opt']),
    localBin: lines(s['localbin']),
    localSbin: lines(s['localsbin']),
    symlinks,
    mntDataDirs: lines(s['mntdata']),
    dpkgChanged: lines(s['dpkg']),
  }
}

export type SnapshotResult = { snapshotPath: string; takenAt: string }

export async function runSnapshot(ssh: SshPool, c: Controller): Promise<SnapshotResult> {
  const a = await runAudit(ssh, c)
  const ts = new Date().toISOString().replace(/[:.]/g, '-')
  const path = `/mnt/data/ai/wb-ai-integration/snapshots/snapshot-${ts}.json`
  const payload = JSON.stringify({
    takenAt: new Date().toISOString(),
    fwVersion: a.fw,
    release: a.release,
    manualPackages: a.manualPackages,
    enabledUnits: a.enabledUnits,
    customUnits: a.customUnits,
    opt: a.opt,
    localBin: a.localBin,
    localSbin: a.localSbin,
    symlinks: a.symlinks,
  }, null, 2)
  await ssh.exec(c, 'mkdir -p /mnt/data/ai/wb-ai-integration/snapshots', 5000)
  await ssh.writeFile(c, path, payload)
  return { snapshotPath: path, takenAt: new Date().toISOString() }
}

export type DiffResult = {
  beforePath: string
  added: { packages: string[]; units: string[]; opt: string[] }
  removed: { packages: string[]; units: string[]; opt: string[] }
}

function diff(before: string[], after: string[]): { added: string[]; removed: string[] } {
  const b = new Set(before)
  const a = new Set(after)
  return {
    added: [...a].filter((x) => !b.has(x)).sort(),
    removed: [...b].filter((x) => !a.has(x)).sort(),
  }
}

export async function runDiffSnapshot(ssh: SshPool, c: Controller, beforePath: string): Promise<DiffResult> {
  const raw = await ssh.readFile(c, beforePath, 1_000_000)
  let before: { manualPackages?: string[]; enabledUnits?: string[]; opt?: string[] }
  try {
    before = JSON.parse(raw)
  } catch (e) {
    throw new Error(`runDiffSnapshot: snapshot ${beforePath} is corrupted (invalid JSON): ${(e as Error).message}`)
  }
  const a = await runAudit(ssh, c)
  const pkgs = diff(before.manualPackages ?? [], a.manualPackages)
  const units = diff(before.enabledUnits ?? [], a.enabledUnits)
  const opt = diff(before.opt ?? [], a.opt)
  return {
    beforePath,
    added: { packages: pkgs.added, units: units.added, opt: opt.added },
    removed: { packages: pkgs.removed, units: units.removed, opt: opt.removed },
  }
}
