import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Block, Drawing, Segment, View } from '../types'
import { parseAnsi } from './ansi'
import { appView } from './app'
import { ROOMY, termView } from './term'
import type { AppElements } from './app'

const PANE = 'statusline'
const TITLE = 'Status'
const EVERY_MS = 5000
const drawing = atom({ plugin: 'statusline-pane', key: 'drawing' } as const, { lines: [] } as Drawing)

// Runs the installed copy (what install.sh put under ~/.claude), with the
// python it recorded, the same way statusline.sh does. Calling statusline.py
// directly skips the wrapper's render cache, which is keyed to the terminal's
// width and would be thrashed by a second, narrower caller. --json gives each
// part as data beside the terminal drawing; an install from before it ignores
// the flag and prints the drawing alone.
const RUN = `
D="\${CLAUDE_CONFIG_DIR:-$HOME/.claude}/claude-statusline"
[ -f "$D/statusline.py" ] || { echo "claude-statusline isn't installed here: run ./install.sh" >&2; exit 3; }
P="\${CLAUDE_STATUSLINE_PYTHON:-}"
[ -z "$P" ] && [ -f "$D/python" ] && P=$(cat "$D/python")
exec "\${P:-python3}" "$D/statusline.py" --json
`

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

// the pane's last measured width; a reload starts over and relearns it
let columns = 60
let running = false

async function refresh($: EngineInterface) {
  if (running) return
  running = true
  try {
    const width = String(columns)
    const run = await $.process.run(['/bin/sh', '-c', RUN], {
      stdin: JSON.stringify(await statusInput($)),
      env: { COLUMNS: width, CLAUDE_STATUSLINE_COLUMNS: width },
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

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'statusline-pane',
      description: 'Show claude-statusline in a side pane',
    })
    void $.ui.open({ id: PANE, title: TITLE })
    void refresh($)
    $.clock.every(EVERY_MS, () => void refresh($))

    return next(e)
  })

  on('command.run', { command: 'statusline-pane' }, async $ => {
    await refresh($)
    await $.ui.open({ id: PANE, title: TITLE })

    return { text: 'Status pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const table = $.ui.resolve(e)
    const { Box, Text } = table
    const { lines, view, error } = await read($, drawing)

    // redraw at the pane's own width, so the status line picks its narrow layout
    if (e.props.bodyColumns > 0 && e.props.bodyColumns !== columns) {
      columns = e.props.bodyColumns
      $.clock.after(0, () => void refresh($))
    }

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

    return <Box flexDirection="column">{lines.map((l, i) => row(l, `l${i}`))}</Box>
  })
}
