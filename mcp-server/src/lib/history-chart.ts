// Render a multi-series time-series chart via Vega-Lite SSR.
// Returns SVG string.

import * as vega from 'vega'
import { compile } from 'vega-lite'
import type { TopLevelSpec } from 'vega-lite'

export interface HistoryPoint { v: number; t: number }
export interface HistorySeries {
  label: string
  points: HistoryPoint[]
  min: number
  max: number
  avg: number
  units?: string
  precision?: number
}

export type ChartType =
  | 'line'      // time series as lines (default)
  | 'bar'       // bars over time (for discrete events, binary channels)
  | 'area'      // fill under the line (accumulations, share)
  | 'point'     // scatter (sparse points, outliers)
  | 'histogram' // value distribution: x=value bins, y=point count
  | 'heatmap'   // density: x=time, y=value bins, color=count
  | 'boxplot'   // box-and-whisker per period — min/max/median/quartiles

interface FlatPoint {
  t: string
  v: number
  vn: number
  series: string
  unit: string
}

const PALETTE = ['#2563eb', '#dc2626', '#16a34a', '#d97706', '#7c3aed', '#0891b2', '#db2777', '#65a30d']

export function pickTimeFormat(durationSec: number): string {
  if (durationSec <= 3600)         return '%H:%M:%S'
  if (durationSec <= 86400)        return '%H:%M'
  if (durationSec <= 7 * 86400)    return '%d.%m %H:%M'
  return '%d.%m'
}

export function emptySvg(message: string): string {
  return (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 240" font-family="system-ui,sans-serif">' +
    '<rect width="880" height="240" fill="#ffffff"/>' +
    `<text x="440" y="120" text-anchor="middle" fill="#64748b" font-size="14">${message}</text>` +
    '</svg>'
  )
}

export function groupByUnits(series: HistorySeries[]): Map<string, HistorySeries[]> {
  const groups = new Map<string, HistorySeries[]>()
  for (const s of series) {
    const key = s.units ?? ''
    const arr = groups.get(key)
    if (arr) arr.push(s)
    else groups.set(key, [s])
  }
  return groups
}

export function buildLabelMap(series: HistorySeries[]): Map<HistorySeries, string> {
  const devices = new Set<string>()
  for (const s of series) {
    const slash = s.label.indexOf('/')
    devices.add(slash > 0 ? s.label.slice(0, slash) : '')
  }
  const stripDevice = devices.size === 1 && !devices.has('')
  const map = new Map<HistorySeries, string>()
  for (const s of series) {
    const slash = s.label.indexOf('/')
    const channel = slash > 0 && stripDevice ? s.label.slice(slash + 1) : s.label
    const label = s.units ? `${channel}, ${s.units}` : channel
    map.set(s, label)
  }
  return map
}

export function flatten(nonEmpty: HistorySeries[], labels: Map<HistorySeries, string>): FlatPoint[] {
  const out: FlatPoint[] = []
  for (const s of nonEmpty) {
    const range = s.max - s.min
    const norm = (v: number) => (range > 0 ? (v - s.min) / range : 0.5)
    const label = labels.get(s) ?? s.label
    const unit = s.units ?? ''
    for (const p of s.points) {
      out.push({ t: new Date(p.t * 1000).toISOString(), v: p.v, vn: norm(p.v), series: label, unit })
    }
  }
  return out
}

export function legendCfg(seriesCount: number): Record<string, unknown> | null {
  if (seriesCount <= 1) return null
  if (seriesCount <= 3) return { title: null, orient: 'bottom', direction: 'horizontal', columns: 0, labelLimit: 360, symbolSize: 80, padding: 8 }
  return { title: null, orient: 'right', direction: 'vertical', columns: 1, labelLimit: 280, symbolSize: 80, rowPadding: 4 }
}

const baseConfig = {
  view: { stroke: 'transparent' },
  axis: { labelColor: '#64748b', titleColor: '#64748b', gridColor: '#e2e8f0' },
  legend: { labelColor: '#334155', titleColor: '#334155', labelFontSize: 11 },
} as const

