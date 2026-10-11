import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { resolveConfig } from 'vite'

const root = fileURLToPath(new URL('../', import.meta.url))

test('Vite stores optimizer cache in this checkout, not shared dependencies', async () => {
  const config = await resolveConfig({ root, configFile: path.join(root, 'vite.config.js') }, 'serve')
  assert.equal(config.cacheDir, path.join(root, '.vite'))
})
