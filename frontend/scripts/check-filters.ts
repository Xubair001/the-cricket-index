/**
 * The filter-URL rules, checked.
 *
 * This repo has no test suite, and this file is not the start of one - it is the
 * one piece of the filter layer that is pure logic and easy to get subtly wrong,
 * so it is asserted rather than described. Two of these rules were written the
 * other way round first: `0` was being dropped as falsy, which silently restored
 * a control's default when a reader deliberately set a floor of nought.
 *
 *     npm run check:filters
 */
import { mergeFilterParams as merge } from '../src/state/useFilters'

const cases: [string, string][] = []
const check = (name: string, got: string, want: string) => {
  cases.push([name, got === want ? 'PASS' : `FAIL got=${got} want=${want}`])
}
const q = (s: string) => new URLSearchParams(s)

check('set drops the offset',
  merge(q('competition=tests&offset=40'), { sort_by: 'wickets' }, true).toString(),
  'competition=tests&sort_by=wickets')
check('keep preserves the offset',
  merge(q('competition=tests&offset=40'), { explain: 'abc' }, false).toString(),
  'competition=tests&offset=40&explain=abc')
check('paging writes its own offset through set',
  merge(q('offset=40'), { offset: 60 }, true).toString(), 'offset=60')
check('empty string removes the key',
  merge(q('team=22&offset=20'), { team: '' }, true).toString(), '')
check('null removes the key',
  merge(q('a=1&b=2&players=x'), { a: null, b: null }, true).toString(), 'players=x')
check('a number is written as text',
  merge(q(''), { min_matches: 30 }, true).toString(), 'min_matches=30')
check('paging back to page one clears the offset',
  merge(q('offset=20'), { offset: 0 }, false).toString(), '')
check('a zero FILTER is kept, because a floor of nought is a real choice',
  merge(q('min_matches=10'), { min_matches: 0 }, true).toString(), 'min_matches=0')
check('unrelated keys survive',
  merge(q('gender=male&sort=runs&offset=25'), { min_matches: 5 }, true).toString(),
  'gender=male&sort=runs&min_matches=5')
check('the input is not mutated', (() => {
  const before = q('a=1&offset=9')
  merge(before, { a: null }, true)
  return before.toString()
})(), 'a=1&offset=9')

for (const [name, verdict] of cases) console.log(verdict.padEnd(6), name)
const failed = cases.filter(([, v]) => v !== 'PASS').length
console.log(failed === 0 ? `\nOK  ${cases.length} merge rules hold.` : `\nFAIL ${failed} of ${cases.length}`)

// Throwing rather than setting an exit code: this runs under the app's
// tsconfig, which has no Node types, and a thrown error already fails the run.
if (failed > 0) throw new Error(`${failed} of ${cases.length} merge rules broken`)
