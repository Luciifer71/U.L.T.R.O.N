import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

/*
 * Windows and macOS ignore letter case in file names, and Vite resolves an
 * extensionless import by trying .ts before .tsx. So `HoloHands.tsx` next to
 * `holoHands.ts` makes `import HoloHands from './HoloHands'` load the wrong file
 * there (a blank page), while Linux CI passes. Keep module names unique
 * ignoring case and extension.
 */
const SOURCE = /\.(m?[jt]sx?)$/

function modules(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return modules(path)
    return SOURCE.test(name) ? [path] : []
  })
}

describe('module names', () => {
  test('no two modules differ only by letter case or extension', () => {
    const seen = new Map<string, string>()
    const clashes: string[] = []
    for (const root of ['src', 'tests']) {
      for (const path of modules(root)) {
        const key = relative('.', path).replace(SOURCE, '').toLowerCase()
        const other = seen.get(key)
        if (other) clashes.push(`${other} <-> ${path}`)
        else seen.set(key, path)
      }
    }
    assert.deepEqual(clashes, [])
  })
})
