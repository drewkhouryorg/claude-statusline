import type { Repo, Segment, Session, Ship, System, Tank, Tone, View, Week } from '../types'
import { fiveWords, fmtAge, fmtDur, paint } from './svg'

// The docked terminal pane, drawn from the view rather than the status line's
// own text: a tall column with room to spell things out. Lines of styled runs,
// as parseAnsi gives, so the pane draws both the same way.

export const ROOMY = 34 // the narrowest pane this layout is for; below it the status line's own blocks stack

const BLOCKS = ' ▁▂▃▄▅▆▇█'
const LABEL = 9 // the width of the label column: "Context  "

const s = (text: string, tone?: Tone | null, bold?: boolean): Segment =>
  tone === 'dim' ? { text, dim: true } : { text, color: paint(tone), ...(bold ? { bold } : {}) }
const dim = (text: string): Segment => ({ text, dim: true })
const kv = (label: string, ...value: Segment[]): Segment[] => [dim(label.padEnd(LABEL)), ...value]
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))
const centre = (text: string, w: number) => {
  const left = Math.max(0, Math.floor((w - text.length) / 2))
  return (' '.repeat(left) + text).padEnd(w)
}

/** Each part under its heading and a rule, as wide as the pane. */
export function termView(v: View, width: number): Segment[][] {
  const out: Segment[][] = []
  const section = (title: string, lines: Segment[][]) => {
    if (lines.length === 0) return
    if (out.length) out.push([])
    out.push([{ text: title, bold: true }], [dim('─'.repeat(width))], ...lines)
  }
  section('Needs you', v.alerts.map(a => [s(a.text, a.tone)]))
  section('Usage', usage(v, width))
  if (v.week) section('Week', week(v.week, width))
  section('Repo', repo(v.repo, width))
  if (v.ship) section('Ship', ship(v.ship))
  section('Session', session(v.session))
  if (v.system) section('System', system(v.system, width))
  return out
}

const TANK_NAMES = { ctx: 'context', '5h': '5 hour', wk: 'week' } as const

/** A tank's inside, in cells: a third of the pane less room to breathe, 4 to 6 wide, and taller once it's wider. */
export function tankSize(width: number): { w: number; h: number } {
  const w = clamp(Math.floor((width - 4) / 3) - 5, 4, 6)
  return { w, h: w >= 5 ? 6 : 5 }
}

/**
 * The tanks, taller and wider than the status line's: each fills from the
 * bottom in its pace colour, a dashed line marks where the pace lands at
 * reset (above the fill, below the top), and the clock's ◂ sits in a column
 * of its own beside the right wall.
 */
export function tankRows(tanks: Tank[], width: number): Segment[][] {
  const { h, w } = tankSize(width)
  const across = w + 3 // two walls and the clock's column
  const gap = '  '
  const rows: Segment[][] = Array.from({ length: h + 2 }, () => [])
  tanks.forEach((t, i) => {
    const tone = t.tone
    const level = t.pct === null ? 0 : Math.round((clamp(t.pct, 0, 100) / 100) * h * 8)
    // the row the projection lands in; past the top, the ↑ by the number says so instead
    const paceRow = t.pct === null || t.projected == null || t.projected > 100 ? -1 : Math.min(h - 1, Math.floor((t.projected / 100) * h))
    const clockRow = t.elapsed == null ? -1 : Math.min(h - 1, Math.floor(clamp(t.elapsed, 0, 1) * h))
    const lead = i ? [dim(gap)] : []
    const number = t.pct === null ? '--' : t.pct >= 100 ? 'full' : `${Math.round(t.pct)}%${t.projected != null && t.projected > 100 ? '↑' : ''}`
    rows[0]!.push(...lead, t.pct === null ? dim(centre(number, across)) : s(centre(number, across), tone, true))
    for (let r = 0; r < h; r++) {
      const up = h - 1 - r // rows counted from the bottom
      const fill = clamp(level - 8 * up, 0, 8)
      const inside = fill ? s(BLOCKS[fill]!.repeat(w), tone) : up === paceRow ? s('╌'.repeat(w), tone) : s(' '.repeat(w))
      rows[r + 1]!.push(...lead, dim('▕'), inside, dim('▏'), up === clockRow ? s('◂', tone) : s(' '))
    }
    rows[h + 1]!.push(...lead, dim(centre(TANK_NAMES[t.label], across)))
  })
  return rows
}

const tokens = (n: number) => (n >= 1_000_000 ? `${n / 1_000_000}M` : `${Math.round(n / 1000)}k`)

