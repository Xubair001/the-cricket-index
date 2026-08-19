import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { TournamentSummary } from '../api/types'
import { useGender } from '../gender/useGender'
import { useScope } from '../scope/scope'
import { ErrorMessage, SkeletonRows } from '../components/LoadingSpinner'
import { EmptyState, PageHeader, Panel, Provenance } from '../components/ui'
import { count } from '../format'

/**
 * Tournaments and events.
 *
 * The page exists because `matches.event_name` holds 1,276 distinct events and
 * only 266 of them are tournaments - the rest are bilateral tours ("Pakistan
 * tour of England"), which are two sides playing a series. The API applies
 * that test on the number of sides that actually played, so what reaches here
 * is already the multi-team set; this page's job is to put the tournaments a
 * reader came looking for at the top without hiding the rest.
 *
 * Flagship events lead, then other ICC events, then everything else by volume.
 * That is ordering only. The count in the header says how many are held, so a
 * reader can see the tail is there rather than wondering what was filtered.
 */

function Row({ t, slug }: { t: TournamentSummary; slug: string }) {
  return (
    <Link
      to={`/${slug}/tournaments/${t.slug}`}
      className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border-subtle px-4 py-3 transition-colors last:border-0 hover:bg-elevated"
    >
      <span className="min-w-0 flex-1">
        <span className="text-sm font-medium text-ink">{t.name}</span>
        {t.is_icc && (
          <span
            className="ml-2 rounded bg-elevated px-1.5 py-0.5 align-middle font-mono text-[9px] uppercase tracking-[0.08em] text-muted ring-1 ring-inset ring-border-default"
            title="Run by the International Cricket Council"
          >
            ICC
          </span>
        )}
        <span className="mt-0.5 block text-xs text-dim">
          {t.competition_name} · {count(t.editions)} edition{t.editions === 1 ? '' : 's'} ·{' '}
          {count(t.sides)} sides
          {t.first_date && t.last_date && (
            <>
              {' '}
              · {t.first_date.slice(0, 4)}-{t.last_date.slice(0, 4)}
            </>
          )}
        </span>
      </span>

      {/* The most recent champion is the single fact a reader most often wants
          from a tournament list. A dash means the deciding match is not in
          this dataset, which the detail page explains rather than implying
          that nobody won. */}
      <span className="w-40 shrink-0 text-xs">
        <span className="block text-dim">{t.latest_season ?? '-'}</span>
        <span className="block text-ink">{t.latest_winner ?? '-'}</span>
      </span>
      <span className="tnum w-16 shrink-0 text-right text-sm text-muted">{count(t.matches)}</span>
    </Link>
  )
}

export function Tournaments() {
  const { slug, apiGender } = useGender()
  const { competitionType, family } = useScope()
  const [items, setItems] = useState<TournamentSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .tournaments(apiGender, { competition_type: competitionType })
      .then((res) => !cancelled && setItems(res))
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [apiGender, competitionType])

  const flagship = items.filter((t) => t.is_flagship)
  const rest = items.filter((t) => !t.is_flagship)

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={`${slug === 'men' ? "Men's" : "Women's"} ${
          family === 'league' ? 'league' : 'international'
        } cricket`}
        title="Tournaments"
        blurb="World Cups, the Champions Trophy, the Asia Cup and every other multi-team event in this dataset - each with its editions, its champions and its leading players."
      />

      {error ? (
        <ErrorMessage message={error} />
      ) : loading ? (
        <Panel title="Tournaments" bodyClassName="">
          <SkeletonRows rows={8} className="p-4" />
        </Panel>
      ) : items.length === 0 ? (
        <EmptyState
          title="No tournaments in this scope"
          hint="Franchise leagues are single competitions rather than multi-event tournaments. Switch to International at the top right."
        />
      ) : (
        <>
          {flagship.length > 0 && (
            <Panel
              title="Global tournaments"
              blurb="The world events. Ordering only - everything else is below, not hidden."
              bodyClassName=""
            >
              {flagship.map((t) => (
                <Row key={`${t.slug}-${t.competition_key}`} t={t} slug={slug} />
              ))}
            </Panel>
          )}

          {rest.length > 0 && (
            <Panel
              title={`Other events (${count(rest.length)})`}
              blurb="Qualifiers, regional competitions, development leagues and invitational series. Included because they are real cricket that this dataset holds, and because a qualifier is where most associate nations' record lives."
              bodyClassName=""
            >
              {rest.map((t) => (
                <Row key={`${t.slug}-${t.competition_key}`} t={t} slug={slug} />
              ))}
            </Panel>
          )}
        </>
      )}

      <Provenance>
        A tournament here is an event at least three different sides played in. That test is read
        off the data rather than from the name: `event_name` holds 1,276 distinct values and 1,013
        of them are bilateral tours, which a name-based rule would neither reliably exclude nor
        reliably catch. Cricsheet spells some tournaments several ways across their editions - the
        men's 50-over World Cup appears as three different names - and those are merged from a
        curated list checked against each edition's finalists, never by matching on shared words.
        Coverage is partial: this dataset does not hold every match of every edition, so an
        edition reports the matches held rather than a total.
      </Provenance>
    </div>
  )
}
