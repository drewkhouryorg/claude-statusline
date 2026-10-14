import { expect, test } from 'claude-code/testing'

import { meter, tankRows, tankSize, termView, week } from '../hooks/term'
import type { Segment, Tank } from '../types'
import { BAD_DAY } from './fixtures/bad-day'

const text = (line: Segment[]) => line.map(s => s.text).join('')
const lines = (width: number) => termView(BAD_DAY, width).map(text)

test('each part has its heading with a rule under it as wide as the pane', async () => {
  const out = lines(46)
  const headings = out.filter((l, i) => out[i + 1] === '─'.repeat(46))

  expect(headings).toEqual(['Needs you', 'Usage', 'Week', 'Repo', 'Ship', 'Session', 'System'])
})

test("the tanks' clock arrow has a column of its own, so the walls stay whole", async () => {
  // bad day: the 5h and week windows each have a clock; every row keeps both walls
  const rows = tankRows(BAD_DAY.tanks, 46).slice(1, -1).map(text)
  const { w } = tankSize(46)

  for (const row of rows) {
    expect(row.split('▕').length - 1).toBe(3)
    expect(row.split('▏').length - 1).toBe(3)
  }
  expect(rows.join('').split('◂').length - 1).toBe(2)
  expect(rows.every(r => r.length === rows[0]!.length)).toBe(true)
  expect(w).toBeGreaterThan(4)
})

test('tanks grow with the pane, within reason', async () => {
  expect(tankSize(28)).toEqual({ w: 4, h: 5 })
  expect(tankSize(34)).toEqual({ w: 5, h: 6 })
  expect(tankSize(120)).toEqual({ w: 6, h: 6 })
})

test('where the pace lands is one dashed line, not a fill', async () => {
  // a quiet week so far (18%) on course for 98%: a marker near the top, the rest empty
  const quiet: Tank = { label: 'wk', pct: 18, tone: 'olive', elapsed: 0.2, projected: 98 }
  const inside = tankRows([quiet], 46).slice(1, -1).map(r => text(r).slice(1, 1 + tankSize(46).w))

  expect(inside.filter(r => r.includes('╌'))).toHaveLength(1)
  expect(inside[0]).toMatch(/^╌+$/)
  expect(inside.join('')).not.toContain('░')
})

test('a pace past the top is the arrow by the number, not a line', async () => {
  const hot: Tank = { label: '5h', pct: 40, tone: 'brick', elapsed: 0.2, projected: 200 }
  const rows = tankRows([hot], 46).map(text)

  expect(rows[0]).toContain('40%↑')
  expect(rows.join('')).not.toContain('╌')
})

test('things are said in words: what each number is', async () => {
  const out = lines(46)

  expect(out).toContain('Context  91% of 200k tokens')
  expect(out).toContain('5-hour   94% · runs out in ~6m')
  expect(out).toContain('Week     71% · on pace for ~83% at reset')
  expect(out).toContain('Model    Opus 5.5 · xhigh effort')
})

test("the week's chart has the whole row, a slot a day, its words under it", async () => {
  const out = week(BAD_DAY.week!, 46).map(text)
  const numbers = out[4]!.trim().split(/\s+/)
  const names = out[5]!.trim().split(/\s+/)

  expect(numbers).toEqual(BAD_DAY.week!.days.map(d => String(d.number)))
  expect(names).toEqual(['Fri', 'Sat', 'Sun', 'Mon', 'Tue', 'Wed', 'Thu'])
  expect(out.slice(-3)).toEqual(['71% now', '~83% by Fri 6am', '29% left for Thu'])
})

test('meters widen with the pane', async () => {
  const bar = (width: number) => text(meter('CPU', 50, 'sage', width)).replace(/[^█░]/g, '').length

  expect(bar(60)).toBeGreaterThan(bar(40))
  expect(text(meter('CPU', 50, 'sage', 40)).length).toBe(40)
})

test("changes are spelled out where they fit, else written short", async () => {
  expect(lines(80)).toContain('Changes  ●7 staged · ✚4 modified · ↑5 ahead · ↓2 behind')
  expect(lines(46)).toContain('Changes  ●7 ✚4 ↑5 ↓2')
})
