import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Block, Drawing, Segment, View } from '../types'
import { parseAnsi } from './ansi'
import { appView } from './app'
import { ROOMY, termView } from './term'
import type { AppElements } from './app'

const PANE = 'statusline'
const TITLE = 'Status'
// the status line's git and system readings last 10 s (SLOW_TTL in
// statusline.py), so a faster tick would redraw the same data at full cost
export const EVERY_MS = 10_000
// a redraw may ask for a run sooner than the tick, at most this often
export const SOONEST_MS = 1_000
const drawing = atom({ plugin: 'statusline-pane', key: 'drawing' } as const, { lines: [] } as Drawing)
// whether the person opened the pane: an unasked one gives way on a terminal
// that isn't fullscreen, where it would sit above the prompt as a second status line
const asked = atom({ plugin: 'statusline-pane', key: 'asked' } as const, false)

// Runs the status line installed beside this mod (install.sh puts the mod in
// the install folder as pane/), else the default install, with the python it
// recorded, the way statusline.sh does. Calling statusline.py directly skips
// the wrapper's render cache, which is keyed to the terminal's width and
// would be thrashed by a second caller. --json gives each part as data beside
// the terminal drawing; an install from before it ignores the flag and
// prints the drawing alone.
const RUN = `
D="\${STATUSLINE_HOME:-}"
[ -f "$D/statusline.py" ] || D="\${CLAUDE_CONFIG_DIR:-$HOME/.claude}/claude-statusline"
[ -f "$D/statusline.py" ] || { echo "No status line at $D: run ./install.sh in claude-statusline first" >&2; exit 3; }
P="\${CLAUDE_STATUSLINE_PYTHON:-}"
[ -z "$P" ] && [ -f "$D/python" ] && P=$(cat "$D/python")
exec "\${P:-python3}" "$D/statusline.py" --json
`

/** The folder holding the mod's folder: the install folder when install.sh put it there. */
export const parent = (dir: string) => dir.replace(/\/+$/, '').replace(/\/[^/]*$/, '') || '/'

/** What statusline.py printed: the view and its drawing, or (an older install) the drawing alone. */
export function readOutput(stdout: string): Drawing {
  if (stdout.trimStart().startsWith('{')) {
    try {
      const view = JSON.parse(stdout) as View
      if (view.schema === 1 && typeof view.ansi === 'string') return { lines: parseAnsi(view.ansi), view }
    } catch {
      // not the view after all: draw it as the text it is
    }
  }
  return { lines: parseAnsi(stdout) }
}

// Text's `mono` prop is refused by older engines (the desktop app's 2.1.295
// refuses the whole tree over it); 2.1.299 is the oldest seen to accept it
const MONO_SINCE = [2, 1, 299]

export function hasMono(base: string | undefined): boolean {
  const parts = (base ?? '').split(/[.-]/).slice(0, 3).map(Number)
  if (parts.length < 3 || parts.some(Number.isNaN)) return false
  for (let i = 0; i < 3; i++) {
    const have = parts[i] ?? 0
    const need = MONO_SINCE[i] ?? 0
    if (have !== need) return have > need
  }
  return true
}

// $.session.model() answers the id (claude-opus-5-5); Claude Code's status
// input carries a display name beside it (Opus 5.5), which the line shows
export function displayName(model: string): string {
  const m = /^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?(\[.*\])?$/.exec(model)
  if (!m || !m[1] || !m[2]) return model
  const family = m[1][0]?.toUpperCase() + m[1].slice(1)
  return `${family} ${m[2]}${m[3] ? '.' + m[3] : ''}`
}

const toEpochSeconds = (iso?: string) => (iso ? Math.floor(Date.parse(iso) / 1000) : undefined)

// The JSON Claude Code pipes to a statusLine command, rebuilt from what the
// mod API exposes. Not available here: effort, session name, lines changed,
// prompt cache state and the PR, so those parts of the drawing stay blank.
export async function statusInput($: EngineInterface) {
  const [sessionId, model, cwd, root, usage, now] = await Promise.all([
    $.session.id(),
    $.session.model(),
    $.session.cwd(),
    $.session.root(),
    $.session.usage(),
    $.clock.now(),
  ])
  const limit = (kind: string) => {
    const found = usage.rateLimits.find(r => r.kind === kind)
    return found && { used_percentage: found.percentUsed, resets_at: toEpochSeconds(found.resetsAt) }
  }
  // before the session's first reply there's no measured context; estimate it
  // locally, as /context does, so the tank isn't empty at the start
  const ctxPercent = usage.context.percent ?? (await $.session.usage({ breakdown: 'summary' })).context.breakdown?.percentage
  const fiveHour = limit('five_hour')
  const sevenDay = limit('seven_day')

  return {
    session_id: sessionId,
    cwd,
    model: { id: model, display_name: displayName(model) },
    workspace: { current_dir: cwd, project_dir: root },
    cost: { total_cost_usd: usage.cost?.usd, total_duration_ms: now - usage.startedAt },
    context_window: {
      used_percentage: ctxPercent,
      context_window_size: usage.context.window,
      total_input_tokens: usage.context.tokens,
    },
    ...(fiveHour || sevenDay
      ? { rate_limits: { ...(fiveHour && { five_hour: fiveHour }), ...(sevenDay && { seven_day: sevenDay }) } }
      : {}),
  }
}

const HEADINGS: Record<Block, string> = {
  tanks: 'Usage',
  repo: 'Repo',
  ship: 'Ship',
  session: 'Session',
  week: 'Week',
  system: 'System',
  alerts: 'Alerts',
}

