export const meta = {
  name: 'statusline-review',
  description: 'Five specialist reviewers on a claude-statusline branch; the skeptic re-checks each one\'s findings',
  whenToUse: 'Before merging a claude-statusline branch. args: { repo, scratch, branch, base (default main), context (what the branch is, the setup, what is already decided) }',
  phases: [
    { title: 'Review', detail: 'Ines (performance), Kofi (security), Rosa (platforms), Wren (docs and sense), Priya (tests)' },
    { title: 'Verify', detail: 'Sable re-checks each reviewer\'s findings' },
  ],
}

const REPO = args.repo
const SCRATCH = args.scratch
const BRANCH = args.branch
const BASE = args.base || 'main'
const CONTEXT = args.context || ''

const REVIEWERS = [
  { key: 'perf', name: 'Ines Halloran', brief: 'ines-performance.md' },
  { key: 'sec', name: 'Kofi Asante', brief: 'kofi-security.md' },
  { key: 'plat', name: 'Rosa Lindqvist', brief: 'rosa-platforms.md' },
  { key: 'docs', name: 'Wren Okafor', brief: 'wren-docs.md' },
  { key: 'tests', name: 'Priya Raman', brief: 'priya-tests.md' },
]

const FINDINGS = {
  type: 'object',
  properties: {
    verdict: { type: 'string', description: 'one line: ship / ship with changes / fix first / rethink, then why' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string', description: 'short id, unique within your report, e.g. 1, 2, 3' },
          title: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          problem: { type: 'string', description: 'what a user would notice, in plain words' },
          who: { type: 'string', description: 'who hits it and when' },
          evidence: { type: 'string', description: 'file:line, commands run and their output, measurements' },
          fix: { type: 'string', description: 'the change you would make, naming files' },
          basis: { type: 'string', enum: ['measured', 'demonstrated', 'probed', 'from reading'] },
        },
        required: ['id', 'title', 'severity', 'problem', 'who', 'evidence', 'fix', 'basis'],
      },
    },
    works: { type: 'array', items: { type: 'string' } },
    dropped: { type: 'integer', description: 'how many weaker findings you left out' },
  },
  required: ['verdict', 'findings', 'works', 'dropped'],
}

const CHECKED = {
  type: 'object',
  properties: {
    items: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          call: { type: 'string', enum: ['confirmed', 'raised', 'downgraded', 'trivial', 'refuted'] },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low', 'none'] },
          evidence: { type: 'string', description: 'what you checked or ran, and what it showed' },
        },
        required: ['id', 'call', 'severity', 'evidence'],
      },
    },
  },
  required: ['items'],
}

const brief = r => `You are ${r.name}. Your brief is ${REPO}/.claude/agents/${r.brief}: read it first and follow it exactly, including its house rules. In it, <repo> means ${REPO} and <base> means ${BASE}. A scratch folder you may write to: ${SCRATCH}.`

const results = await pipeline(
  REVIEWERS,
  r => agent(`${brief(r)}

Review the branch ${BRANCH} in ${REPO} (git -C ${REPO} log --oneline ${BASE}..HEAD). The person asking wants a full review before merging: don't boil the ocean with trivial stuff, but make sure nothing important is missed.

${CONTEXT}

Return your report through the structured output. Keep to findings that would change what someone does; drop the rest and count them in "dropped".`,
    { label: `${r.name} (${r.key})`, phase: 'Review', schema: FINDINGS }),
  (report, r) => {
    if (!report) return null
    if (!report.findings.length) return { reviewer: r, report, checked: [] }
    return agent(`You are Sable Ortiz. Your brief is ${REPO}/.claude/agents/sable-skeptic.md: read it first and follow it exactly. In it, <repo> means ${REPO} and <base> means ${BASE}. A scratch folder you may write to: ${SCRATCH}.

${r.name} reviewed the branch ${BRANCH} in ${REPO} for the ${r.key} angle. Re-check every finding below before anyone acts on it: go to the evidence yourself, re-run what can be re-run, try to refute it, and rate it for this project.

${CONTEXT}

${r.name.toUpperCase()}'S FINDINGS:
${JSON.stringify(report.findings, null, 1)}`,
      { label: `Sable on ${r.name}`, phase: 'Verify', schema: CHECKED })
      .then(checked => ({ reviewer: r, report, checked: checked ? checked.items : null }))
  },
)

const out = results.filter(Boolean).map(({ reviewer, report, checked }) => ({
  reviewer: reviewer.name,
  angle: reviewer.key,
  verdict: report.verdict,
  works: report.works,
  dropped: report.dropped,
  findings: report.findings.map(f => {
    const c = (checked || []).find(x => x.id === f.id)
    return { ...f, sable: c ? { call: c.call, severity: c.severity, evidence: c.evidence } : 'not checked' }
  }),
}))
const missing = REVIEWERS.filter(r => !out.some(o => o.angle === r.key)).map(r => r.name)
if (missing.length) log(`no report from: ${missing.join(', ')}`)
return { reports: out, missing }
