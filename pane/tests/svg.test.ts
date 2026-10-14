import { expect, test } from 'claude-code/testing'

import { dayTitle, esc, fiveWords, fmtAge, fmtDur, PAINT, tankTitle, tanksSvg, weekSvg } from '../hooks/svg'
import type { Tank } from '../types'
import { BAD_DAY } from './fixtures/bad-day'

const tank = (label: Tank['label']) => BAD_DAY.tanks.find(t => t.label === label)!

test('durations and ages read as the terminal writes them', async () => {
  expect(fmtDur(5400)).toBe('1h30m')
  expect(fmtDur(2 * 86400 + 4 * 3600)).toBe('2d4h')
  expect(fmtDur(45)).toBe('45s')
  expect(fmtAge(11400)).toBe('3h')
  expect(fmtAge(720)).toBe('12m')
})

test('a tank is drawn in its pace colour, with its number on top', async () => {
  // bad day: the 5h tank is at 94% and red
  const svg = tanksSvg([tank('5h')])

  expect(svg).toContain(`fill="${PAINT.brick}"`)
  expect(svg).toContain('>94%</text>')
})

test('a limit tank gets the clock notch, the context tank does not', async () => {
  const notch = /<path d="M [\d.]+ [\d.]+ l 8 -5 v 10 z"/

  expect(tanksSvg([tank('5h')])).toMatch(notch)
  expect(tanksSvg([tank('ctx')])).not.toMatch(notch)
})

test('a pace past 100% puts an arrow over the tank', async () => {
  // 5h is on course for 300%; the week ends near 83%
  const arrow = /l -6 6 h 12 z/

  expect(tanksSvg([tank('5h')])).toMatch(arrow)
  expect(tanksSvg([tank('wk')])).not.toMatch(arrow)
})

test('where the pace lands is a dashed line, not a fill, as in the terminal', async () => {
  // the week: 71% used, landing near 83% at reset
  const svg = tanksSvg([tank('wk')])

  expect(svg.match(/<line [^>]*stroke-dasharray/g)).toHaveLength(1)
  expect(svg).not.toContain('opacity=')
})

test('a pace past the top has no line, only the arrow', async () => {
  expect(tanksSvg([tank('5h')])).not.toMatch(/<line [^>]*stroke-dasharray/)
})

test('a tank with no reading says so and has no fill', async () => {
  const empty: Tank = { label: 'ctx', pct: null, tone: null, elapsed: null }
  const svg = tanksSvg([empty])

  expect(svg).toContain('>--</text>')
  expect(svg).not.toContain('fill="#')
  expect(tankTitle(empty)).toBe('Context window: no reading yet')
})

test('a tank tooltip says the level, the reset and where the pace lands', async () => {
  expect(tankTitle(tank('5h'))).toBe('5-hour limit: 94% used · resets in 3h26m · at this pace ~300% by then')
})

test('the week draws a bar per day, days to come dashed', async () => {
  const svg = weekSvg(BAD_DAY.week!)

  expect(svg.match(/<rect x=/g)?.length).toBe(BAD_DAY.week!.days.length)
  expect(svg.match(/stroke-dasharray="3 3"/g)?.length).toBe(1) // Thu, the one day to come
})

test('a day tooltip says what it spent, or what is left for it', async () => {
  const [fri, , , , , wed, thu] = BAD_DAY.week!.days

  expect(dayTitle(fri!)).toBe('Fri: 12% of the week')
  expect(dayTitle(wed!)).toBe('Wed (today): 11% of the week')
  expect(dayTitle(thu!)).toBe('Thu: 29% of the week left for it, if today stops here')
})

test('the 5h window says when it runs out before the reset', async () => {
  expect(fiveWords(BAD_DAY.five!)).toEqual({ text: '5h runs out in ~6m', tone: 'brick' })
})

test('names from a repo cannot break out of the SVG', async () => {
  expect(esc('<script>"x" & y')).toBe('&lt;script&gt;&quot;x&quot; &amp; y')
})
