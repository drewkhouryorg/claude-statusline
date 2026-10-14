import type { Day, Five, Tank, Tone, Week } from '../types'

// The terminal palette (xterm 256 numbers in statusline.py), as hex. Each is
// mid-light, so it reads on the app's dark and light themes alike.
export const PAINT: Record<Tone, string> = {
  sage: '#87af87',
  olive: '#afaf5f',
  terra: '#d7875f',
  brick: '#d75f5f',
  amber: '#d7af5f',
  cyan: '#00afaf',
  grey: '#808080',
  purple: '#af5fd7',
  dim: '#808080',
}

export const paint = (tone: Tone | null | undefined): string | undefined => (tone ? PAINT[tone] : undefined)

// SVG is drawn apart from the page, as an image or in a sandboxed frame, so it
// can't take the theme's colours; it follows the light or dark preference itself
const STYLE = `<style>
text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;fill:#2b2b2b}
.dim{fill:#7a7a7a}.track{fill:none;stroke:#c8c8c8}.well{fill:#ececec}
@media (prefers-color-scheme:dark){text{fill:#e6e4df}.dim{fill:#8f8f8f}.track{stroke:#4a4a4a}.well{fill:#262626}}
</style>`

export const esc = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

const svg = (w: number, h: number, body: string) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">${STYLE}${body}</svg>`

/** `1h30m`, `2d4h`, `45s`: statusline.py's fmt_dur. */
export function fmtDur(secs: number): string {
  const s = Math.max(0, Math.floor(secs))
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d) return `${d}d${h}h`
  if (h) return `${h}h${String(m).padStart(2, '0')}m`
  return m ? `${m}m` : `${s}s`
}

