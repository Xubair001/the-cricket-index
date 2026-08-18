import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { NewsArticleSummary, NewsSourceInfo } from '../api/types'
import { useGender } from '../gender/useGender'
import { ErrorMessage, SkeletonRows } from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'
import { NewsCard } from '../components/NewsItem'
import { EmptyState, PageHeader, Panel, Provenance, buttonClass, fieldClass } from '../components/ui'

const LIMIT = 20

/**
 * Cricket news from four publishers.
 *
 * Deliberately an index, not a reader. Every headline links out to the
 * publisher: nothing here is re-hosted, and the page's job is to say what has
 * been written and where to read it, not to substitute for the masthead that
 * wrote it.
 *
 * Two honesty devices, both borrowed from the Scout page's pattern of naming
 * what it could not do:
 *
 * - The source list includes the publishers that are switched OFF, with the
 *   reason. An archive gathered under per-publisher policies is a deliberate
 *   subset of cricket journalism, and hiding the exclusions would let it read
 *   as a survey of all of it.
 * - The gender filter is asymmetric and says so. "Women's" is a positive fact
 *   (the text carried explicit markers); "Men's" is only the absence of one.
 */
export function News() {
  const { slug, apiGender } = useGender()
  const [items, setItems] = useState<NewsArticleSummary[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [source, setSource] = useState('')
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [sources, setSources] = useState<NewsSourceInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.newsSources().then(setSources).catch(() => setSources([]))
  }, [])

  // Reset to page one whenever the question changes; leaving the offset means
  // a narrower filter can land on an empty page that looks like no results.
  useEffect(() => {
    setOffset(0)
  }, [apiGender, source, search])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .news({
        gender: apiGender,
        source: source || undefined,
        q: search || undefined,
        limit: LIMIT,
        offset,
      })
      .then((page) => {
        if (cancelled) return
        setItems(page.items)
        setTotal(page.total)
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [apiGender, source, search, offset])

  const enabled = sources.filter((s) => s.enabled)
  const disabled = sources.filter((s) => !s.enabled)

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={`${slug === 'men' ? "Men's" : "Women's"} cricket · four publishers`}
        title="Cricket News"
        blurb="Headlines, standfirsts and lead images gathered from each publisher's own feed or API. Every story links out to the masthead that wrote it."
      />

      <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-[10rem]">
          <span className="u-eyebrow block">Publisher</span>
          <select
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className={`${fieldClass} mt-1`}
          >
            <option value="">All publishers</option>
            {enabled.map((s) => (
              <option key={s.key} value={s.key}>
                {s.name} ({s.articles})
              </option>
            ))}
          </select>
        </label>

        <form
          className="flex min-w-[14rem] flex-1 items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            setSearch(query.trim())
          }}
        >
          <label className="min-w-0 flex-1">
            <span className="u-eyebrow block">Search</span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="A player, a side, a phrase"
              className={`${fieldClass} mt-1`}
            />
          </label>
          <button type="submit" className={buttonClass}>
            Search
          </button>
        </form>
      </div>

      {error ? (
        <ErrorMessage message={error} />
      ) : (
        <Panel
          title={`${total.toLocaleString()} ${total === 1 ? 'story' : 'stories'}`}
          blurb={
            apiGender === 'female'
              ? "Women's cricket, identified from explicit markers in the text. An article that names no side cannot be classified and is not listed here."
              : "Everything not identified as women's cricket. That is an absence rather than a finding: publishers do not mark men's cricket, so this is the unmarked default."
          }
          bodyClassName=""
        >
          {loading ? (
            <SkeletonRows rows={6} className="p-4" />
          ) : items.length === 0 ? (
            <EmptyState
              title="No stories match"
              hint={
                search
                  ? 'Try a broader phrase, or clear the publisher filter.'
                  : 'The feeds may not have been synced yet. Run the news sync from the ingestion worker.'
              }
            />
          ) : (
            items.map((a, i) => (
              <NewsCard
                key={a.article_id}
                article={a}
                to={`/${slug}/news/${a.article_id}`}
                eager={i < 6}
              />
            ))
          )}
        </Panel>
      )}

      {!loading && total > LIMIT && (
        <Pagination total={total} limit={LIMIT} offset={offset} onChange={setOffset} />
      )}

      <Panel
        title="Where this comes from"
        blurb="Each publisher is read through the most structured route it actually leaves open, and two are switched off on their own instructions."
        bodyClassName="divide-y divide-border-subtle"
      >
        {[...enabled, ...disabled].map((s) => (
          <div key={s.key} className="px-4 py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <span className="text-sm font-medium text-ink">
                {s.home_url ? (
                  <a
                    href={s.home_url}
                    target="_blank"
                    rel="noopener noreferrer external"
                    className="hover:text-analytic-ink"
                  >
                    {s.name}
                  </a>
                ) : (
                  s.name
                )}
              </span>
              <span className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.08em]">
                <span className="text-dim">{s.strategy}</span>
                {s.enabled ? (
                  <span className="tnum text-muted">{s.articles.toLocaleString()} held</span>
                ) : (
                  /* Not red. An excluded source is not an error or a failure -
                     it is a publisher's instruction being followed - and red
                     in this product means below par. */
                  <span className="rounded bg-elevated px-1.5 py-0.5 text-dim ring-1 ring-inset ring-border-default">
                    not ingested
                  </span>
                )}
              </span>
            </div>
            {s.policy_note && (
              <p className="mt-1 max-w-prose text-xs leading-relaxed text-muted">{s.policy_note}</p>
            )}
          </div>
        ))}
      </Panel>

      <Provenance>
        News is kept entirely separate from every figure this product computes. Nothing an article
        says feeds a ranking, an average or a form verdict - the same separation that keeps ICC's
        published ratings out of the ratings computed here. Articles are de-duplicated on the
        publisher's own article id and on a hash of what was extracted, so a story that is re-read
        or re-slugged is one row; a body that republishes another publisher's is marked rather than
        hidden, because a wire story running in three places is information. Images are referenced
        from each publisher's CDN and never copied. Some publishers permit only a headline and a
        lead image, so a story with no summary here is a licence boundary rather than a gap.
      </Provenance>
    </div>
  )
}
