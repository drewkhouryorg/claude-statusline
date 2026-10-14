import { expect, test } from 'claude-code/testing'

import { displayName } from '../hooks/register'

test('a model id reads as the name Claude Code shows', async () => {
  expect(displayName('claude-opus-5-5')).toBe('Opus 5.5')
  expect(displayName('claude-fable-5-1')).toBe('Fable 5.1')
  expect(displayName('claude-haiku-5-5-20260301')).toBe('Haiku 5.5')
  expect(displayName('claude-sonnet-5-5[1m]')).toBe('Sonnet 5.5')
})

test('a name it does not recognise is shown as given', async () => {
  expect(displayName('Opus 5.5')).toBe('Opus 5.5')
  expect(displayName('us.anthropic.claude-opus-5-5')).toBe('us.anthropic.claude-opus-5-5')
})
