import { expect, test } from 'claude-code/testing'

import { parseAnsi, xterm256 } from '../hooks/ansi'

// The escapes statusline.py writes: dim (2), a 256-colour foreground
// (38;5;N), the bold black-on-colour badge (1;38;5;16;48;5;N), and OSC 8
// hyperlinks around a PR number.
const ESC = '\x1b'
const DIM = `${ESC}[2m`
const RESET = `${ESC}[0m`
const fg = (n: number) => `${ESC}[38;5;${n}m`
const badge = (n: number) => `${ESC}[1;38;5;16;48;5;${n}m`
const link = (url: string, text: string) => `${ESC}]8;;${url}${ESC}\\${text}${ESC}]8;;${ESC}\\`

test('a palette colour becomes the hex a 256-colour terminal shows', async () => {
  expect(xterm256(37)).toBe('#00afaf') // the branch colour
  expect(xterm256(16)).toBe('#000000') // the badge's text
  expect(xterm256(244)).toBe('#808080') // the grey ramp
})

test('each styled run keeps its own colour, and a reset clears it', async () => {
  const [line] = parseAnsi(`${DIM} · ${RESET}${fg(37)}main${RESET} plain`)

  expect(line).toEqual([
    { dim: true, text: ' · ' },
    { color: '#00afaf', text: 'main' },
    { text: ' plain' },
  ])
})

test('a badge is bold with a background', async () => {
  const [line] = parseAnsi(`${badge(167)} CI failed ${RESET}`)

  expect(line?.[0]).toEqual({ bold: true, color: '#000000', backgroundColor: '#d75f5f', text: ' CI failed ' })
})

test('hyperlink escapes are dropped and their text kept', async () => {
  const [line] = parseAnsi(`PR ${link('https://github.com/acme/shop/pull/142', '#142')}`)

  expect(line?.map(s => s.text).join('')).toBe('PR #142')
})

test('an empty row between rows stays a row', async () => {
  expect(parseAnsi('one\n\ntwo\n')).toEqual([[{ text: 'one' }], [], [{ text: 'two' }]])
})
