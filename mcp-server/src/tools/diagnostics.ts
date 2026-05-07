import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { type Ctx, resolveController, text, SN } from '../helpers.ts'
import { shellQuote } from '../lib/shell.ts'

export function registerDiagnosticTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_metrics', {
    description: 'Метрики контроллера: нагрузка, память, диск',
    inputSchema: z.object({ sn: SN }),
  }, async ({ sn }) => {
    return text(await ctx.ssh.getMetrics(resolveController(ctx, sn)))
  })

  server.registerTool('wb_logs', {
    description: 'Логи сервиса через journalctl. Окно времени — `since`/`until` (как у systemd: "1h ago", "today", "10 minutes ago", ISO-таймстамп). Фильтр по подстроке/regex — `grep` (включить) или `grepInvert` (исключить). `lines` — hard-cap.',
    inputSchema: z.object({
      sn: SN,
      unit: z.string().optional().describe('systemd-юнит (wb-mqtt-serial, wb-rules, mosquitto)'),
      lines: z.number().optional().default(100).describe('Hard-cap на число строк (после фильтров). По умолчанию 100.'),
      priority: z.string().optional().describe('Фильтр приоритета: err, warning, info, debug. Включает все более серьёзные.'),
      since: z.string().optional().describe('Начало окна: "1h ago", "today", "10 minutes ago", "2026-05-07 12:00", или ISO-таймстамп.'),
      until: z.string().optional().describe('Конец окна (тот же формат, что и since).'),
      grep: z.string().optional().describe('Включить только строки, matched по regex (PCRE).'),
      grepInvert: z.string().optional().describe('Исключить строки, matched по regex.'),
    }),
  }, async ({ sn, unit, lines, priority, since, until, grep, grepInvert }) => {
    return text(await ctx.ssh.readLogs(resolveController(ctx, sn), { unit, lines, priority, since, until, grep, grepInvert }))
  })

  server.registerTool('wb_failed', {
    description: 'Список упавших systemd-сервисов (systemctl --failed)',
    inputSchema: z.object({ sn: SN }),
  }, async ({ sn }) => {
    const r = await ctx.ssh.exec(resolveController(ctx, sn), 'systemctl --failed --no-pager', 10000)
    return text(r.stdout)
  })

  server.registerTool('wb_systemd_unit', {
    description: 'Управление и инспекция systemd-юнита: status (parsed), start/stop/restart/reload/enable/disable/mask/unmask, cat (содержимое юнита со всеми drop-ins), list-deps. По умолчанию action="status" — структурированный объект {active, sub, load, unitFileState, exitCode, mainPid, since, ...}. Для status передай только sn+unit; для action — sn+unit+action.',
    inputSchema: z.object({
      sn: SN,
      unit: z.string().describe('systemd-юнит (wb-mqtt-serial.service, fstrim.timer, mosquitto). Расширение .service можно опустить.'),
      action: z.enum(['status', 'start', 'stop', 'restart', 'reload', 'enable', 'disable', 'mask', 'unmask', 'cat', 'list-deps']).optional().default('status'),
    }),
  }, async ({ sn, unit, action }) => {
    const c = resolveController(ctx, sn)
    if (!/^[A-Za-z0-9@._:\\-]+$/.test(unit)) return text({ error: `Invalid unit name "${unit}". Allowed: A-Za-z0-9, @, ., _, :, -.` })
    const u = shellQuote(unit)
    if (action === 'status') {
      const sh = `systemctl is-active ${u} 2>/dev/null || true; echo ===WB-SD===; systemctl show ${u} -p ActiveState,LoadState,SubState,UnitFileState,Result,ExecMainStatus,ExecMainExitTimestamp,ExecMainPID,ActiveEnterTimestamp --no-pager 2>/dev/null || true; echo ===WB-SD===; systemctl status ${u} --no-pager -n 5 2>&1 || true`
      const r = await ctx.ssh.exec(c, sh, 10000)
      const parts = r.stdout.split('===WB-SD===')
      const active = (parts[0] ?? '').trim()
      const props: Record<string, string> = {}
      for (const line of (parts[1] ?? '').split('\n')) {
        const eq = line.indexOf('=')
        if (eq > 0) props[line.slice(0, eq).trim()] = line.slice(eq + 1).trim()
      }
      const tail = (parts[2] ?? '').trim()
      return text({
        unit,
        active,
        loadState: props['LoadState'],
        subState: props['SubState'],
        unitFileState: props['UnitFileState'],
        result: props['Result'],
        exitCode: props['ExecMainStatus'] ? Number(props['ExecMainStatus']) : undefined,
        mainPid: props['ExecMainPID'] && props['ExecMainPID'] !== '0' ? Number(props['ExecMainPID']) : undefined,
        activeSince: props['ActiveEnterTimestamp'],
        exitedAt: props['ExecMainExitTimestamp'],
        statusTail: tail,
      })
    }
    if (action === 'cat') {
      const r = await ctx.ssh.exec(c, `systemctl cat ${u} 2>&1`, 10000)
      return text({ unit, content: r.stdout, ok: r.code === 0 })
    }
    if (action === 'list-deps') {
      const r = await ctx.ssh.exec(c, `systemctl list-dependencies ${u} --no-pager 2>&1`, 10000)
      return text({ unit, dependencies: r.stdout, ok: r.code === 0 })
    }
    const r = await ctx.ssh.exec(c, `systemctl ${action} ${u} 2>&1; echo ===CODE=$?`, 30000)
    const m = r.stdout.match(/===CODE=(\d+)/)
    const code = m ? Number(m[1]) : -1
    const output = m ? r.stdout.slice(0, r.stdout.lastIndexOf('===CODE=')).trim() : r.stdout
    return text({ unit, action, exitCode: code, ok: code === 0, output })
  })

  server.registerTool('wb_network_status', {
    description: 'Сетевая картина контроллера: интерфейсы (ip -j), активные NetworkManager-соединения, default route, опционально ping в интернет. Свёрнутый ответ — то, что обычно нужно для диагностики «инет отвалился».',
    inputSchema: z.object({
      sn: SN,
      pingTarget: z.string().optional().describe('Если задан — пинговать `ping -c1 -W2 <target>` (например 8.8.8.8). Иначе пропустить.'),
    }),
  }, async ({ sn, pingTarget }) => {
    const c = resolveController(ctx, sn)
    // Whitelist hostname/IP characters (RFC 1035 + IPv6) — shellQuote сверху как страховка.
    const safeTarget = pingTarget ? pingTarget.replace(/[^A-Za-z0-9.:_-]/g, '') : ''
    const sh = [
      'echo ===IP===',
      'ip -j -4 addr show 2>/dev/null',
      'echo ===ROUTE===',
      'ip -j -4 route show default 2>/dev/null',
      'echo ===NM===',
      "nmcli -t -f NAME,UUID,TYPE,DEVICE,STATE connection show 2>/dev/null",
      'echo ===NM_DEV===',
      "nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device 2>/dev/null",
      ...(safeTarget ? ['echo ===PING===', `ping -c1 -W2 ${shellQuote(safeTarget)} 2>&1 | tail -2`] : []),
    ].join('; ')
    const r = await ctx.ssh.exec(c, sh, 15000)
    const sec = (label: string) => {
      const start = r.stdout.indexOf(`===${label}===`)
      if (start < 0) return ''
      const after = start + label.length + 6
      const next = r.stdout.indexOf('\n===', after)
      return r.stdout.slice(after, next < 0 ? undefined : next).trim()
    }
    let interfaces: any[] = []
    try { interfaces = JSON.parse(sec('IP') || '[]') } catch {}
    let defaultRoute: any[] = []
    try { defaultRoute = JSON.parse(sec('ROUTE') || '[]') } catch {}
    const nmConnections = sec('NM').split('\n').filter(Boolean).map((l) => {
      const [name, uuid, type, device, state] = l.split(':')
      return { name, uuid, type, device, state }
    })
    const nmDevices = sec('NM_DEV').split('\n').filter(Boolean).map((l) => {
      const [device, type, state, connection] = l.split(':')
      return { device, type, state, connection }
    })
    const out: Record<string, unknown> = {
      interfaces: interfaces.map((i: any) => ({
        name: i.ifname,
        state: i.operstate,
        mtu: i.mtu,
        ipv4: (i.addr_info ?? []).map((a: any) => `${a.local}/${a.prefixlen}`),
      })),
      defaultRoute: defaultRoute[0] ? { gateway: defaultRoute[0].gateway, dev: defaultRoute[0].dev } : null,
      nmConnections,
      nmDevices,
    }
    if (safeTarget) {
      const ping = sec('PING')
      const m = ping.match(/(\d+)% packet loss/)
      out.ping = { target: safeTarget, raw: ping, lossPct: m ? Number(m[1]) : undefined, reachable: m ? Number(m[1]) === 0 : undefined }
    }
    return text(out)
  })

  server.registerTool('wb_cloud_status', {
    description: 'Состояние Wiren Board Cloud-агента: активность сервиса wb-cloud-agent, MQTT-статус (`/devices/system__wb-cloud-agent__*/controls/{status,activation_link,cloud_base_url}`), наличие сертификата устройства. Один вызов — всё что нужно понять, цеплят ли контроллер к облаку.',
    inputSchema: z.object({ sn: SN }),
  }, async ({ sn }) => {
    const c = resolveController(ctx, sn)
    const sh = [
      'echo ===SVC===',
      'systemctl is-active wb-cloud-agent 2>/dev/null || true',
      'echo ===CONF===',
      'cat /etc/wb-cloud-agent.conf 2>/dev/null || true',
      'echo ===CERT===',
      'ls -1 /var/lib/wb-cloud-agent/device_bundle.crt.pem 2>/dev/null && echo cert-present || echo cert-missing',
      'echo ===PROVIDERS===',
      'ls /var/lib/wb-cloud-agent/providers/ 2>/dev/null || true',
      'echo ===MQTT===',
      // `system__wb-cloud-agent__+` — невалидный wildcard (+ должен занимать весь уровень между /).
      // Берём всё /devices/+/controls/+ и фильтруем на стороне TS.
      "timeout 3 mosquitto_sub -F '%t\\t%p' -t '/devices/+/controls/+' 2>/dev/null | grep '^/devices/system__wb-cloud-agent__' || true",
    ].join('; ')
    const r = await ctx.ssh.exec(c, sh, 15000)
    const sec = (label: string) => {
      const start = r.stdout.indexOf(`===${label}===`)
      if (start < 0) return ''
      const after = start + label.length + 6
      const next = r.stdout.indexOf('\n===', after)
      return r.stdout.slice(after, next < 0 ? undefined : next).trim()
    }
    let conf: Record<string, unknown> | null = null
    try { conf = JSON.parse(sec('CONF') || 'null') } catch {}
    const mqttLines = sec('MQTT').split('\n').filter(Boolean)
    const mqtt: Record<string, Record<string, string>> = {}
    for (const line of mqttLines) {
      const tab = line.indexOf('\t')
      if (tab < 0) continue
      const topic = line.slice(0, tab)
      const payload = line.slice(tab + 1)
      const m = topic.match(/^\/devices\/(system__wb-cloud-agent__[^/]+)\/controls\/([^/]+?)(?:\/meta(?:\/.+)?)?$/)
      if (!m) continue
      const provider = m[1]!
      const control = m[2]!
      if (topic.endsWith('/meta') || topic.includes('/meta/')) continue
      mqtt[provider] = mqtt[provider] ?? {}
      mqtt[provider][control] = payload
    }
    return text({
      serviceActive: sec('SVC').trim() === 'active',
      certPresent: sec('CERT').includes('cert-present'),
      providers: sec('PROVIDERS').split('\n').filter(Boolean),
      conf,
      mqtt,
    })
  })

  server.registerTool('wb_serial_debug', {
    description: 'Собрать raw RS-485 пакеты для диагностики. Включает debug в /etc/wb-mqtt-serial.conf, рестартует драйвер, собирает journalctl за период, потом гарантированно выключает debug и рестартует обратно (даже при ошибке посередине, через trap).',
    inputSchema: z.object({
      sn: SN,
      duration: z.number().min(10).max(300).default(60).describe('Длительность в секундах'),
    }),
  }, async ({ sn, duration }) => {
    const c = resolveController(ctx, sn)
    const script = [
      'set -e',
      'CONF=/etc/wb-mqtt-serial.conf',
      'LOGFILE=/mnt/data/ai/wb-ai-integration/diag/debug-serial.log',
      'mkdir -p /mnt/data/ai/wb-ai-integration/diag',
      // trap: что бы ни случилось дальше — вернуть debug:false и перезапустить драйвер.
      'restore_off() { python3 -c "import json; c=json.load(open(\\"$CONF\\")); c[\\"debug\\"]=False; json.dump(c,open(\\"$CONF\\",\\"w\\"),indent=2)" 2>/dev/null || true; systemctl restart wb-mqtt-serial >/dev/null 2>&1 || true; echo "[wb_serial_debug] restored debug:false"; }',
      'trap restore_off EXIT INT TERM',
      `python3 -c "import json; c=json.load(open('$CONF')); c['debug']=True; json.dump(c,open('$CONF','w'),indent=2)"`,
      'systemctl restart wb-mqtt-serial',
      'sleep 1',
      'START_TS=$(date -u +%Y-%m-%dT%H:%M:%S)',
      `echo "[wb_serial_debug] collecting ${duration}s from $START_TS"`,
      `sleep ${duration}`,
      // Без -n: пишем весь журнал за окно. -n 500 молча режет на быстрых шинах.
      'journalctl -u wb-mqtt-serial --since "$START_TS" --no-pager > "$LOGFILE"',
      'echo "[wb_serial_debug] saved $(wc -l < "$LOGFILE") lines to $LOGFILE"',
    ].join('; ')
    const job = await ctx.ssh.jobStart(c, script, 'serial debug collect')
    return text({
      jobId: job.jobId,
      logPath: '/mnt/data/ai/wb-ai-integration/diag/debug-serial.log',
      message: `Debug-сбор запущен на ${duration} сек. Используй wb_job_status / wb_job_tail для прогресса. После завершения логи: wb_read_file path=/mnt/data/ai/wb-ai-integration/diag/debug-serial.log (или scp если >64 КБ).`,
    })
  })
}
