import type { Segment } from '../types'

// xterm's first 16 colours; the pane takes hex, so the status line's palette
// numbers are turned into what a 256-colour terminal would show
const BASIC = [
  '#000000', '#cd0000', '#00cd00', '#cdcd00', '#0000ee', '#cd00cd', '#00cdcd', '#e5e5e5',
  '#7f7f7f', '#ff0000', '#00ff00', '#ffff00', '#5c5cff', '#ff00ff', '#00ffff', '#ffffff',
]
const CUBE = [0, 95, 135, 175, 215, 255]

const basic = (n: number) => BASIC[n] ?? '#000000'
const level = (n: number) => CUBE[n] ?? 0

const hex = (r: number, g: number, b: number) =>
  '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('')

export function xterm256(n: number): string {
  if (n < 16) return basic(n)
  if (n < 232) {
    const i = n - 16
    return hex(level(Math.floor(i / 36)), level(Math.floor(i / 6) % 6), level(i % 6))
  }
  const gray = 8 + 10 * (n - 232)
  return hex(gray, gray, gray)
}

type Style = Omit<Segment, 'text'>

function applySgr(style: Style, params: number[]): Style {
  let next = { ...style }
  for (let i = 0; i < params.length; i++) {
    const p = params[i] ?? 0
    if (p === 0) next = {}
    else if (p === 1) next.bold = true
    else if (p === 2) next.dim = true
    else if (p === 22) next = { ...next, bold: undefined, dim: undefined }
    else if (p === 39) next.color = undefined
    else if (p === 49) next.backgroundColor = undefined
    else if (p >= 30 && p <= 37) next.color = basic(p - 30)
    else if (p >= 90 && p <= 97) next.color = basic(p - 90 + 8)
    else if (p >= 40 && p <= 47) next.backgroundColor = basic(p - 40)
    else if ((p === 38 || p === 48) && params[i + 1] === 5 && i + 2 < params.length) {
      next[p === 38 ? 'color' : 'backgroundColor'] = xterm256(params[i + 2] ?? 0)
      i += 2
    }
  }
  return next
}

// OSC sequences (the status line's hyperlinks) end in BEL or ESC \
const OSC = /\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g
const SGR = /\x1b\[([0-9;]*)m/g

/** Splits the status line's ANSI output into lines of styled runs. */
export function parseAnsi(output: string): Segment[][] {
  const lines: Segment[][] = []
  let style: Style = {}
  for (const raw of output.replace(OSC, '').replace(/\n+$/, '').split('\n')) {
    const line: Segment[] = []
    let at = 0
    for (const m of raw.matchAll(SGR)) {
      if (m.index > at) line.push({ ...style, text: raw.slice(at, m.index) })
      style = applySgr(style, !m[1] ? [0] : m[1].split(';').map(Number))
      at = m.index + m[0].length
    }
    if (at < raw.length) line.push({ ...style, text: raw.slice(at) })
    lines.push(line)
  }
  return lines
}
