import { spawn } from 'node:child_process'
import type { Controller, ExecResult, SshAuth } from './types.ts'
import { shellQuote } from './shell.ts'

const DEFAULT_TIMEOUT = 30_000
const SHORT_TIMEOUT = 10_000

/** SshPool is a stateless command runner — each call spawns its own ssh subprocess.
 *  No persistent connection multiplexing. If perf becomes an issue, add ControlMaster. */
export class SshPool {
  constructor(private auth: SshAuth) {}

  /** Run a remote command. Throws only on spawn errors; non-zero exit returns code in result. */
  async exec(c: Controller, command: string, timeoutMs: number = DEFAULT_TIMEOUT): Promise<ExecResult> {
    const target = pickTarget(c)
    const baseArgs = sshArgs(this.auth, target)
    const { cmd, args, env } = wrapAuth(this.auth, baseArgs)
    args.push(command)
    return runProcess(cmd, args, timeoutMs, undefined, env)
  }

  /** Read up to maxBytes from a remote file. Throws if file doesn't exist or read fails. */
  async readFile(c: Controller, path: string, maxBytes: number = 64_000): Promise<string> {
    const escaped = shellQuote(path)
    const r = await this.exec(c, `head -c ${maxBytes + 1} ${escaped}`, SHORT_TIMEOUT)
    if (r.code !== 0) throw new Error(`readFile ${path}: ${r.stderr.trim() || `exit ${r.code}`}`)
    if (r.stdout.length > maxBytes) {
      throw new Error(`readFile ${path}: file larger than ${maxBytes} bytes`)
    }
    return r.stdout
  }

  /** Write content to a remote file via stdin → cat. Creates parent dirs implicitly only if they exist. */
  async writeFile(c: Controller, path: string, content: string): Promise<void> {
    const target = pickTarget(c)
    const baseArgs = sshArgs(this.auth, target)
    const { cmd, args, env } = wrapAuth(this.auth, baseArgs)
    args.push(`cat > ${shellQuote(path)}`)
    const r = await runProcess(cmd, args, DEFAULT_TIMEOUT, content, env)
    if (r.code !== 0) throw new Error(`writeFile ${path}: ${r.stderr.trim() || `exit ${r.code}`}`)
  }

  /** Publish a single MQTT message via mosquitto_pub on the controller. */
  async mqttPublish(c: Controller, topic: string, payload: string, opts: { retain?: boolean; qos?: 0 | 1 | 2 } = {}): Promise<void> {
    const t = shellQuote(topic)
    const p = shellQuote(payload)
    const flags: string[] = []
    if (opts.retain) flags.push('-r')
    if (opts.qos != null) flags.push('-q', String(opts.qos))
    const r = await this.exec(c, `mosquitto_pub ${flags.join(' ')} -t ${t} -m ${p}`, SHORT_TIMEOUT)
    if (r.code !== 0) throw new Error(`mqtt publish ${topic}: ${r.stderr.trim() || `exit ${r.code}`}`)
  }

  /** Read a single retained MQTT message (-C 1). Returns trimmed payload or null on timeout.
   *  Surfaces invalid-topic errors (e.g. '+' inside a level) instead of returning null. */
  async mqttRead(c: Controller, topic: string, timeoutSec: number = 5): Promise<string | null> {
    const t = shellQuote(topic)
    const r = await this.exec(c, `mosquitto_sub -t ${t} -C 1 -W ${timeoutSec}`, (timeoutSec + 5) * 1000)
    if (r.stderr.includes('Invalid subscription topic')) {
      throw new Error(`mqtt read: invalid topic "${topic}". В MQTT '+' и '#' — wildcards уровней целиком, между '/'.`)
    }
    const v = r.stdout.replace(/\n$/, '')
    return v === '' ? null : v
  }

