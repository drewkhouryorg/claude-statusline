import { expect, mock, test } from 'claude-code/testing'
import type { On, ProcessRunResult, UiPane } from 'claude-code'

import { EVERY_MS, parent, readOutput } from '../hooks/register'
import { BAD_DAY } from './fixtures/bad-day'

// --json from a current install, and the bare drawing an older one prints
const JSON_OUT = JSON.stringify(BAD_DAY) + '\n'
const TEXT_OUT = '\x1b[2m · \x1b[0m\x1b[38;5;37mmain\x1b[0m\n'

const ran = (stdout: string): { value: ProcessRunResult } => ({
  value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})

const TYPED = {
  command: 'statusline-pane',
  args: '',
  origin: { kind: 'composer' },
  presentation: { isFullscreen: true, columns: 200 },
} as const

// a session as the mod reads it, on an engine without Text's mono
function session(on: On, stdout: string) {
  mock.clock(on, { now: BAD_DAY.now * 1000 })
  on('session.id', () => ({ value: 'a1b2c3d4-5e6f-4a1b-9c8d-0123456789ab' }))
  on('session.model', () => ({ value: 'claude-opus-5-5' }))
  on('session.cwd', () => ({ value: '/Users/dev/code/acme-shop' }))
  on('session.root', () => ({ value: '/Users/dev/code/acme-shop' }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { window: 200000, percent: 91 }, rateLimits: [] } }))
  on('session.version', () => ({ value: { version: '2.1.295', base: '2.1.295' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('process.run', () => ran(stdout))
}

// docked beside the transcript (tall, narrow) or inline above the prompt (wide, short)
const pane = (surface: 'terminal' | 'desktop' | 'mobile', placement: 'dock' | 'inline' = 'dock') =>
  ({
    plugin: 'statusline-pane',
    surface,
    component: 'Pane',
    requestId: 'statusline',
    props: { title: 'Status', isFocused: false, bodyColumns: 100, placement, scroll: { offset: 0, bodyRows: 40 }, view: {} },
  }) as const

const HEADINGS = ['Usage', 'Repo', 'Ship', 'Session', 'Week', 'System', 'Alerts']

test('the output of --json is the view, with its drawing', async () => {
  const got = readOutput(JSON_OUT)

  expect(got.view?.repo).toEqual(BAD_DAY.repo)
  expect(got.lines.length).toBeGreaterThan(0)
})

test("an older install's bare drawing is drawn as text", async () => {
  const got = readOutput(TEXT_OUT)

  expect(got.view).toBeUndefined()
  expect(got.lines[0]?.map(s => s.text).join('')).toBe(' · main')
})

test('output that only looks like JSON is drawn as text', async () => {
  expect(readOutput('{not json').view).toBeUndefined()
})

test('the apps draw the tanks, the week and the meter bars as pictures', async ($, on) => {
  session(on, JSON_OUT)
  await $.command.run(TYPED)

  for (const surface of ['desktop', 'mobile'] as const) {
    const ui = await $.ui.mount(pane(surface))
    const pictures = await ui.findAll({ type: 'Svg' })

    expect(pictures.map(p => p.props.alt)).toEqual([
      'ctx 91%, 5h 94%, wk 71%',
      'Fri 12%, Sat 9%, Sun 12%, Mon 14%, Tue 13%, Wed 11%, Thu 29%',
      'cpu 100%',
      'mem 63%',
    ])
    await ui.unmount()
  }
})

test("the apps' drawings are images, which the app sizes to their own proportions", async ($, on) => {
  session(on, JSON_OUT)
  await $.command.run(TYPED)
  const ui = await $.ui.mount(pane('desktop'))

  for (const picture of await ui.findAll({ type: 'Svg' })) expect(picture.props.isInteractive).toBeUndefined()
  await ui.unmount()
})

test('a side pane gets a card to a row; a wide one, two side by side', async ($, on) => {
  session(on, JSON_OUT)
  await $.command.run(TYPED)
  const widths = async (bodyColumns: number) => {
    const base = pane('desktop')
    const ui = await $.ui.mount({ ...base, props: { ...base.props, bodyColumns } })
    const width = (await ui.find({ type: 'Box', key: 'usage' }))?.props.width
    await ui.unmount()
    return width
  }

  expect(await widths(60)).toBe('100%')
  expect(await widths(120)).toBe('49%')
})

test("the machine's meters are text at the card's size, the bar a thin picture", async ($, on) => {
  session(on, JSON_OUT)
  await $.command.run(TYPED)
  const ui = await $.ui.mount(pane('desktop'))

  expect(await ui.find({ type: 'Text', text: /^cpu$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^mem$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^63%$/ })).toBeDefined()
  // bad day: memory at 63%, in its pressure colour (warn: terra)
  const pictures = await ui.findAll({ type: 'Svg' })
  const bar = String(pictures.find(p => p.props.alt === 'mem 63%')?.props.source)
  expect(bar).toContain('width="630"')
  expect(bar).toContain('fill="#d7875f"')
  await ui.unmount()
})

test('the apps draw each part as a card with its own words', async ($, on) => {
  session(on, JSON_OUT)
  await $.command.run(TYPED)
  const ui = await $.ui.mount(pane('desktop'))

  for (const title of ['Usage', 'Week', 'Repo', 'Ship', 'Session', 'System']) {
    expect(await ui.find({ type: 'Text', text: new RegExp(`^${title}$`) })).toBeDefined()
  }
  expect((await ui.find({ type: 'Text', text: /^feat\/rewards$/ }))?.props.color).toBe('#00afaf')
  expect(await ui.find({ type: 'Link', text: '#142' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^5h runs out in ~6m$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^3 waiting for a core · node$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^⚠ migration pending$/ })).toBeDefined()
  await ui.unmount()
})

test('docked in the terminal with room, each part is spelled out under its heading', async ($, on) => {
  session(on, JSON_OUT)
  await $.command.run(TYPED)
  const ui = await $.ui.mount(pane('terminal', 'dock'))

  expect(await ui.find({ type: 'Text', text: /^Usage$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^Context  91% of 200k tokens$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^Branch   feat\/rewards$/ })).toBeDefined()
  await ui.unmount()
})

test('docked in a narrow terminal pane, the status line parts stack under headings', async ($, on) => {
  session(on, JSON_OUT)
  await $.command.run(TYPED)
  const narrow = pane('terminal', 'dock')
  const ui = await $.ui.mount({ ...narrow, props: { ...narrow.props, bodyColumns: 30 } })

  const headings = await ui.findAll({ type: 'Text', text: new RegExp(`^(${HEADINGS.join('|')})$`) })
  expect(headings.map(h => h.text)).toEqual(HEADINGS)
  await ui.unmount()
})

test('inline in the terminal, it stays the status line strip', async ($, on) => {
  session(on, JSON_OUT)
  await $.command.run(TYPED)
  const ui = await $.ui.mount(pane('terminal', 'inline'))

  expect(await ui.findAll({ type: 'Text', text: new RegExp(`^(${HEADINGS.join('|')})$`) })).toHaveLength(0)
  expect(await ui.find({ type: 'Text', text: /^ctx  5h  wk/ })).toBeDefined() // the tanks' labels start the last row
  await ui.unmount()
})

test('the terminal keeps the status line as text', async ($, on) => {
  session(on, JSON_OUT)
  await $.command.run(TYPED)
  const ui = await $.ui.mount(pane('terminal'))

  expect(await ui.findAll({ type: 'Svg' })).toHaveLength(0)
  expect(await ui.find({ type: 'Text', text: /acme-shop/ })).toBeDefined()
  await ui.unmount()
})

test('before the install has --json, the apps draw the text', async ($, on) => {
  session(on, TEXT_OUT)
  await $.command.run(TYPED)
  const ui = await $.ui.mount(pane('desktop'))

  expect(await ui.findAll({ type: 'Svg' })).toHaveLength(0)
  expect(await ui.find({ type: 'Text', text: /^main$/ })).toBeDefined()
  // and says how to get the rest
  expect(await ui.find({ type: 'Text', text: /install\.sh .* again for the full pane/ })).toBeDefined()
  await ui.unmount()
})

// How often the pane runs statusline.py, and when it doesn't. Each run costs
// about 50 ms of CPU in each session: a pane that runs when nobody can see
// it, or in a loop, costs every open session that much again.

const MINUTE = 60_000
const placed: UiPane = { id: 'statusline', title: 'Status', isShown: true, isFocused: false, isPlaced: true }

/** A session that counts the pane's runs and closes; `panes` is what $.ui.panes answers on each tick. */
function counted(on: On, panes: UiPane[]) {
  const clock = mock.clock(on, { now: BAD_DAY.now * 1000 })
  const seen = { runs: 0, closed: 0 }
  on('session.id', () => ({ value: 'a1b2c3d4-5e6f-4a1b-9c8d-0123456789ab' }))
  on('session.model', () => ({ value: 'claude-opus-5-5' }))
  on('session.cwd', () => ({ value: '/Users/dev/code/acme-shop' }))
  on('session.root', () => ({ value: '/Users/dev/code/acme-shop' }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { window: 200000, percent: 12 }, rateLimits: [] } }))
  on('session.version', () => ({ value: { version: '2.1.299', base: '2.1.299' } }))
  // beneath the mod: the session starting, and the engine taking its command
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('command.register', () => ({ value: { command: 'statusline-pane' } }))
  on('ui.open', () => ({ value: panes.some(p => p.isPlaced) ? { isPlaced: true } : { isPlaced: false, reason: 'no-surface' } }))
  on('ui.panes', () => ({ value: panes }))
  on('ui.close', () => {
    seen.closed++
    return { value: undefined }
  })
  on('process.run', () => {
    seen.runs++
    return ran(JSON_OUT)
  })
  return { clock, seen }
}

const sized = (surface: 'terminal' | 'desktop' | 'mobile', bodyColumns: number, placement: 'dock' | 'inline' = 'dock', isFullscreen = true) => {
  const base = pane(surface, placement)
  return { ...base, props: { ...base.props, bodyColumns }, viewport: { columns: bodyColumns, rows: 40, isFullscreen } }
}

const CWD = '/Users/dev/code/acme-shop'

test('a -p run, with nothing to draw on, never runs the status line', async ($, on) => {
  const { clock, seen } = counted(on, [])
  await $.session.start({ cwd: CWD, surface: null, isInteractive: false })
  await clock.advance(MINUTE)

  expect(seen.runs).toBe(0)
})

test('a pane that was never placed, or was closed, runs nothing', async ($, on) => {
  // a terminal under 144 columns: the unasked pane waits undrawn
  const { clock, seen } = counted(on, [{ ...placed, isPlaced: false, isShown: false }])
  await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
  await clock.advance(MINUTE)

  expect(seen.runs).toBe(0)
})

test('a pane on screen runs once a tick, no faster', async ($, on) => {
  const { clock, seen } = counted(on, [placed])
  await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
  await clock.advance(MINUTE)

  // fails if the timer goes, or runs faster than the status line's own readings change
  expect(seen.runs).toBe(MINUTE / EVERY_MS)
})

test('one session on two surfaces at different widths still runs about once a tick', async ($, on) => {
  // a terminal session also open on the phone: before, each surface's width
  // asked for a run at its own width, and the two took turns without end
  const { clock, seen } = counted(on, [placed])
  await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
  const terminal = await $.ui.mount(sized('terminal', 60))
  const phone = await $.ui.mount(sized('mobile', 38))
  await clock.advance(MINUTE)

  expect(seen.runs).toBeLessThanOrEqual(MINUTE / EVERY_MS + 2)
  await terminal.unmount()
  await phone.unmount()
})

test('unasked above the prompt of a terminal that is not fullscreen, the pane gives way', async ($, on) => {
  // tmux, or fullscreen off: there it would be the status line a second time
  const { seen } = counted(on, [placed])
  await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount(sized('terminal', 150, 'inline', false))

  expect(seen.closed).toBe(1)
  expect(await ui.find({ type: 'Text', text: /ctx/ })).toBeUndefined()
  await ui.unmount()
})

test('the status line is looked for beside the mod first: the install folder holding pane/', async () => {
  expect(parent('/Users/dev/.claude/claude-statusline/pane')).toBe('/Users/dev/.claude/claude-statusline')
  expect(parent('/Users/dev/.claude/claude-statusline/pane/')).toBe('/Users/dev/.claude/claude-statusline')
})
