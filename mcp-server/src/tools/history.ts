import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { writeFile } from 'node:fs/promises'
import { type Ctx, resolveController, text, err, SN } from '../helpers.ts'
import { renderHistoryChart, type ChartType, type HistorySeries } from '../lib/history-chart.ts'

const PERIOD_RE = /^(\d+)(h|d)$/

function resolvePeriod(period: string | undefined, from: number | undefined, to: number | undefined): { from: number; to: number } {
  const now = Math.floor(Date.now() / 1000)
  const tsTo = to ?? now
  let tsFrom = from ?? 0
  if (period) {
    const m = period.match(PERIOD_RE)
    if (m) tsFrom = now - Number(m[1]) * (m[2] === 'h' ? 3600 : 86400)
  }
  return { from: tsFrom, to: tsTo }
}

function pickInterval(durationSec: number, override?: number): number {
  if (override != null) return override
  if (durationSec <= 3600) return 0
  if (durationSec <= 86400) return 60
  return 600
}

function pickLimit(durationSec: number, override?: number): number {
  if (override != null) return override
  if (durationSec <= 3600) return 200
  if (durationSec <= 86400) return 500
  return 1000
}

type HistoryRpcPoint = { device: string; control: string; t?: number; timestamp?: number; value?: string | number; min?: string | number; max?: string | number; units?: string }
type HistoryRpcResult = { values?: HistoryRpcPoint[] }

function asNum(x: string | number | undefined): number | null {
  if (x == null) return null
  const n = typeof x === 'number' ? x : Number(x)
  return Number.isFinite(n) ? n : null
}

/** Convert raw RPC response into HistorySeries[] for the chart renderer. */
function rpcToSeries(channels: [string, string][], rpc: HistoryRpcResult): HistorySeries[] {
  const map = new Map<string, HistorySeries>()
  for (const [d, c] of channels) {
    const label = `${d}/${c}`
    map.set(label, { label, points: [], min: Infinity, max: -Infinity, avg: 0 })
  }
  for (const p of rpc.values ?? []) {
    const label = `${p.device}/${p.control}`
    const s = map.get(label)
    if (!s) continue
    const t = p.t ?? p.timestamp
    const v = asNum(p.value)
    if (t == null || v == null) continue
    s.points.push({ t, v })
    const lo = asNum(p.min) ?? v
    const hi = asNum(p.max) ?? v
    if (lo < s.min) s.min = lo
    if (hi > s.max) s.max = hi
    if (p.units && !s.units) s.units = p.units
  }
  for (const s of map.values()) {
    if (!Number.isFinite(s.min)) s.min = 0
    if (!Number.isFinite(s.max)) s.max = 0
    if (s.points.length) s.avg = s.points.reduce((a, p) => a + p.v, 0) / s.points.length
  }
  return [...map.values()]
}