  /** Subscribe with `-W <timeoutSec>` and parse "topic\tpayload" pairs.
   *  WB control names may contain spaces (e.g. WB-MR6C "Input 0", "Input 0 counter"),
   *  so we use TAB as the field separator instead of mosquitto_sub -v.
   *  Captures stderr separately to surface invalid-topic errors (e.g. `+` inside a level).
   *
   *  Limitation: line-based parsing. If payload contains `\n`, the message will split
   *  across lines and lose its topic — known case for WB is `meta`-JSON payloads,
   *  but mosquitto_sub renders them as single-line JSON, so это не задевает. */
  async mqttListTopics(c: Controller, prefix: string, timeoutSec: number = 3): Promise<{ topic: string; payload: string }[]> {
    const t = shellQuote(prefix)
    const cmd = `mosquitto_sub -F '%t\\t%p' -t ${t} -W ${timeoutSec}`
    const r = await this.exec(c, cmd, (timeoutSec + 5) * 1000)
    if (r.stderr.includes('Invalid subscription topic')) {
      throw new Error(`mqtt list: invalid topic "${prefix}". В MQTT '+' и '#' — wildcards уровней целиком, между '/'. Например '/devices/+/meta/name' OK, а '/devices/foo__+/bar' — нельзя.`)
    }
    const out: { topic: string; payload: string }[] = []
    for (const line of r.stdout.split('\n')) {
      if (!line) continue
      const tab = line.indexOf('\t')
      if (tab < 0) { out.push({ topic: line, payload: '' }); continue }
      out.push({ topic: line.slice(0, tab), payload: line.slice(tab + 1) })
    }
    return out
  }

  /** RPC over MQTT: subscribe to reply, publish request, parse JSON response.
   *  Все user-controlled куски топика и payload проходят через shellQuote — даже
   *  для «доверенных» драйверов это страховка от случайных `'`/`$()` в имени. */
  async mqttRpc(c: Controller, driver: string, service: string, method: string, params: unknown, timeoutSec: number = 10): Promise<unknown> {
    const id = randomId()
    const req = { id: 1, params }
    const reqJson = JSON.stringify(req)
    const replyTopic = `/rpc/v1/${driver}/${service}/${method}/${id}/reply`
    const reqTopic = `/rpc/v1/${driver}/${service}/${method}/${id}`
    // Subscribe in background, sleep 0.2s to ensure subscription is active, publish, wait.
    const sh = `mosquitto_sub -t ${shellQuote(replyTopic)} -C 1 -W ${timeoutSec} & SUB=$!; sleep 0.2; mosquitto_pub -t ${shellQuote(reqTopic)} -m ${shellQuote(reqJson)}; wait $SUB`
    const r = await this.exec(c, sh, (timeoutSec + 5) * 1000)
    const out = r.stdout.trim()
    if (!out) throw new Error(`mqtt rpc ${driver}/${service}/${method}: timeout (no reply in ${timeoutSec}s)`)
    let parsed: unknown
    try { parsed = JSON.parse(out) } catch { throw new Error(`mqtt rpc reply not JSON: ${out.slice(0, 200)}`) }
    return (parsed as { error?: unknown; result?: unknown }).result ?? parsed
  }

  async readLogs(c: Controller, opts: { unit?: string; lines?: number; priority?: string; since?: string; until?: string; grep?: string; grepInvert?: string } = {}): Promise<string> {
    const args: string[] = ['journalctl', '--no-pager']
    if (opts.unit) args.push('-u', shellQuote(opts.unit))
    if (opts.priority) args.push('-p', shellQuote(opts.priority))
    if (opts.since) args.push('--since', shellQuote(opts.since))
    if (opts.until) args.push('--until', shellQuote(opts.until))
    if (opts.grep) args.push('--grep', shellQuote(opts.grep))
    if (opts.grepInvert) args.push('--grep', shellQuote(opts.grepInvert), '--invert-grep')
    if (opts.lines != null) args.push('-n', String(opts.lines))
    const r = await this.exec(c, args.join(' '), 30_000)
    return r.stdout
  }