/** `40s`, `12m`, `3h`, `2d`: statusline.py's fmt_age. */
export function fmtAge(secs: number): string {
  const s = Math.max(0, Math.floor(secs))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

const NAMES = { ctx: 'context', '5h': '5 hour', wk: 'week' } as const

/** What a tank's tooltip says: the level, when it resets, where the pace lands. */
export function tankTitle(t: Tank): string {
  const what = t.label === 'ctx' ? 'Context window' : t.label === '5h' ? '5-hour limit' : 'Weekly limit'
  if (t.pct === null) return `${what}: no reading yet`
  const parts = [`${what}: ${Math.round(t.pct)}% used`]
  if (t.label === 'ctx' && t.size) parts.push(`of ${Math.round(t.size / 1000)}k tokens`)
  if (t.to_reset != null) parts.push(`resets in ${fmtDur(t.to_reset)}`)
  if (t.projected != null) parts.push(`at this pace ~${Math.round(t.projected)}% by then`)
  return parts.join(' · ')
}

const TANK = { w: 54, h: 92, top: 30, gap: 34, left: 18 }

/**
 * The three tanks, as the terminal pane draws them. Each fills from the
 * bottom in its pace colour; a dashed line marks where the pace lands at
 * reset (an arrow over the tank when that's past the top), and the notch on
 * the right wall is how far the clock is through the window, so fill above
 * the notch is burning faster than time.
 */
export function tanksSvg(tanks: Tank[]): string {
  const { w, h, top, gap, left } = TANK
  const width = left * 2 + tanks.length * w + (tanks.length - 1) * gap
  const bottom = top + h
  const parts = tanks.map((t, i) => {
    const x = left + i * (w + gap)
    const color = paint(t.tone) ?? PAINT.dim
    const level = (pct: number) => (Math.max(0, Math.min(100, pct)) / 100) * h
    const clip = `tank${i}`
    let inner = `<rect class="well" x="${x}" y="${top}" width="${w}" height="${h}" rx="9"/>`
    if (t.pct !== null) {
      const fill = level(t.pct)
      inner += `<rect x="${x}" y="${bottom - fill}" width="${w}" height="${fill}" fill="${color}"/>`
      // where the pace lands at reset: a dashed line above the fill; past the top, the arrow below says so
      if (t.projected != null && t.projected > t.pct && t.projected <= 100) {
        const y = bottom - level(t.projected)
        inner += `<line x1="${x}" x2="${x + w}" y1="${y}" y2="${y}" stroke="${color}" stroke-width="2" stroke-dasharray="4 3"/>`
      }
    }
    let out = `<clipPath id="${clip}"><rect x="${x}" y="${top}" width="${w}" height="${h}" rx="9"/></clipPath>`
    out += `<g clip-path="url(#${clip})">${inner}</g>`
    out += `<rect class="track" x="${x}" y="${top}" width="${w}" height="${h}" rx="9" stroke-width="1.5"/>`
    if (t.elapsed != null) {
      const y = bottom - Math.max(0, Math.min(1, t.elapsed)) * h
      out += `<path d="M ${x + w + 1} ${y} l 8 -5 v 10 z" fill="${color}"/>`
    }
    if (t.projected != null && t.projected > 100 && t.pct !== null) {
      out += `<path d="M ${x + w / 2} ${top - 2} l -6 6 h 12 z" fill="${color}" transform="translate(0 -1)"/>`
    }
    const number = t.pct === null ? '--' : t.pct >= 100 ? 'full' : `${Math.round(t.pct)}%`
    out += `<text x="${x + w / 2}" y="${top - 10}" text-anchor="middle" font-size="17" font-weight="600"${t.pct === null ? ' class="dim"' : ` style="fill:${color}"`}>${number}</text>`
    out += `<text class="dim" x="${x + w / 2}" y="${bottom + 18}" text-anchor="middle" font-size="12">${NAMES[t.label]}</text>`
    return `<g><title>${esc(tankTitle(t))}</title>${out}</g>`
  })
  return svg(width, bottom + 26, parts.join(''))
}

// half again a day's share, so a quiet week isn't all tall bars (CHART_FLOOR)
const CHART_FLOOR = 150 / 7

/** What a day's tooltip says. */
export function dayTitle(d: Day): string {
  if (d.pct === null) return `${d.name}: before the usage log started`
  const share = `${d.number ?? Math.round(d.pct)}% of the week`
  return d.when === 'later' ? `${d.name}: ${share} left for it, if today stops here` : `${d.name}${d.when === 'now' ? ' (today)' : ''}: ${share}`
}

/**
 * The week as a bar per day: past days in the colour of their spend against
 * their share, today outlined, days to come pale and dashed, splitting what's
 * left. Each bar's percent sits on it and the day's name under it.
 */
export function weekSvg(week: Week): string {
  const days = week.days
  // wide for its height, so scaled to a card it spans the card without standing tall
  const slot = 60
  const width = slot * days.length
  const top = 22
  const h = 78
  const bottom = top + h
  const scale = Math.max(CHART_FLOOR, ...days.map(d => d.pct ?? 0))
  const bars = days.map((d, i) => {
    const x = i * slot + slot * 0.2
    const w = slot * 0.6
    const mid = x + w / 2
    const color = paint(d.tone) ?? PAINT.grey
    let out = ''
    if (d.pct === null) {
      out += `<line x1="${x}" x2="${x + w}" y1="${bottom - 1}" y2="${bottom - 1}" stroke="${PAINT.grey}" stroke-width="2" stroke-dasharray="1 4" stroke-linecap="round"/>`
    } else {
      const bh = Math.max(2, (d.pct / scale) * h)
      const y = bottom - bh
      out +=
        d.when === 'later'
          ? `<rect x="${x}" y="${y}" width="${w}" height="${bh}" rx="4" fill="${color}" fill-opacity="0.18" stroke="${color}" stroke-dasharray="3 3"/>`
          : `<rect x="${x}" y="${y}" width="${w}" height="${bh}" rx="4" fill="${color}"/>`
      if (d.when === 'now') out += `<rect class="track" x="${x - 3}" y="${y - 3}" width="${w + 6}" height="${bh + 6}" rx="6" stroke-width="1.5"/>`
      out += `<text x="${mid}" y="${y - 6}" text-anchor="middle" font-size="12"${d.when === 'later' ? ' class="dim"' : ''}>${d.number ?? ''}</text>`
    }
    const name = esc(d.name.slice(0, 2))
    out += `<text x="${mid}" y="${bottom + 16}" text-anchor="middle" font-size="12"${d.when === 'now' ? ' font-weight="700"' : ' class="dim"'}>${name}</text>`
    return `<g><title>${esc(dayTitle(d))}</title>${out}</g>`
  })
  return svg(width, bottom + 22, bars.join(''))
}

/** The 5h window in words, as statusline.py's runway line puts it. */
export function fiveWords(five: Five): { text: string; tone: Tone | null } {
  const reset = five.to_reset != null ? ` · resets in ${fmtDur(five.to_reset)}` : ''
  if (five.state === 'full') return { text: `5h limit used up${reset}`, tone: 'brick' }
  if (five.state === 'out' && five.to_full != null) return { text: `5h runs out in ~${fmtDur(five.to_full)}`, tone: five.tone }
  return { text: `5h${reset}`, tone: 'dim' }
}

/**
 * A meter's bar alone: a rounded track and its fill, no text, so scaling it
 * to the room between its label and its percent only changes its length.
 * 1000 wide for 28 high: wider than any pane, so the app shrinks it to the
 * room it has, a thin bar about 8px tall in a side pane.
 */
export function barSvg(pct: number | null, tone: Tone): string {
  const fill = pct === null ? 0 : Math.round(Math.max(0, Math.min(100, pct)) * 10)
  const bar = fill ? `<rect x="0" y="0" width="${Math.max(fill, 28)}" height="28" rx="14" fill="${paint(tone) ?? PAINT.dim}"/>` : ''
  return svg(1000, 28, `<rect class="well" x="0" y="0" width="1000" height="28" rx="14"/>${bar}`)
}