export function registerHistoryTools(server: McpServer, ctx: Ctx) {
  server.registerTool('wb_history', {
    description: 'Query data history from wb-mqtt-db (points + min/max/avg stats)',
    inputSchema: z.object({
      sn: SN,
      channels: z.array(z.tuple([z.string(), z.string()])).describe('Channels: [["device_id", "control_name"], ...]'),
      period: z.string().optional().describe('Period: 1h, 6h, 24h, 7d, 30d'),
      from: z.number().optional().describe('Unix timestamp of the start'),
      to: z.number().optional().describe('Unix timestamp of the end'),
      limit: z.number().optional().default(1000),
      min_interval: z.number().optional().describe('Min interval between points (sec)'),
    }),
  }, async ({ sn, channels, period, from, to, limit, min_interval }) => {
    const { from: tsFrom, to: tsTo } = resolvePeriod(period, from, to)
    const params = {
      channels,
      timestamp: { gt: tsFrom, lt: tsTo },
      limit: limit ?? 1000,
      ...(min_interval != null ? { min_interval } : {}),
    }
    return text(await ctx.ssh.mqttRpc(resolveController(ctx, sn), 'db_logger', 'history', 'get_values', params, 30))
  })

  server.registerTool('wb_history_chart', {
    description: 'Render a history chart. **By default — inline Mermaid `xychart-beta`** (linear, single Y-axis), which Claude Code renders directly in chat. Switch to `format="svg"` (or pass `outputPath`) for a Vega-Lite SVG with richer types (line/bar/area/point/histogram/heatmap/boxplot, dual Y-axis for 2 units, normalization for 3+). Suggest SVG to the user when they ask for a richer chart, want to save to a file, or need a non-line type — but start with the Mermaid default.',
    inputSchema: z.object({
      sn: SN,
      channels: z.array(z.tuple([z.string(), z.string()])).describe('Channels: [["device_id","control_name"], ...]'),
      period: z.string().optional().describe('Period: 1h, 6h, 24h, 7d, 30d (if from/to is not set)'),
      from: z.number().optional().describe('Unix timestamp of the start'),
      to: z.number().optional().describe('Unix timestamp of the end'),
      format: z.enum(['mermaid', 'svg']).optional().default('mermaid').describe('mermaid (default): inline `xychart-beta`, single Y-axis, downsampled to ~30 points. svg: Vega-Lite, richer features. Auto-switches to svg if outputPath is set.'),
      chartType: z.enum(['line','bar','area','point','histogram','heatmap','boxplot']).optional().default('line').describe('Only applies when format=svg. Default line.'),
      title: z.string().optional().default(''),
      ylabel: z.string().optional().default(''),
      outputPath: z.string().optional().describe('Only for SVG. If set, the SVG is written to this path and a short status is returned inline. Implies format=svg.'),
      limit: z.number().optional(),
      min_interval: z.number().optional().describe('Min bucket interval (sec). Default auto (0/60/600 depending on period length).'),
    }),
  }, async ({ sn, channels, period, from, to, format, chartType, title, ylabel, outputPath, limit, min_interval }) => {
    const c = resolveController(ctx, sn)
    const { from: tsFrom, to: tsTo } = resolvePeriod(period, from, to)
    if (tsTo <= tsFrom) return err(`Bad period: from=${tsFrom} >= to=${tsTo}`)
    const durationSec = tsTo - tsFrom
    const params = {
      channels,
      timestamp: { gt: tsFrom, lt: tsTo },
      min_interval: pickInterval(durationSec, min_interval),
      limit: pickLimit(durationSec, limit),
    }
    const rpc = await ctx.ssh.mqttRpc(c, 'db_logger', 'history', 'get_values', params, 30) as HistoryRpcResult
    const series = rpcToSeries(channels, rpc)
    const totalPoints = series.reduce((a, s) => a + s.points.length, 0)
    const useSvg = outputPath != null || format === 'svg'
    if (!useSvg) {
      const mermaid = renderMermaidChart(series, tsFrom, tsTo, title ?? '', ylabel ?? '')
      return text({
        format: 'mermaid',
        mermaid,
        totalPoints,
        channels: channels.length,
        from: tsFrom,
        to: tsTo,
        hint: 'Other chart types (bar/area/point/histogram/heatmap/boxplot) and dual Y-axis are available with format="svg".',
      })
    }
    const svg = await renderHistoryChart(series, tsFrom, tsTo, title ?? '', ylabel ?? '', chartType as ChartType)
    if (outputPath) {
      await writeFile(outputPath, svg, 'utf8')
      return text({ ok: true, format: 'svg', outputPath, svgBytes: svg.length, totalPoints, channels: channels.length, from: tsFrom, to: tsTo })
    }
    if (svg.length > 200_000) {
      return err(`SVG too large (${svg.length} bytes) for an inline response. Pass outputPath to write it to a file, or shorten the period / reduce the channel count.`)
    }
    return text({ format: 'svg', svg, svgBytes: svg.length, totalPoints, channels: channels.length, from: tsFrom, to: tsTo })
  })
}

/** Render a series collection as Mermaid `xychart-beta`. Single Y-axis (Mermaid limitation),
 *  downsampled to MAX_POINTS so the chat renders cleanly. For multi-series of the same unit,
 *  emits multiple `line [...]`. */
function renderMermaidChart(series: HistorySeries[], from: number, to: number, title: string, ylabel: string): string {
  const MAX_POINTS = 30
  const useDate = (to - from) > 86400  // > 24h → include MM-DD
  const fmt = (t: number) => {
    const d = new Date(t * 1000)
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    if (!useDate) return `${hh}:${mm}`
    const mo = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    return `${mo}-${dd} ${hh}:${mm}`
  }

  const nonEmpty = series.filter((s) => s.points.length > 0)
  if (nonEmpty.length === 0) {
    return `xychart-beta\n  title "${title || '(no data)'}"\n  x-axis []\n  y-axis "${ylabel || ''}" 0 --> 1`
  }

  const primary = nonEmpty[0]!
  const step = Math.max(1, Math.ceil(primary.points.length / MAX_POINTS))
  const keepIdx = primary.points.map((_, i) => i).filter((i) => i % step === 0)
  const xLabels = keepIdx.map((i) => `"${fmt(primary.points[i]!.t)}"`)

  const allVals = nonEmpty.flatMap((s) => s.points.map((p) => p.v))
  let yMin = Math.min(...allVals)
  let yMax = Math.max(...allVals)
  const span = yMax - yMin
  const pad = span > 0 ? span * 0.1 : Math.max(1, Math.abs(yMax) * 0.1)
  yMin -= pad
  yMax += pad

  const lines: string[] = []
  lines.push('xychart-beta')
  if (title) lines.push(`  title "${title.replace(/"/g, "'")}"`)
  lines.push(`  x-axis [${xLabels.join(', ')}]`)
  lines.push(`  y-axis "${(ylabel || '').replace(/"/g, "'")}" ${yMin.toFixed(2)} --> ${yMax.toFixed(2)}`)
  for (const s of nonEmpty) {
    // Each series is independently downsampled (it may have a different cadence than the primary).
    const sStep = Math.max(1, Math.ceil(s.points.length / MAX_POINTS))
    const vals = s.points.filter((_, i) => i % sStep === 0).map((p) => Number.isFinite(p.v) ? p.v.toFixed(2) : '0')
    lines.push(`  line [${vals.join(', ')}]`)
  }
  return lines.join('\n')
}
