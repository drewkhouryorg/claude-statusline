import { expect, mock, test } from 'claude-code/testing'
import type { On, ProcessRunResult, SessionUsage } from 'claude-code'

// The session as the mod API reports it: 54% of a 200k window, 62% of the
// 5-hour limit and 30% of the week, an hour in. The resets are the ISO forms
// of 1759405400 and 1759745600.
const NOW = 1759400000_000
const USAGE: SessionUsage = {
  startedAt: NOW - 3600_000,
  context: { tokens: 108000, window: 200000, percent: 54 },
  rateLimits: [
    { kind: 'five_hour', percentUsed: 62, resetsAt: '2025-10-02T11:43:20.000Z' },
    { kind: 'seven_day', percentUsed: 30, resetsAt: '2025-10-06T10:13:20.000Z' },
  ],
  cost: { usd: 1.25 },
}

// one row as statusline.py prints it: dim separator, branch in palette 37
const PRINTED = '\x1b[2m · \x1b[0m\x1b[38;5;37mmain\x1b[0m\n'

const ran = (stdout: string, exitCode = 0, stderr = ''): { value: ProcessRunResult } => ({
  value: { exitCode, stdout, stderr, isStdoutTruncated: false, isStderrTruncated: false },
})

// the person typing /statusline-pane in the composer of a docked layout
const TYPED = {
  command: 'statusline-pane',
  args: '',
  origin: { kind: 'composer' },
  presentation: { isFullscreen: true, columns: 200 },
} as const

// what the mod reads from the session, and a surface that seats the pane
// `usage` answers $.session.usage; a test that needs another reading passes its own
function session(on: On, usage: any = () => ({ value: USAGE })) {
  mock.clock(on, { now: NOW })
  on('session.id', () => ({ value: 'a1b2c3d4-5e6f-4a1b-9c8d-0123456789ab' }))
  on('session.model', () => ({ value: 'Opus 5.5' }))
  on('session.cwd', () => ({ value: '/Users/dev/code/acme-shop' }))
  on('session.root', () => ({ value: '/Users/dev/code/acme-shop' }))
  on('session.usage', usage)
  on('ui.open', () => ({ value: { isPlaced: true } }))
}

const PANE = {
  plugin: 'statusline-pane',
  surface: 'terminal',
  component: 'Pane',
  requestId: 'statusline',
  props: {
    title: 'Status',
    isFocused: false,
    bodyColumns: 60,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 20 },
    view: {},
  },
} as const

// a current engine. An older one (the desktop app's 2.1.295) refuses any tree
// holding `mono`, which is why the mod asks the version first; run under that
// engine this test has nothing to check, and the next one covers it
test('every surface draws what the status line printed, in its colours, monospaced', async ($, on) => {
  session(on)
  on('session.version', () => ({ value: { version: '2.1.299', base: '2.1.299' } }))
  on('process.run', () => ran(PRINTED))

  await $.command.run(TYPED)
  for (const surface of ['terminal', 'desktop', 'mobile'] as const) {
    let ui
    try {
      ui = await $.ui.mount({ ...PANE, surface })
    } catch (err) {
      if (/Text prop "mono" is not allowed/.test(String(err))) return
      throw err
    }

    expect((await ui.find({ type: 'Text', text: /^main$/ }))?.props.color).toBe('#00afaf')
    expect((await ui.find({ type: 'Text', text: ' · main' }))?.props.mono).toBe(true)
    await ui.unmount()
  }
})

// the desktop app's own Claude Code, which refuses a tree holding `mono`
test('an engine without mono still gets a drawing', async ($, on) => {
  session(on)
  on('session.version', () => ({ value: { version: '2.1.295', base: '2.1.295' } }))
  on('process.run', () => ran(PRINTED))

  await $.command.run(TYPED)
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })

  expect((await ui.find({ type: 'Text', text: ' · main' }))?.props).not.toHaveProperty('mono')
  await ui.unmount()
})

test('the status line gets the figures Claude Code would pipe to it', async ($, on) => {
  session(on)
  let sent: Record<string, any> = {}
  on('process.run', (_$, e) => {
    sent = JSON.parse(e.init?.stdin ?? '{}')
    return ran(PRINTED)
  })

  await $.command.run(TYPED)

  expect(sent.context_window).toEqual({ used_percentage: 54, context_window_size: 200000, total_input_tokens: 108000 })
  expect(sent.rate_limits).toEqual({
    five_hour: { used_percentage: 62, resets_at: 1759405400 },
    seven_day: { used_percentage: 30, resets_at: 1759745600 },
  })
  expect(sent.cost).toEqual({ total_cost_usd: 1.25, total_duration_ms: 3600_000 })
})

test('before the first reply, the context is estimated as /context does', async ($, on) => {
  // no reply yet: no measured percent, but a local breakdown on asking
  session(on, (_$: unknown, e: { breakdown?: string }) =>
    e.breakdown
      ? { value: { ...USAGE, context: { window: 200000, breakdown: { percentage: 12 } } } }
      : { value: { ...USAGE, context: { window: 200000 } } },
  )
  let sent: Record<string, any> = {}
  on('process.run', (_$, e) => {
    sent = JSON.parse(e.init?.stdin ?? '{}')
    return ran(PRINTED)
  })

  await $.command.run(TYPED)

  expect(sent.context_window.used_percentage).toBe(12)
})

test('a missing install shows the reason in the pane', async ($, on) => {
  session(on)
  const reason = "claude-statusline isn't installed here: run ./install.sh"
  on('process.run', () => ran('', 3, reason + '\n'))

  await $.command.run(TYPED)
  const ui = await $.ui.mount(PANE)

  expect((await ui.find({ type: 'Text', text: reason }))?.props.color).toBe('error')
  await ui.unmount()
})