export async function renderHistoryChart(
  series: HistorySeries[],
  from: number,
  to: number,
  title: string,
  ylabel: string,
  chartType: ChartType = 'line',
): Promise<string> {
  const nonEmpty = series.filter(s => s.points.length > 0)
  if (!nonEmpty.length) return emptySvg('No data for the selected period')

  const labelMap = buildLabelMap(nonEmpty)
  const values = flatten(nonEmpty, labelMap)
  const groups = groupByUnits(nonEmpty)
  const groupCount = groups.size
  const durationSec = to - from
  const timeFormat = pickTimeFormat(durationSec)
  const seriesCount = nonEmpty.length

  const xScaleDomain = [new Date(from * 1000).toISOString(), new Date(to * 1000).toISOString()]
  const xTimeEnc = {
    field: 't',
    type: 'temporal',
    axis: { title: null, format: timeFormat, labelAngle: -30, labelOverlap: 'parity' },
    scale: { domain: xScaleDomain },
  } as const

  const colorRange = nonEmpty.map((_, i) => PALETTE[i % PALETTE.length] ?? '#000')
  const allLabels = nonEmpty.map(s => labelMap.get(s)!)
  const colorEnc = {
    field: 'series',
    type: 'nominal' as const,
    scale: { domain: allLabels, range: colorRange },
    legend: legendCfg(seriesCount),
  }

  const sideLegend = (legendCfg(seriesCount) as { orient?: string } | null)?.orient === 'right'
  const width = sideLegend ? 980 : 880
  const baseSpec = {
    $schema: 'https://vega.github.io/schema/vega-lite/v5.json' as const,
    width,
    height: 360,
    background: '#ffffff',
    title: title ? { text: title, fontSize: 14, color: '#1e293b' } : undefined,
    config: baseConfig,
  }

  // ─── histogram: value distribution by bins ───────────────────────────
  if (chartType === 'histogram') {
    return await renderSpec({
      ...baseSpec,
      data: { values },
      mark: { type: 'bar', tooltip: true },
      encoding: {
        x: {
          field: 'v', type: 'quantitative', bin: { maxbins: 30 },
          axis: { title: ylabel || groups.size === 1 ? [...groups.keys()][0] || null : null, grid: false },
        },
        y: { aggregate: 'count', type: 'quantitative', axis: { title: 'count', grid: true } },
        color: colorEnc,
        ...(seriesCount > 1 ? { xOffset: { field: 'series', type: 'nominal' } } : {}),
      },
    } as TopLevelSpec)
  }

  // ─── heatmap: x=binned time, y=binned value ──────────────────────────
  if (chartType === 'heatmap') {
    const tu = durationSec <= 7 * 86400 ? 'yearmonthdatehours' : 'yearmonthdate'
    const heatmapMark = { type: 'rect' as const, tooltip: true }
    if (seriesCount > 1) {
      return await renderSpec({
        ...baseSpec,
        data: { values },
        facet: { row: { field: 'series', type: 'nominal', header: { title: null, labelAngle: 0, labelAlign: 'left', labelAnchor: 'start' } } },
        spec: {
          width,
          height: Math.max(120, Math.floor(360 / seriesCount)),
          mark: heatmapMark,
          encoding: {
            x: { field: 't', type: 'temporal', timeUnit: tu, axis: { title: null, format: timeFormat, labelAngle: -30 } },
            y: { field: 'v', type: 'quantitative', bin: { maxbins: 24 }, axis: { title: null } },
            color: { aggregate: 'count', type: 'quantitative', scale: { scheme: 'blues' }, legend: { title: 'density', orient: 'right' } },
          },
        },
      } as unknown as TopLevelSpec)
    }
    const onlyUnit = [...groups.keys()][0] ?? ''
    return await renderSpec({
      ...baseSpec,
      data: { values },
      mark: heatmapMark,
      encoding: {
        x: { field: 't', type: 'temporal', timeUnit: tu, axis: { title: null, format: timeFormat, labelAngle: -30 } },
        y: { field: 'v', type: 'quantitative', bin: { maxbins: 30 }, axis: { title: ylabel || onlyUnit || null } },
        color: { aggregate: 'count', type: 'quantitative', scale: { scheme: 'blues' }, legend: { title: 'density', orient: 'right' } },
      },
    } as TopLevelSpec)
  }

  // ─── boxplot: spread by period (hour / day depending on length) ──────
  if (chartType === 'boxplot') {
    const tu = durationSec <= 86400 ? 'hours' : durationSec <= 7 * 86400 ? 'yearmonthdate' : 'yearweek'
    return await renderSpec({
      ...baseSpec,
      data: { values },
      mark: { type: 'boxplot', extent: 1.5 },
      encoding: {
        x: { field: 't', type: 'temporal', timeUnit: tu, axis: { title: null, format: timeFormat, labelAngle: -30 } },
        y: { field: 'v', type: 'quantitative', axis: { title: ylabel || (groups.size === 1 ? [...groups.keys()][0] : null) || null, grid: true }, scale: { zero: false } },
        color: colorEnc,
      },
    } as TopLevelSpec)
  }

  // ─── line / bar / area / point — all time-series kinds ──────────────
  const markType: 'line' | 'bar' | 'area' | 'point' =
    chartType === 'bar' ? 'bar' :
    chartType === 'area' ? 'area' :
    chartType === 'point' ? 'point' :
    'line'
  const markCfg: Record<string, unknown> = { type: markType, tooltip: true }
  if (markType === 'line' || markType === 'area') { markCfg['interpolate'] = 'monotone'; markCfg['strokeWidth'] = 1.6 }
  if (markType === 'point') { markCfg['filled'] = true; markCfg['size'] = 30 }
  if (markType === 'area') { markCfg['opacity'] = 0.55 }

  if (groupCount === 1) {
    const onlyUnit = [...groups.keys()][0] ?? ''
    return await renderSpec({
      ...baseSpec,
      data: { values },
      mark: markCfg as { type: 'line' | 'bar' | 'area' | 'point' },
      encoding: {
        x: xTimeEnc,
        y: {
          field: 'v', type: 'quantitative',
          axis: { title: ylabel || onlyUnit || null, grid: true },
          scale: { zero: false, nice: true },
        },
        color: colorEnc,
      },
    } as TopLevelSpec)
  }
  if (groupCount === 2) {
    const groupArr = [...groups.entries()]
    const layers = groupArr.map(([unit, grpSeries], gIdx) => {
      const grpLabels = grpSeries.map(s => labelMap.get(s)!)
      const filterExpr = grpLabels.map(l => `'${l.replace(/'/g, "\\'")}'`).join(',')
      return {
        transform: [{ filter: `indexof([${filterExpr}], datum.series) >= 0` }],
        mark: markCfg as { type: 'line' | 'bar' | 'area' | 'point' },
        encoding: {
          x: xTimeEnc,
          y: {
            field: 'v', type: 'quantitative',
            axis: {
              title: unit || (gIdx === 0 ? ylabel : ''),
              orient: gIdx === 0 ? 'left' : 'right',
              grid: gIdx === 0,
            },
            scale: { zero: false, nice: true },
          },
          color: colorEnc,
        },
      }
    })
    return await renderSpec({ ...baseSpec, data: { values }, layer: layers, resolve: { scale: { y: 'independent' } } } as unknown as TopLevelSpec)
  }
  // 3+ units — normalize
  const legendLabels = nonEmpty.map(s => {
    const base = labelMap.get(s)!
    const range = `${s.min.toFixed(2)}…${s.max.toFixed(2)}${s.units ? ` ${s.units}` : ''}`
    return `${base} · ${range}`
  })
  const seriesToLegend = new Map<string, string>()
  nonEmpty.forEach((s, i) => seriesToLegend.set(labelMap.get(s)!, legendLabels[i] ?? ''))
  const normedValues = values.map(p => ({ ...p, seriesLegend: seriesToLegend.get(p.series) ?? p.series }))
  return await renderSpec({
    ...baseSpec,
    data: { values: normedValues },
    mark: markCfg as { type: 'line' | 'bar' | 'area' | 'point' },
    encoding: {
      x: xTimeEnc,
      y: {
        field: 'vn', type: 'quantitative',
        axis: { title: 'normalized (0…1)', grid: true, format: '.1f' },
        scale: { domain: [0, 1] },
      },
      color: {
        field: 'seriesLegend', type: 'nominal',
        scale: { domain: legendLabels, range: colorRange },
        legend: legendCfg(seriesCount),
      },
    },
  } as TopLevelSpec)
}

async function renderSpec(spec: TopLevelSpec): Promise<string> {
  const compiled = compile(spec).spec
  const view = new vega.View(vega.parse(compiled), { renderer: 'none' })
  return await view.toSVG()
}
