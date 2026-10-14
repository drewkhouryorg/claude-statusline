import type { Elements, RenderElement } from 'claude-code'

import type { Repo, Session, Ship, System, Tone, View, Week, Words } from '../types'
import { barSvg, fiveWords, fmtAge, fmtDur, paint, tanksSvg, weekSvg } from './svg'

// the desktop and mobile apps both carry these four
export type AppElements = Pick<Elements['desktop'], 'Box' | 'Text' | 'Svg' | 'Link'>

const TWO_UP = 48 // the pane's columns a card needs before two share a row

const RUN = { ok: ['✓', 'sage'], fail: ['✗', 'brick'], running: ['⟳', 'amber'], cancelled: ['○', 'dim'] } as const
const CHECK = { pass: ['✓', 'sage'], fail: ['✗', 'brick'], pending: ['⟳', 'amber'], none: ['·', 'dim'] } as const

/**
 * The status line as the app draws it: a card per part, one to a row in a
 * side pane and two side by side once it's wide (`columns`, the pane's body), with the tanks, the week and the machine drawn as SVG and the
 * rest as text in the status line's colours.
 */
export function appView(el: AppElements, v: View, columns: number): RenderElement {
  const { Box, Text, Svg, Link } = el
  // two cards to a row only where each still has a side pane's room
  const across = columns >= 2 * TWO_UP ? 2 : 1

  const words = (w: Words, key?: string) =>
    w.tone === 'dim' ? <Text key={key} dimColor>{w.text}</Text> : <Text key={key} color={paint(w.tone)}>{w.text}</Text>

  // a card's lines sit close; only its title stands apart. Its width is a share
  // of the row, so a card never runs past the pane's edge
  const card = (key: string, title: string, body: RenderElement[]) => (
    <Box key={key} flexDirection="column" padding={1} width={across === 2 ? '49%' : '100%'} borderStyle="round" borderColor="subtle">
      <Box marginBottom={1}>
        <Text dimColor bold>{title}</Text>
      </Box>
      {body}
    </Box>
  )

  const row = (key: string, parts: (RenderElement | false | null | undefined)[]) => (
    <Box key={key} flexDirection="row" flexWrap="wrap" columnGap={1} alignItems="center">
      {parts.filter((p): p is RenderElement => !!p)}
    </Box>
  )

  const link = (url: string | null, label: string, key: string) =>
    url && /^https?:\/\//.test(url) ? <Link key={key} href={url} label={label} /> : <Text key={key}>{label}</Text>

  const stale = (age: number | null) => age != null && <Text dimColor>{`${fmtAge(age)} old`}</Text>

  function usage(): RenderElement {
    const five = v.five && fiveWords(v.five)
    return card('usage', 'Usage', [
      <Svg key="tanks" source={tanksSvg(v.tanks)} alt={v.tanks.map(t => `${t.label} ${t.pct ?? '--'}%`).join(', ')} />,
      ...(five ? [words(five, 'five')] : []),
    ])
  }

  function week(w: Week): RenderElement {
    if (w.days.length === 0) return card('week', 'Week', [<Text key="used">{`${Math.round(w.used)}% used`}</Text>])
    return card('week', 'Week', [
      <Svg key="chart" source={weekSvg(w)} alt={w.days.map(d => `${d.name} ${d.number ?? '-'}%`).join(', ')} />,
      <Box key="lines" flexDirection="column">{w.lines.map((l, i) => words(l, `l${i}`))}</Box>,
    ])
  }

  function repo(r: Repo): RenderElement {
    if (!r.git) return card('repo', 'Repo', [<Text key="name" bold>{r.name}</Text>, <Text key="git" dimColor>no git</Text>])
    const where = r.branch ? <Text key="b" color={paint('cyan')}>{r.branch}</Text> : <Text key="b" color={paint('olive')}>{`detached ${r.sha ?? ''}`}</Text>
    const changes = r.marks.length
      ? r.marks.map(m => (m.tone === 'dim' ? <Text key={m.kind} dimColor>{`${m.glyph}${m.count}`}</Text> : <Text key={m.kind} color={paint(m.tone)}>{`${m.glyph}${m.count}`}</Text>))
      : [<Text key="clean" dimColor>{r.status_unknown ? 'git slow' : 'clean'}</Text>]
    const age =
      r.commit_age != null &&
      (r.commit_tone === 'dim' || !r.commit_tone ? (
        <Text key="age" dimColor>{`committed ${fmtAge(r.commit_age)} ago`}</Text>
      ) : (
        <Text key="age" color={paint(r.commit_tone)}>{`committed ${fmtAge(r.commit_age)} ago`}</Text>
      ))
    return card('repo', 'Repo', [
      row('name', [<Text key="n" bold>{r.name}</Text>, !!r.worktree && <Text key="wt" dimColor>{`worktree ${r.worktree}`}</Text>]),
      row('branch', [where, !!r.state && <Text key="s" color={paint('olive')}>{r.state}</Text>]),
      row('changes', [...changes, age]),
      r.pr && row('pr', [link(r.pr.url, `#${r.pr.number}`, 'n'), r.pr.checks && words(r.pr.checks, 'c'), r.pr.review && words(r.pr.review, 'r')]),
    ].filter((x): x is RenderElement => !!x))
  }

  function ship(s: Ship): RenderElement {
    const ci = s.ci.map((c, i) =>
      row(`ci${i}`, [
        link(c.url, c.name, 'n'),
        <Text key="runs">{c.runs.map((r, j) => <Text key={`r${j}`} color={paint(RUN[r][1])}>{RUN[r][0]}</Text>)}</Text>,
        stale(c.stale_age),
      ]),
    )
    const deploys = s.deploys.map((d, i) =>
      row(`dep${i}`, [
        link(d.url, d.env, 'n'),
        d.status === 'fail' ? <Text key="s" color={paint('brick')}>✗ deploy failed</Text>
          : d.status === 'running' ? <Text key="s" color={paint('amber')}>⟳ deploying</Text>
          : <Text key="s"><Text color={paint('sage')}>✓</Text>{` ${d.version}`}</Text>,
        d.age != null && d.status !== 'running' && <Text key="age" dimColor>{fmtAge(d.age)}</Text>,
        d.behind > 0 && <Text key="behind" color={paint(d.behind_tone)}>{`${d.behind} behind`}</Text>,
        stale(d.stale_age),
      ]),
    )
    const prs = s.prs && row('prs', [
      <Text key="label" dimColor>PRs</Text>,
      ...(s.prs.items.length
        ? s.prs.items.map((p, i) => (
            <Box key={`p${i}`} flexDirection="row">
              {link(p.url, `#${p.number}`, 'n')}
              <Text color={paint(CHECK[p.checks][1])}>{CHECK[p.checks][0]}</Text>
            </Box>
          ))
        : [<Text key="open">{`${s.prs.open} open`}</Text>]),
      s.prs.needs_review > 0 && <Text key="review" color={paint('olive')}>{`${s.prs.needs_review} need review`}</Text>,
      stale(s.prs.stale_age),
    ])
    return card('ship', 'Ship', [...ci, ...deploys, ...(prs ? [prs] : [])])
  }

  function session(s: Session): RenderElement {
    // the mod API doesn't give the session's name, so a missing one isn't "untitled": leave it out
    return card('session', 'Session', [
      row('model', [
        <Text key="m" bold>{s.model ?? '?'}</Text>,
        !!s.effort && <Text key="e" dimColor>{s.effort}</Text>,
        s.fast && <Text key="f" color={paint('amber')}>fast</Text>,
        s.duration != null && <Text key="d">{fmtDur(s.duration)}</Text>,
      ]),
      !!s.name && <Text key="name">{s.name}</Text>,
      row('id', [
        !!s.id && <Text key="id" dimColor>{s.id}</Text>,
        !!(s.added || s.removed) && <Text key="add" color={paint('sage')}>{`+${s.added ?? 0}`}</Text>,
        !!(s.added || s.removed) && <Text key="rm" color={paint('brick')}>{`−${s.removed ?? 0}`}</Text>,
      ]),
    ].filter((x): x is RenderElement => !!x))
  }

  // a meter: the label and percent as the card's own text, so they never
  // shrink, and between them a thin bar drawn to the room left. The labels
  // are the status line's own, cpu and mem: the same length, so the bars match
  const meter = (key: string, label: string, pct: number | null, tone: Tone) => (
    <Box key={key} flexDirection="row" alignItems="center" columnGap={1}>
      <Box width={3}>
        <Text dimColor>{label}</Text>
      </Box>
      <Box flexGrow={1}>
        <Svg source={barSvg(pct, tone)} alt={`${label} ${pct === null ? 'no reading' : `${Math.round(pct)}%`}`} />
      </Box>
      <Box width={5} justifyContent="flex-end">
        {pct === null ? <Text dimColor>--</Text> : <Text>{`${Math.round(pct)}%`}</Text>}
      </Box>
    </Box>
  )

  function machine(s: System): RenderElement {
    const mem = s.memory
    const arrow = { up: '↑', down: '↓', steady: '→' } as const
    const flow = [
      mem.comp_mb != null && `compressed ${(mem.comp_mb / 1024).toFixed(1)}G${mem.comp_trend ? ' ' + arrow[mem.comp_trend] : ''}`,
      mem.swap_mb != null && mem.swap_trend && `swap ${(mem.swap_mb / 1024).toFixed(1)}G ${arrow[mem.swap_trend]}`,
    ].filter(Boolean).join(' · ')
    return card('system', 'System', [
      meter('cpu', 'cpu', s.cpu.usage, s.cpu.tone),
      meter('mem', 'mem', mem.used_pct, mem.tone),
      s.cpu.waiting > 0 && <Text key="wait" color={paint('brick')}>{`${s.cpu.waiting} waiting for a core${s.cpu.top ? ` · ${s.cpu.top}` : ''}`}</Text>,
      mem.pressure !== 'normal' && (
        <Text key="pressure" color={paint(mem.tone)}>
          {`memory pressure ${mem.pressure}${mem.top ? ` · quitting ${mem.top.name} frees ${(mem.top.mb / 1024).toFixed(1)}G` : ''}`}
        </Text>
      ),
      flow && <Text key="flow" dimColor>{flow}</Text>,
      s.battery && <Text key="batt" color={paint(s.battery.tone)}>{`battery ${s.battery.pct}%`}</Text>,
    ].filter((x): x is RenderElement => !!x))
  }

  const cards = [usage(), v.week && week(v.week), repo(v.repo), v.ship && ship(v.ship), session(v.session), v.system && machine(v.system)]

  return (
    <Box flexDirection="column" rowGap={1}>
      {v.alerts.map((a, i) => (
        <Box key={`alert${i}`} paddingX={1} borderStyle="round" borderColor={paint(a.tone) ?? 'warning'}>
          {words(a)}
        </Box>
      ))}
      <Box flexDirection="row" flexWrap="wrap" justifyContent="space-between" rowGap={1} width="100%">
        {cards.filter((c): c is RenderElement => !!c)}
      </Box>
    </Box>
  )
}