  async getInfo(c: Controller): Promise<Record<string, string>> {
    // Unique delimiter survives content without trailing newline.
    const D = '===WBI==='
    const sec = (label: string, cmd: string) => `printf '\\n${D}${label}\\n'; ${cmd}`
    const script = [
      sec('HOST', 'hostname'),
      sec('UNAME', 'uname -a'),
      sec('UPTIME', 'uptime'),
      sec('RELEASE', 'cat /usr/lib/wb-release 2>/dev/null || true'),
      sec('FW', 'cat /etc/wb-fw-version 2>/dev/null || true'),
      sec('SN', 'cat /var/lib/wirenboard/short_sn.conf 2>/dev/null || true'),
    ].join('; ')
    const r = await this.exec(c, script, SHORT_TIMEOUT)
    const get = (label: string): string => extractSection(r.stdout, D, label)
    return {
      sn: get('SN') || c.sn,
      hostname: get('HOST'),
      uname: get('UNAME'),
      uptime: get('UPTIME'),
      release: get('RELEASE'),
      fwVersion: get('FW'),
    }
  }

  async getMetrics(c: Controller): Promise<Record<string, unknown>> {
    const D = '===WBM==='
    const sec = (label: string, cmd: string) => `printf '\\n${D}${label}\\n'; ${cmd}`
    const script = [
      sec('LOAD', 'cat /proc/loadavg'),
      sec('MEM', 'free -m | sed -n "2p"'),
      sec('ROOT', 'df -h / | tail -1'),
      sec('MNT', 'df -h /mnt/data 2>/dev/null | tail -1'),
    ].join('; ')
    const r = await this.exec(c, script, SHORT_TIMEOUT)
    const get = (label: string): string => extractSection(r.stdout, D, label)
    const load = get('LOAD').split(/\s+/)
    const mem = get('MEM').split(/\s+/)
    const root = get('ROOT').split(/\s+/)
    const mnt = get('MNT').split(/\s+/)
    return {
      loadAvg: { one: parseFloat(load[0] || '0'), five: parseFloat(load[1] || '0'), fifteen: parseFloat(load[2] || '0') },
      memMiB: { total: parseInt(mem[1] || '0', 10), used: parseInt(mem[2] || '0', 10), free: parseInt(mem[3] || '0', 10) },
      diskRoot: { total: root[1] || '', used: root[2] || '', free: root[3] || '', usePct: root[4] || '' },
      diskMntData: mnt[1] ? { total: mnt[1], used: mnt[2] || '', free: mnt[3] || '', usePct: mnt[4] || '' } : null,
    }
  }

