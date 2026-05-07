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
    description: 'Render an SVG history chart via Vega-Lite. Supports: line, bar, area, point, histogram, heatmap, boxplot. For 2 different units it draws a dual Y-axis; for 3+ it normalizes to [0;1] with a range legend. Large SVGs (>50 KB) — save to outputPath.',
    inputSchema: z.object({
      sn: SN,
      channels: z.array(z.tuple([z.string(), z.string()])).describe('Channels: [["device_id","control_name"], ...]'),
      period: z.string().optional().describe('Period: 1h, 6h, 24h, 7d, 30d (if from/to is not set)'),
      from: z.number().optional().describe('Unix timestamp of the start'),
      to: z.number().optional().describe('Unix timestamp of the end'),
      chartType: z.enum(['line','bar','area','point','histogram','heatmap','boxplot']).optional().default('line'),
      title: z.string().optional().default(''),
      ylabel: z.string().optional().default(''),
      outputPath: z.string().optional().describe('If set, the SVG is written to this local path and only a short status is returned inline. Otherwise the SVG is returned inline.'),
      limit: z.number().optional(),
      min_interval: z.number().optional().describe('Min bucket interval (sec). Default auto (0/60/600 depending on period length).'),
    }),
  }, async ({ sn, channels, period, from, to, chartType, title, ylabel, outputPath, limit, min_interval }) => {
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
    const svg = await renderHistoryChart(series, tsFrom, tsTo, title ?? '', ylabel ?? '', chartType as ChartType)
    if (outputPath) {
      await writeFile(outputPath, svg, 'utf8')
      return text({ ok: true, outputPath, svgBytes: svg.length, totalPoints, channels: channels.length, from: tsFrom, to: tsTo })
    }
    if (svg.length > 200_000) {
      return err(`SVG too large (${svg.length} bytes) for an inline response. Pass outputPath to write it to a file, or shorten period / reduce the number of channels.`)
    }
    return text({ svg, svgBytes: svg.length, totalPoints, channels: channels.length, from: tsFrom, to: tsTo })
  })
}
