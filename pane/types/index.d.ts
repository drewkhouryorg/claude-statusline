// One run of text in one style, as the status line printed it.
export type Segment = { text: string; color?: string; backgroundColor?: string; bold?: boolean; dim?: boolean }

// The status line's colour names (statusline.py's TONES); the pane picks the paint.
export type Tone = 'sage' | 'olive' | 'terra' | 'brick' | 'amber' | 'cyan' | 'grey' | 'purple' | 'dim'

export type Words = { text: string; tone: Tone | null }

export type Tank = {
  label: 'ctx' | '5h' | 'wk'
  pct: number | null
  tone: Tone | null
  // how far through its window the clock is, 0..1; the limits only
  elapsed: number | null
  to_reset?: number | null
  to_full?: number | null
  projected?: number | null
  size?: number | null
}

export type Repo =
  | { git: false; name: string }
  | {
      git: true
      name: string
      worktree: string | null
      branch: string | null
      sha: string | null
      state: string | null
      marks: { kind: string; glyph: string; count: number; tone: Tone | null }[]
      status_unknown: boolean
      commit_age: number | null
      commit_tone: Tone | null
      pr: { number: number | string; url: string | null; checks: Words | null; review: Words | null } | null
    }

export type RunState = 'ok' | 'fail' | 'running' | 'cancelled'

export type Ship = {
  ci: { name: string; url: string | null; runs: RunState[]; stale_age: number | null }[]
  deploys: {
    env: string
    url: string | null
    status: 'ok' | 'fail' | 'running'
    version: string
    age: number | null
    behind: number
    behind_tone: Tone
    stale_age: number | null
  }[]
  prs: {
    url: string | null
    open: number
    needs_review: number
    items: { number: string; url: string | null; checks: 'pass' | 'fail' | 'pending' | 'none'; draft: boolean }[]
    stale_age: number | null
  } | null
}

export type Session = {
  model: string | null
  effort: string | null
  fast: boolean
  duration: number | null
  name: string | null
  id: string | null
  added: number | null
  removed: number | null
}

export type Five = { used: number; state: 'full' | 'out' | 'ok'; tone: Tone; to_reset: number | null; to_full: number | null }

export type Day = { name: string; pct: number | null; number: number | null; tone: Tone; when: 'past' | 'now' | 'later' }

export type Week = {
  used: number
  tone: Tone
  to_reset: number | null
  projected: number | null
  days: Day[]
  lines: Words[]
}

export type System = {
  cpu: { usage: number | null; tone: Tone; waiting: number; top: string | null }
  memory: {
    used_pct: number | null
    pressure: 'normal' | 'warn' | 'crit'
    tone: Tone
    comp_mb: number | null
    comp_trend: 'up' | 'down' | 'steady' | null
    swap_mb: number | null
    swap_trend: 'up' | 'down' | null
    top: { name: string; mb: number } | null
  }
  battery: { pct: number; tone: Tone } | null
}

// What `statusline.py --json` prints: each part as data, and the terminal drawing
export type View = {
  schema: 1
  now: number
  tanks: Tank[]
  repo: Repo
  ship: Ship | null
  session: Session
  five: Five | null
  week: Week | null
  system: System | null
  alerts: Words[]
  ansi: string
  // each part as the terminal draws it, apart, for a tall narrow pane; absent before the install had it
  blocks?: { name: Block; lines: string[] }[]
  // v0.1.0, with +commit when it isn't that release; null for an install from before versions, absent before the view had it
  version?: string | null
}

export type Block = 'tanks' | 'repo' | 'ship' | 'session' | 'week' | 'system' | 'alerts'

// `view` is absent where the install predates --json: the pane draws the text alone
export type Drawing = { lines: Segment[][]; view?: View; error?: string }

declare module 'claude-code' {
  interface PluginState {
    'statusline-pane': { drawing: Drawing; asked: boolean }
  }
}