function usage(v: View, width: number): Segment[][] {
  const lines = tankRows(v.tanks, width)
  lines.push([])
  for (const t of v.tanks) {
    const name = t.label === 'ctx' ? 'Context' : t.label === '5h' ? '5-hour' : 'Week'
    if (t.pct === null) {
      // the limits arrive with replies on Pro and Max plans, and never on an API key: say only what's known
      lines.push(kv(name, dim('no reading yet')))
      continue
    }
    const value = [s(`${Math.round(t.pct)}%`, t.tone, true)]
    if (t.label === 'ctx' && t.size) value.push(dim(` of ${tokens(t.size)} tokens`))
    if (t.label === '5h' && v.five) {
      const five = fiveWords(v.five)
      value.push(dim(' · '), five.tone === 'dim' ? dim(five.text.replace(/^5h · /, '')) : s(five.text.replace(/^5h /, ''), five.tone))
    }
    if (t.label === 'wk' && t.projected != null) {
      value.push(dim(' · '), s(`on pace for ~${Math.round(t.projected)}% at reset`, t.projected > 100 ? 'purple' : null))
    }
    lines.push(kv(name, ...value))
  }
  return lines
}

const CHART_ROWS = 4
const CHART_FLOOR = 150 / 7 // half again a day's share, so a quiet week isn't all tall bars

/** The week's chart across the whole pane, a bar per day, and its words under it. */
export function week(w: Week, width: number): Segment[][] {
  if (w.days.length === 0) return [kv('Used', s(`${Math.round(w.used)}%`, w.tone, true))]
  const n = w.days.length
  const slot = clamp(Math.floor(width / n), 3, 7)
  const bar = slot - 1
  const scale = Math.max(CHART_FLOOR, ...w.days.map(d => d.pct ?? 0))
  const lines: Segment[][] = []
  for (let r = 0; r < CHART_ROWS; r++) {
    const up = CHART_ROWS - 1 - r
    lines.push(
      w.days.map(d => {
        if (d.pct === null) return up === 0 ? dim('·'.repeat(bar).padEnd(slot)) : s(' '.repeat(slot))
        const eighths = clamp(Math.round((d.pct / scale) * CHART_ROWS * 8) - 8 * up, 0, 8)
        // a sliver of a bar still shows on the floor, so no day reads as blank
        const block = BLOCKS[up === 0 && d.pct > 0 ? Math.max(1, eighths) : eighths]!
        return s(block.repeat(bar).padEnd(slot), d.when === 'later' ? 'grey' : d.tone)
      }),
    )
  }
  lines.push(w.days.map(d => (d.number === null ? s(' '.repeat(slot)) : s(String(d.number).padStart(bar).padEnd(slot), d.when === 'later' ? 'dim' : d.tone))))
  lines.push(w.days.map(d => ({ text: d.name.slice(0, bar >= 3 ? 3 : 2).padEnd(slot), dim: d.when !== 'now', bold: d.when === 'now' })))
  lines.push([])
  for (const l of w.lines) lines.push([s(l.text, l.tone)])
  return lines
}

const MARK_NAMES: Record<string, string> = {
  conflicts: 'conflicts',
  staged: 'staged',
  modified: 'modified',
  untracked: 'untracked',
  ahead: 'ahead',
  behind: 'behind',
}

const length = (line: Segment[]) => line.reduce((n, seg) => n + seg.text.length, 0)

function repo(r: Repo, width: number): Segment[][] {
  if (!r.git) return [kv('Folder', s(r.name)), kv('Git', dim('not a repo'))]
  const lines = [kv('Repo', s(r.name, null, true), ...(r.worktree ? [dim(` · worktree ${r.worktree}`)] : []))]
  lines.push(r.branch ? kv('Branch', s(r.branch, 'cyan')) : kv('Branch', s(`detached at ${r.sha ?? '?'}`, 'olive')))
  if (r.state) lines.push(kv('State', s(r.state, 'olive')))
  if (r.marks.length) {
    // spelled out where it fits (✚4 modified · ?2 untracked), else as the status line writes it (✚4 ?2)
    const named = kv('Changes', ...r.marks.flatMap((m, i) => [...(i ? [dim(' · ')] : []), s(`${m.glyph}${m.count} ${MARK_NAMES[m.kind] ?? m.kind}`, m.tone)]))
    lines.push(length(named) <= width ? named : kv('Changes', ...r.marks.flatMap((m, i) => [...(i ? [s(' ')] : []), s(`${m.glyph}${m.count}`, m.tone)])))
  } else {
    lines.push(kv('Changes', dim(r.status_unknown ? 'git is slow to answer' : 'none, clean')))
  }
  if (r.commit_age != null) lines.push(kv('Commit', s(`${fmtAge(r.commit_age)} ago`, r.commit_tone)))
  if (r.pr) {
    lines.push(
      kv(
        'PR',
        s(`#${r.pr.number}`, 'cyan'),
        ...(r.pr.checks ? [dim(' · '), s(r.pr.checks.text, r.pr.checks.tone)] : []),
        ...(r.pr.review ? [dim(' · '), s(r.pr.review.text, r.pr.review.tone)] : []),
      ),
    )
  }
  return lines
}