  /** Start a background command via systemd-run.
   *  Подход: команда → /mnt/data/ai/wb-ai-integration/jobs/<id>.sh, лог через
   *  systemd `StandardOutput=append:` (не shell-redirect). Никакого shell-quoting,
   *  никакого риска со слипанием `;` в `bash -c '… > LOG'`. Скрипт сохранён —
   *  jobStatus может его показать. Старые .sh/.log gc-ятся по TTL. */
  async jobStart(c: Controller, command: string, label?: string): Promise<{ jobId: string; startedAt: string }> {
    if (!command.trim()) throw new Error('jobStart: empty command')
    // GC старых job-файлов (best effort)
    void this.exec(c, `find ${JOB_DIR} -maxdepth 1 -type f -mmin +${Math.floor(JOB_TTL_SEC / 60)} -delete 2>/dev/null || true`, SHORT_TIMEOUT).catch(() => {})
    const id = randomId()
    const unit = `${JOB_UNIT_PREFIX}${id}`
    const scriptPath = `${JOB_DIR}/${id}.sh`
    const logPath = `${JOB_DIR}/${id}.log`
    const labelPath = `${JOB_DIR}/${id}.label`
    const startedAtPath = `${JOB_DIR}/${id}.started`
    const scriptContent = `#!/bin/bash\nset -o pipefail\n${command}\n`
    await this.exec(c, `mkdir -p ${JOB_DIR}`, SHORT_TIMEOUT)
    await this.writeFile(c, scriptPath, scriptContent)
    if (label) await this.writeFile(c, labelPath, label)
    await this.exec(c, `chmod +x ${shellQuote(scriptPath)}`, SHORT_TIMEOUT)
    const descrSafe = (label ? `wb-ai-job ${id} ${label}` : `wb-ai-job ${id}`).slice(0, 120).replace(/['"\\]/g, '')
    const runCmd =
      `date +%s > ${startedAtPath} && ` +
      `systemd-run --unit=${unit} --collect --quiet ` +
      `--description='${descrSafe}' ` +
      `-p StandardOutput=append:${logPath} ` +
      `-p StandardError=append:${logPath} ` +
      `-p WorkingDirectory=/root ` +
      `/bin/bash ${shellQuote(scriptPath)}`
    const r = await this.exec(c, runCmd, SHORT_TIMEOUT)
    if (r.code !== 0) throw new Error(`jobStart: ${r.stderr.trim() || `exit ${r.code}`}`)
    return { jobId: id, startedAt: new Date().toISOString() }
  }

  async jobStatus(c: Controller, jobId: string): Promise<Record<string, unknown>> {
    if (!/^[a-z0-9]+$/i.test(jobId)) throw new Error(`jobStatus: invalid jobId ${jobId}`)
    const unit = `${JOB_UNIT_PREFIX}${jobId}`
    const sh = [
      `systemctl is-active ${unit} 2>/dev/null || true`,
      `echo ===WB-JS===`,
      `systemctl show ${unit} -p ActiveState,Result,ExecMainStatus,ExecMainExitTimestamp --no-pager 2>/dev/null || true`,
      `echo ===WB-JS===`,
      `cat ${JOB_DIR}/${jobId}.label 2>/dev/null || true`,
      `echo ===WB-JS===`,
      `cat ${JOB_DIR}/${jobId}.started 2>/dev/null || true`,
      `echo ===WB-JS===`,
      `wc -l < ${JOB_DIR}/${jobId}.log 2>/dev/null || echo 0`,
    ].join('; ')
    const r = await this.exec(c, sh, SHORT_TIMEOUT)
    const parts = r.stdout.split('===WB-JS===')
    const isActive = (parts[0] ?? '').trim()
    const props: Record<string, string> = {}
    for (const line of (parts[1] ?? '').split('\n')) {
      const eq = line.indexOf('=')
      if (eq > 0) props[line.slice(0, eq)] = line.slice(eq + 1)
    }
    const lbl = (parts[2] ?? '').trim()
    const startedTs = parseInt((parts[3] ?? '').trim(), 10)
    const lineCount = parseInt((parts[4] ?? '').trim(), 10) || 0
    return {
      jobId,
      active: isActive,
      result: props['Result'],
      exitCode: props['ExecMainStatus'] ? parseInt(props['ExecMainStatus'], 10) : undefined,
      exitedAt: props['ExecMainExitTimestamp'],
      label: lbl || undefined,
      startedAt: Number.isFinite(startedTs) && startedTs > 0 ? new Date(startedTs * 1000).toISOString() : undefined,
      logLines: lineCount,
      logPath: `${JOB_DIR}/${jobId}.log`,
    }
  }

  async jobTail(c: Controller, jobId: string, fromLine: number = 1, maxLines: number = 500): Promise<{ lines: string[]; totalLines: number }> {
    if (!/^[a-z0-9]+$/i.test(jobId)) throw new Error(`jobTail: invalid jobId ${jobId}`)
    const log = `${JOB_DIR}/${jobId}.log`
    const sh = `awk 'NR>=${fromLine} && NR<${fromLine + maxLines}' ${log} 2>/dev/null || true; echo ---; wc -l < ${log} 2>/dev/null || echo 0`
    const r = await this.exec(c, sh, SHORT_TIMEOUT)
    const idx = r.stdout.lastIndexOf('---')
    const body = idx >= 0 ? r.stdout.slice(0, idx) : r.stdout
    const total = idx >= 0 ? parseInt(r.stdout.slice(idx + 3).trim(), 10) || 0 : 0
    const lines = body.split('\n').filter((l, i, arr) => !(i === arr.length - 1 && l === ''))
    return { lines, totalLines: total }
  }

  async jobCancel(c: Controller, jobId: string): Promise<void> {
    if (!/^[a-z0-9]+$/i.test(jobId)) throw new Error(`jobCancel: invalid jobId ${jobId}`)
    const unit = `${JOB_UNIT_PREFIX}${jobId}`
    await this.exec(c, `systemctl stop ${unit} 2>/dev/null || true`, SHORT_TIMEOUT)
  }
}

const JOB_DIR = '/mnt/data/ai/wb-ai-integration/jobs'
const JOB_UNIT_PREFIX = 'wb-ai-job-'
const JOB_TTL_SEC = 24 * 3600

// ---- helpers ----

function pickTarget(c: Controller): string {
  // Prefer first usable address (filtered upstream), fall back to host.
  return c.addresses[0] ?? c.host
}

function sshArgs(auth: SshAuth, target: string): string[] {
  // StrictHostKeyChecking=no + UserKnownHostsFile=/dev/null — host-key контроллера МЕНЯЕТСЯ
  // после factoryreset/FIT-прошивки. С `accept-new` или строгой проверкой ssh упал бы
  // на «REMOTE HOST IDENTIFICATION HAS CHANGED!», и MCP застрял бы. WB-контроллер
  // в локальной сети — доверенная среда; проверка hostkey бесполезна и мешает.
  // LogLevel=ERROR глушит «Warning: Permanently added ... to the list of known hosts.»
  const args = [
    '-o', 'StrictHostKeyChecking=no',
    '-o', 'UserKnownHostsFile=/dev/null',
    '-o', 'LogLevel=ERROR',
    '-o', 'ConnectTimeout=5',
    '-o', 'BatchMode=' + (auth.password ? 'no' : 'yes'),
    '-o', 'NumberOfPasswordPrompts=1',
  ]
  if (auth.keyPath) { args.push('-i', auth.keyPath) }
  args.push(`${auth.user}@${target}`)
  return args
}

/** If password auth: prefix `sshpass -e ssh ...`, pass password via SSHPASS env. */
function wrapAuth(auth: SshAuth, sshArgList: string[]): { cmd: string; args: string[]; env: NodeJS.ProcessEnv } {
  if (auth.password && !auth.keyPath) {
    return {
      cmd: 'sshpass',
      args: ['-e', 'ssh', ...sshArgList],
      env: { ...process.env, SSHPASS: auth.password },
    }
  }
  return { cmd: 'ssh', args: sshArgList, env: { ...process.env } }
}

function runProcess(cmd: string, args: string[], timeoutMs: number, stdinData?: string, env: NodeJS.ProcessEnv = process.env): Promise<ExecResult> {
  return new Promise((resolve) => {
    const p = spawn(cmd, args, { env, stdio: ['pipe', 'pipe', 'pipe'] })
    let stdout = ''
    let stderr = ''
    p.stdout.on('data', (d) => { stdout += String(d) })
    p.stderr.on('data', (d) => { stderr += String(d) })
    const t = setTimeout(() => p.kill('SIGTERM'), timeoutMs)
    p.on('close', (code) => {
      clearTimeout(t)
      resolve({ stdout, stderr, code: code ?? -1 })
    })
    p.on('error', (e) => {
      clearTimeout(t)
      resolve({ stdout, stderr: stderr + String(e), code: -1 })
    })
    if (stdinData !== undefined) {
      p.stdin.write(stdinData)
    }
    p.stdin.end()
  })
}

/** Extract a section between unique delimiter markers `<D><LABEL>\n...<D><NEXT>` or end-of-string. */
function extractSection(stdout: string, delim: string, label: string): string {
  const start = stdout.indexOf(`${delim}${label}\n`)
  if (start < 0) return ''
  const bodyStart = start + delim.length + label.length + 1
  const next = stdout.indexOf(delim, bodyStart)
  const end = next < 0 ? stdout.length : next
  return stdout.slice(bodyStart, end).trim()
}

function randomId(): string {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
  let out = ''
  for (let i = 0; i < 8; i++) out += chars[Math.floor(Math.random() * chars.length)]
  return out
}
