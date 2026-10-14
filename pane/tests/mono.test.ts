import { expect, test } from 'claude-code/testing'

import { hasMono } from '../hooks/register'

test('mono is used from 2.1.299 on, development builds included', async () => {
  expect(hasMono('2.1.295')).toBe(false) // the desktop app's, which refuses it
  expect(hasMono('2.1.299')).toBe(true)
  expect(hasMono('2.1.299-dev')).toBe(true)
  expect(hasMono('2.2.0')).toBe(true)
  expect(hasMono('3.0.0')).toBe(true)
})

test('a version it cannot read gets no mono, the safe side', async () => {
  expect(hasMono(undefined)).toBe(false)
  expect(hasMono('nightly')).toBe(false)
})