const RUN = { ok: ['✓', 'sage'], fail: ['✗', 'brick'], running: ['⟳', 'amber'], cancelled: ['○', 'dim'] } as const
const CHECK = { pass: ['✓', 'sage'], fail: ['✗', 'brick'], pending: ['⟳', 'amber'], none: ['·', 'dim'] } as const
const old = (age: number | null) => (age == null ? [] : [dim(` · ${fmtAge(age)} old`)])

function ship(sh: Ship): Segment[][] {
  const lines: Segment[][] = []
  for (const c of sh.ci) lines.push(kv(`CI ${c.name}`, ...c.runs.map(r => s(RUN[r][0], RUN[r][1])), ...old(c.stale_age)))
  for (const d of sh.deploys) {
    const status =
      d.status === 'fail' ? [s('✗ failed', 'brick')] : d.status === 'running' ? [s('⟳ deploying', 'amber')] : [s('✓ ', 'sage'), s(d.version)]
    lines.push(
      kv(
        d.env,
        ...status,
        ...(d.age != null && d.status !== 'running' ? [dim(` · ${fmtAge(d.age)} ago`)] : []),
        ...(d.behind ? [dim(' · '), s(`${d.behind} behind`, d.behind_tone)] : []),
        ...old(d.stale_age),
      ),
    )
  }
  if (sh.prs) {
    const items = sh.prs.items.length
      ? sh.prs.items.flatMap((p, i) => [...(i ? [s(' ')] : []), p.draft ? dim(`#${p.number}`) : s(`#${p.number}`), s(CHECK[p.checks][0], CHECK[p.checks][1])])
      : [s(`${sh.prs.open} open`)]
    lines.push(kv('PRs', ...items, ...(sh.prs.needs_review ? [dim(' · '), s(`${sh.prs.needs_review} to review`, 'olive')] : []), ...old(sh.prs.stale_age)))
  }
  return lines
}

function session(se: Session): Segment[][] {
  const lines = [kv('Model', s(se.model ?? '?', null, true), ...(se.effort ? [dim(` · ${se.effort} effort`)] : []), ...(se.fast ? [s(' · fast', 'amber')] : []))]
  if (se.duration != null) lines.push(kv('Running', s(fmtDur(se.duration))))
  // the mod API doesn't give the session's name, so a missing one isn't "untitled": leave the row out
  if (se.name) lines.push(kv('Name', s(se.name)))
  if (se.added || se.removed) lines.push(kv('Lines', s(`+${se.added ?? 0}`, 'sage'), s(' '), s(`−${se.removed ?? 0}`, 'brick')))
  if (se.id) lines.push(kv('ID', dim(se.id)))
  return lines
}

/** A meter as wide as the pane allows: label, bar, percent. */
export function meter(label: string, pct: number | null, tone: Tone, width: number): Segment[] {
  const cells = Math.max(8, width - LABEL - 5)
  if (pct === null) return kv(label, dim('░'.repeat(cells)), dim('   --'))
  const filled = clamp(Math.round((pct / 100) * cells), 0, cells)
  return kv(label, s('█'.repeat(filled), tone), dim('░'.repeat(cells - filled)), s(`${Math.round(pct)}%`.padStart(5), tone))
}

function system(sy: System, width: number): Segment[][] {
  const mem = sy.memory
  const arrow = { up: '↑', down: '↓', steady: '→' } as const
  const lines = [meter('CPU', sy.cpu.usage, sy.cpu.tone, width)]
  if (sy.cpu.waiting > 0) lines.push(kv('', s(`${sy.cpu.waiting} waiting for a core${sy.cpu.top ? ` · ${sy.cpu.top}` : ''}`, 'brick')))
  lines.push(meter('Memory', mem.used_pct, mem.tone, width))
  if (mem.pressure !== 'normal') {
    lines.push(kv('', s(`pressure ${mem.pressure}${mem.top ? ` · ${mem.top.name} ${(mem.top.mb / 1024).toFixed(1)}G` : ''}`, mem.tone)))
  }
  const flow = [
    mem.comp_mb != null ? `compressed ${(mem.comp_mb / 1024).toFixed(1)}G${mem.comp_trend ? ' ' + arrow[mem.comp_trend] : ''}` : null,
    mem.swap_mb != null && mem.swap_trend ? `swap ${(mem.swap_mb / 1024).toFixed(1)}G ${arrow[mem.swap_trend]}` : null,
  ].filter(Boolean)
  if (flow.length) lines.push(kv('', dim(flow.join(' · '))))
  if (sy.battery) lines.push(kv('Battery', s(`${sy.battery.pct}%`, sy.battery.tone)))
  return lines
}