/** The parts stacked, each under its heading: for a pane docked beside the transcript, tall and narrow. */
export function stacked(blocks: NonNullable<View['blocks']>): { heading: string; lines: Segment[][] }[] {
  return blocks.map(b => ({ heading: HEADINGS[b.name] ?? b.name, lines: parseAnsi(b.lines.join('\n')) }))
}

// the terminal pane's last width: the only width statusline.py runs at. A
// reload starts over and relearns it
let columns = 60
let running = false
let pending = false
let lastRun = Number.NEGATIVE_INFINITY

async function refresh($: EngineInterface) {
  if (running) return
  running = true
  try {
    lastRun = await $.clock.now()
    const width = String(columns)
    const run = await $.process.run(['/bin/sh', '-c', RUN], {
      stdin: JSON.stringify(await statusInput($)),
      // the status line Claude Code runs already writes the usage files; a
      // second writer would only put this mod's estimates in them
      env: { COLUMNS: width, CLAUDE_STATUSLINE_COLUMNS: width, CLAUDE_STATUSLINE_SENSOR: '0', STATUSLINE_HOME: parent($.plugin.root) },
      timeoutMs: 10000,
    })
    const next: Drawing =
      run.exitCode === 0
        ? readOutput(run.stdout)
        : { lines: [], error: run.stderr.trim() || `statusline exited ${run.exitCode}` }
    await update($, drawing, () => next)
  } catch (err) {
    await update($, drawing, () => ({ lines: [], error: String(err) }))
  } finally {
    running = false
  }
}

/** The timer's tick: a run only while the pane is placed on some surface; a hidden, closed or never-drawn pane costs nothing. */
async function tick($: EngineInterface) {
  const pane = (await $.ui.panes()).find(p => p.id === PANE)
  if (pane?.isPlaced) await refresh($)
}

/** A run asked for by a redraw, no sooner than SOONEST_MS after the last, and one at a time. */
async function soon($: EngineInterface) {
  if (pending) return
  pending = true
  const wait = Math.max(0, lastRun + SOONEST_MS - (await $.clock.now()))
  $.clock.after(wait, () => {
    pending = false
    void refresh($)
  })
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'statusline-pane',
      description: 'Show claude-statusline in a side pane',
    })
    // the first run comes from the pane's first drawing, so a pane that is
    // never placed (a -p run, a narrow terminal) never runs anything
    void $.ui.open({ id: PANE, title: TITLE })
    $.clock.every(EVERY_MS, () => void tick($).catch(() => undefined))

    return next(e)
  })

  on('command.run', { command: 'statusline-pane' }, async $ => {
    await update($, asked, () => true)
    await refresh($)
    await $.ui.open({ id: PANE, title: TITLE })

    return { text: 'Status pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const table = $.ui.resolve(e)
    const { Box, Text } = table

    // inline above the prompt of a terminal that isn't fullscreen (tmux, or
    // fullscreen off), a pane nobody asked for would be the status line twice
    if (e.surface === 'terminal' && e.props.placement === 'inline' && e.viewport?.isFullscreen !== true && !(await read($, asked))) {
      void $.ui.close({ id: PANE })
      return <Text> </Text>
    }

    const { lines, view, error } = await read($, drawing)

    // Only the terminal's width decides how wide statusline.py draws. The
    // docked and app layouts lay themselves out from the data at their own
    // width, so another surface (a phone, the app) never asks for a run: two
    // widths taking turns would redraw each other without end.
    const widened = e.surface === 'terminal' && e.props.bodyColumns > 0 && e.props.bodyColumns !== columns
    if (widened) columns = e.props.bodyColumns
    if (widened || (await $.clock.now()) - lastRun >= EVERY_MS) void soon($)

    if (error) return <Text color="error">{error}</Text>
    if (lines.length === 0) return <Text dimColor>Reading the status line…</Text>

    // the apps draw each part themselves; the terminal keeps the status line's own text
    if (e.surface !== 'terminal' && view && 'Svg' in table && 'Link' in table) return appView(table as AppElements, view, e.props.bodyColumns)

    // mono: the status line lines up its tanks and columns by character cell,
    // which the desktop and mobile apps keep only in their monospaced face
    const mono = hasMono((await $.session.version()).base) ? { mono: true } : {}
    const row = (line: Segment[], key: string) => (
      <Text key={key} {...mono} wrap="truncate-end">
        {line.length === 0
          ? ' '
          : line.map(seg => (
              <Text color={seg.color} backgroundColor={seg.backgroundColor} bold={seg.bold} dimColor={seg.dim}>
                {seg.text}
              </Text>
            ))}
      </Text>
    )

    // docked, the pane is a tall column: with room, each part spelled out under
    // its heading; narrower, the status line's own parts stacked
    if (e.props.placement === 'dock' && view && e.props.bodyColumns >= ROOMY) {
      return <Box flexDirection="column">{termView(view, e.props.bodyColumns).map((l, i) => row(l, `t${i}`))}</Box>
    }
    if (e.props.placement === 'dock' && view?.blocks?.length) {
      return (
        <Box flexDirection="column" rowGap={1}>
          {stacked(view.blocks).map((b, i) => (
            <Box key={`b${i}`} flexDirection="column">
              <Text dimColor bold>{b.heading}</Text>
              {b.lines.map((l, j) => row(l, `l${j}`))}
            </Box>
          ))}
        </Box>
      )
    }

    // an install from before --json draws the strip alone; say how to get the rest
    const old = !view && (e.surface !== 'terminal' || e.props.placement === 'dock')
    return (
      <Box flexDirection="column">
        {lines.map((l, i) => row(l, `l${i}`))}
        {old && <Text dimColor>Run ./install.sh in claude-statusline again for the full pane.</Text>}
      </Box>
    )
  })
}
