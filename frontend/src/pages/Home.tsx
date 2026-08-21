import { useEffect, useState } from 'react'
import { ActionLink } from '../components/ActionLink'
import { ArrowExternal, ArrowRight } from '../components/Icon'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type {
  DashboardStats,
  FormLeaderRow,
  IccMovementReport,
  NewsArticleSummary,
} from '../api/types'
import { useGender } from '../gender/useGender'
import type { ApiGender } from '../gender/useGender'
import { ParMeter } from '../components/ParMeter'
import { SkeletonRows } from '../components/LoadingSpinner'
import { Provenance, Uncertain } from '../components/ui'
import { PlayerName } from '../components/PlayerName'
import { NewsRow, SourceChip } from '../components/NewsItem'
import { change, score, timeAgo } from '../format'

/**
 * The landing page.
 *
 * Its job is to say "cricket intelligence, not cricket scores" within one
 * screen, so it opens with questions a person can act on rather than a wall of
 * totals. The counts are present but small and below the fold of attention -
 * they establish the dataset's size, they are not the product.
 *
 * The hero is the par scale rather than a headline figure. Every board on this
 * page is ordered on par units, and a reader who has not been told what 1.00
 * means cannot read any of them; putting the unit first turns the boards from
 * a list of names into something checkable. It is also the one device that is
 * particular to this product - par here is fitted against the strength of the
 * opposition, not against a raw average.
 *
 * Every section above the fold is a computed entry point into the product. The
 * news strip at the foot is the one exception and is placed there on purpose.
 *
 * §6 originally ruled a news feed out, and the reason was sound: a feed at the
 * top would make this look like a scores-and-headlines site, which is the one
 * thing the page exists to say it is not. What changed is that the news is now
 * ingested with the same separation the rest of the product keeps - it feeds no
 * derived figure, it is attributed to the masthead that wrote it, and every
 * headline links out rather than being re-hosted. So it sits BELOW the computed
 * boards and the dataset counts, reads as a strip rather than a feed, and is
 * capped at four stories. It is a way out to the sources, not the product.
 */

/*
 * The hero's actions, split into one PRIMARY and the rest.
 *
 * Five equally-weighted bordered pills gave a reader no idea where to start, and
 * a landing page whose calls to action are all the same weight has none. Finding
 * a player is the entry point every other surface hangs off - a profile links to
 * form, splits, comparison and the boards - so it takes the solid treatment and
 * everything else steps back to a quieter one.
 */
const PRIMARY_ACTION = {
  label: 'Find a player',
  to: 'players',
  hint: 'Search and filter the full register',
}

const SECONDARY_ACTIONS = [
  { label: 'Compare', to: 'compare', hint: 'Up to four careers side by side' },
  { label: 'Build a Best XI', to: 'best-xi', hint: 'Picked to a role shape, with the trade-offs shown' },
  { label: 'Rankings', to: 'rankings', hint: 'Computed from ball-level aggregates' },
  { label: 'ICC rankings', to: 'icc-rankings', hint: 'Official published ratings, kept separate' },
]

/*
 * What this product can actually answer, on the landing page.
 *
 * Everything below the hero used to be three form boards, so a first-time
 * reader could not tell that Scout, Best XI, venue intelligence, tournaments or
 * availability existed at all - they were reachable only from a collapsed
 * sidebar group. Each card leads with the QUESTION it answers rather than the
 * feature name, which is Section 2's first rule applied to navigation: if nobody
 * can name the cricket question a thing answers, it should not be there.
 */
const CAPABILITIES = [
  {
    to: 'scout',
    question: 'Who fits this brief?',
    label: 'Scout',
    detail:
      'State a need - format, role, hand, age, form - and get ranked candidates. Constraints the data cannot honour are named on screen, not dropped.',
  },
  {
    to: 'best-xi',
    question: 'Who are the best eleven?',
    label: 'Best XI',
    detail:
      'A side filled to a role shape, for one of seven objectives, with the highest-rated player left out and the constraint that left them out.',
  },
  {
    to: 'analytics/venues',
    question: 'What kind of cricket does this ground produce?',
    label: 'Venue intelligence',
    detail:
      'Scoring and wicket character per format, and who wins batting first, derived from the toss across 408 grounds.',
  },
  {
    to: 'tournaments',
    question: 'Who won it, and how?',
    label: 'Tournaments',
    detail:
      'World Cups and global events by edition: the table, every fixture, the leading run-scorers and wicket-takers.',
  },
  {
    to: 'performance-index',
    question: 'Who is playing the best cricket?',
    label: 'Performance Index',
    detail:
      'A rating with every component shown, its weight, and what it was measured against. Never a bare number.',
  },
  {
    to: 'availability',
    question: 'Who is committed in this window?',
    label: 'Availability',
    detail:
      'Commitments from announced squads, with the share of the window actually announced above the results.',
  },
]

function TrendGlyph({ trend }: { trend: FormLeaderRow['trend'] }) {
  const glyph = { rising: '\u2197', flat: '\u2192', falling: '\u2198', unknown: '·' }[trend]
  const tone =
    trend === 'rising' ? 'text-positive-ink' : trend === 'falling' ? 'text-negative-ink' : 'text-dim'
  const description = {
    rising: 'Improving within the recent window',
    flat: 'Level within the recent window',
    falling: 'Declining within the recent window',
    unknown: 'Not enough cricket to read a trend',
  }[trend]
  return (
    <span className={`${tone} w-3 shrink-0 text-center text-sm`} title={description}>
      {glyph}
      <span className="sr-only">{description}</span>
    </span>
  )
}

/**
 * The par scale - the legend for every board on this page.
 *
 * Drawn rather than described, and drawn with the same track the rows use, so
 * the meters below are already familiar by the time they appear.
 */
function ParScale() {
  return (
    <div className="rounded-xl border border-border-subtle bg-surface p-4 shadow-card sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="u-eyebrow">The unit on this page</p>
        <p className="text-xs text-muted">
          Every board below is ordered on par units gained, and the form score beside each name
          is a percentile of that same figure.
        </p>
      </div>

      {/* Same track and same datum position as the row meters - a third of the
          way in, because the scale runs to 3.00. Drawing the legend on a
          different scale to the thing it explains would be worse than not
          drawing it. The 2px gaps either side of the datum are what keep the
          line readable where two fills meet it. */}
      <div className="relative mt-4">
        <div className="par-track h-2.5" style={{ ['--par-pos' as string]: 1 / 3 }}>
          <span
            className="par-fill"
            style={{ left: '6%', width: '26.1%', background: 'var(--color-negative)' }}
          />
          <span
            className="par-fill"
            style={{ left: '34.5%', width: '55%', background: 'var(--color-positive)' }}
          />
        </div>
        <div className="relative mt-2 h-8 font-mono text-[10px]">
          <span className="absolute left-0 text-negative-ink">▼ below par</span>
          <span
            className="tnum absolute -translate-x-1/2 text-center text-ink"
            style={{ left: '33.33%' }}
          >
            1.00
            <span className="block text-dim">an average appearance</span>
          </span>
          <span className="absolute right-0 text-positive-ink">above par ▲</span>
        </div>
      </div>

      <p className="mt-3 max-w-3xl text-xs leading-relaxed text-muted">
        A par unit is what one average appearance is worth, after every performance has been scaled
        by the strength of the side it came against. A player at{' '}
        <span className="tnum font-mono text-negative-ink">0.70x</span> is producing less than an
        average appearance even if their form is improving sharply - which is why the absolute
        figure sits beside the change on every row.
      </p>
    </div>
  )
}

function FormBoard({
  title,
  blurb,
  rows,
  loading,
  slug,
  tone,
}: {
  title: string
  blurb: string
  rows: FormLeaderRow[]
  loading: boolean
  slug: string
  tone: 'positive' | 'negative'
}) {
  return (
    <section className="flex flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface shadow-card">
      <header className="border-b border-border-subtle px-4 py-3">
        <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted">{blurb}</p>
      </header>

      {loading ? (
        <SkeletonRows rows={6} className="p-4" />
      ) : rows.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-muted">
          No players meet the evidence threshold in this scope.
        </p>
      ) : (
        <ul className="flex-1 divide-y divide-border-subtle">
          {rows.map((r) => {
            // Confidence below 0.6 is the product saying "thin sample". It is
            // rendered as a dotted rule rather than an amber figure: amber and
            // the red of a below-par delta cannot be separated (ΔE ~12 for
            // normal vision), and here they would sit in adjacent columns.
            const thin = r.confidence < 0.6
            // Worded by the API so it is never a percentage over 100 - a ratio
            // against the player's own baseline has no ceiling.
            const deltaText = r.delta_display ?? change(r.delta_percent)
            const confidenceNote = `Confidence ${Math.round(r.confidence * 100)}% - from ${
              r.recent_matches
            } recent and ${r.baseline_matches} earlier matches`

            return (
              <li key={r.player_identifier}>
                <Link
                  to={`/${slug}/players/${r.player_identifier}`}
                  className="flex items-center gap-2.5 px-4 py-2.5 transition-colors hover:bg-elevated"
                  title={r.explanation}
                >
                  <TrendGlyph trend={r.trend} />
                  <PlayerName
                    name={r.player_name}
                    country={r.country}
                    countryCode={r.country_code}
                    className="min-w-0 flex-1 text-sm text-ink"
                  />

                  {/* The absolute standard, drawn against the datum. A player
                      can post a huge percentage and still be below par, having
                      improved from very poor - the board is ordered on par
                      units gained, so this is what explains the order. */}
                  <ParMeter value={r.recent_mean} className="w-14 shrink-0" />
                  <span
                    className={`tnum w-11 shrink-0 text-right font-mono text-[11px] ${
                      (r.recent_mean ?? 0) >= 1 ? 'text-muted' : 'text-negative-ink'
                    }`}
                  >
                    {r.recent_mean !== null ? `${r.recent_mean.toFixed(2)}x` : '-'}
                  </span>

                  {/* The bounded 0-100 score, not the raw percentage. The
                      strip is ordered on par units gained, and the percentage
                      is not monotonic with that, so showing it here put a
                      larger figure below a smaller one. */}
                  <span
                    className={`tnum w-14 shrink-0 text-right text-sm font-semibold ${
                      tone === 'positive' ? 'text-positive-ink' : 'text-negative-ink'
                    }`}
                    title={`Form score ${score(r.form_score)}/100 in this scope · ${deltaText}`}
                  >
                    {thin ? (
                      <Uncertain reason={confidenceNote}>{score(r.form_score)}</Uncertain>
                    ) : (
                      score(r.form_score)
                    )}
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}

      <footer className="border-t border-border-subtle px-4 py-2">
        <p className="font-mono text-[9px] uppercase tracking-[0.1em] text-dim">
          Trend · Player · Par · Form score
        </p>
      </footer>
    </section>
  )
}

/**
 * The news strip.
 *
 * Four stories, no images bigger than a thumbnail, and every headline an
 * external link. Sized and placed so it cannot be mistaken for the product:
 * the boards above are what this site computes, and this is what other people
 * wrote about the same cricket.
 *
 * It renders nothing at all when there is no news rather than showing an empty
 * shell - an ingestion that has not run yet is not a thing the reader needs to
 * see on the landing page, and the news page itself says so properly.
 */
/**
 * The press strip: one lead story with a real image, three secondary rows.
 *
 * Section 8 forbids turning this page into a news feed, and the constraint is
 * respected in placement and cap rather than by keeping it ugly: it sits BELOW
 * every computed board, holds four stories, and every headline leaves the site.
 * What changed is that four 64px thumbnails in an undifferentiated list read as
 * filler, and a lead story with the space to be legible reads as a way out to
 * the sources - which is what it is.
 *
 * Deliberately still not a figure on this page: nothing here feeds any number
 * above it, and the header says so.
 */
function NewsStrip({
  articles,
  loading,
  slug,
}: {
  articles: NewsArticleSummary[]
  loading: boolean
  slug: string
}) {
  if (!loading && articles.length === 0) return null
  const [lead, ...rest] = articles

  return (
    <section>
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border-default pb-2">
        <h2 className="u-display text-title text-ink">In the cricket press</h2>
        <ActionLink to={`/${slug}/news`} weight="secondary">All news</ActionLink>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-dim">
        From four publishers' own feeds, linked out rather than reproduced. Nothing here feeds any
        figure on this page.
      </p>

      {loading ? (
        <div className="mt-4 rounded-xl border border-border-subtle bg-surface shadow-card">
          <SkeletonRows rows={4} className="p-4" />
        </div>
      ) : (
        <div className="mt-4 grid gap-3 lg:grid-cols-5">
          {lead && <LeadStory article={lead} />}
          {rest.length > 0 && (
            <ul className="divide-y divide-border-subtle overflow-hidden rounded-xl border border-border-subtle bg-surface shadow-card lg:col-span-2">
              {rest.map((a) => (
                <NewsRow key={a.article_id} article={a} />
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

/** The lead story, given the space to be read rather than scanned past. */
function LeadStory({ article }: { article: NewsArticleSummary }) {
  const image = article.image
  return (
    <a
      href={article.url}
      target="_blank"
      rel="noopener noreferrer external"
      className="group flex flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface shadow-card transition-colors hover:border-border-strong lg:col-span-3"
    >
      {image?.url ? (
        // `url` is the hero rendition, not `thumb_url`: this is the one place on
        // the page with room for it, and the list rows beside it still use the
        // small one. Lazy, because it sits well below the fold.
        <img
          src={image.url}
          alt={image.alt_text ?? ''}
          loading="lazy"
          className="aspect-[16/8] w-full bg-sunken object-cover"
        />
      ) : (
        <div className="aspect-[16/8] w-full bg-sunken" aria-hidden />
      )}
      <div className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <SourceChip publisher={article.publisher} />
          <span className="tnum text-[11px] text-dim">{timeAgo(article.published_at)}</span>
        </div>
        <h3 className="text-base font-semibold leading-snug text-ink group-hover:text-analytic-ink">
          {article.title}
        </h3>
        {article.standfirst && (
          <p className="line-clamp-2 text-sm leading-relaxed text-muted">{article.standfirst}</p>
        )}
        {/* A literal escape, not `&nearr;`: JSX resolves named entities through
            Babel's table, which has the right-arrow entity but not this one, so it
            rendered as text on the page. */}
        <span aria-hidden className="mt-auto pt-1 text-xs text-dim">
          Read at {article.publisher} <ArrowExternal className="ml-1" />
        </span>
      </div>
    </a>
  )
}

export function Home() {
  const { slug, apiGender } = useGender()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [inForm, setInForm] = useState<FormLeaderRow[]>([])
  const [rising, setRising] = useState<FormLeaderRow[]>([])
  const [losing, setLosing] = useState<FormLeaderRow[]>([])
  const [news, setNews] = useState<NewsArticleSummary[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([
      api.dashboard(apiGender),
      api.formLeaderboard(apiGender, { state: 'in_form', limit: 6 }),
      api.formLeaderboard(apiGender, { trend: 'rising', limit: 6 }),
      api.formLeaderboard(apiGender, { state: 'out_of_form', limit: 6 }),
    ])
      .then(([d, f, r, l]) => {
        if (cancelled) return
        setStats(d)
        setInForm(f.items)
        setRising(r.items)
        setLosing(l.items)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [apiGender])

  // Fetched on its own, not inside the Promise.all above. News comes from four
  // third parties and is the only thing on this page that can be stale or
  // absent through no fault of ours; folding it into the same promise would
  // let a publisher outage blank the form boards.
  useEffect(() => {
    let cancelled = false
    api
      .news({ gender: apiGender, limit: 4 })
      .then((page) => {
        if (!cancelled) setNews(page.items)
      })
      .catch(() => {
        if (!cancelled) setNews([])
      })
    return () => {
      cancelled = true
    }
  }, [apiGender])

  const kpis: [string, number | undefined][] = [
    ['Players', stats?.total_players],
    ['Matches', stats?.total_matches],
    ['Teams', stats?.total_teams],
    ['Competitions', stats?.by_competition.length],
    ['Seasons', stats?.matches_by_season.length],
  ]

  return (
    <div className="space-y-10">
      {/* ---- Hero ------------------------------------------------------ */}
      <section className="relative overflow-hidden rounded-2xl border border-border-subtle bg-surface px-5 py-8 shadow-card sm:px-8 sm:py-10">
        {/* A single, very quiet field wash. The one decorative element on the
            page, and it is a token gradient rather than a colour, so it
            re-themes with everything else. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.55]"
          style={{
            background:
              'radial-gradient(120% 90% at 88% -10%, var(--color-analytic-dim) 0%, transparent 62%)',
          }}
        />
        <div className="relative">
          <p className="u-eyebrow">
            {slug === 'men' ? "Men's" : "Women's"} cricket · derived from ball-by-ball
          </p>
          <h1 className="u-display mt-3 max-w-3xl text-display text-ink">
            Understand cricket beyond the scorecard.
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-relaxed text-muted">
            A decision-support platform, not a scores site. It answers who to pick and why, and it
            shows the workings for every figure - including the ones it cannot compute.
          </p>

          <div className="mt-6 flex flex-wrap items-center gap-2.5">
            <Link
              to={`/${slug}/${PRIMARY_ACTION.to}`}
              title={PRIMARY_ACTION.hint}
              className="inline-flex items-center gap-1.5 rounded-lg bg-analytic px-4 py-2.5 text-sm font-semibold text-white shadow-card transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-analytic"
            >
              {PRIMARY_ACTION.label}
              <ArrowRight />
            </Link>
            {SECONDARY_ACTIONS.map((a) => (
              <Link
                key={a.label}
                to={`/${slug}/${a.to}`}
                title={a.hint}
                className="rounded-lg border border-border-default bg-surface px-3.5 py-2.5 text-sm font-medium text-muted transition-colors hover:border-border-strong hover:bg-elevated hover:text-ink"
              >
                {a.label}
              </Link>
            ))}
          </div>

          {/* The dataset's scale, in the hero rather than buried below the
              boards. It is what makes the claim above checkable, and at the
              foot it was read by nobody. */}
          <dl className="mt-8 flex flex-wrap gap-x-8 gap-y-3 border-t border-border-subtle pt-5">
            {kpis.map(([label, value]) => (
              <div key={label}>
                <dd className="u-display tnum text-xl text-ink">
                  {value === undefined ? '-' : value.toLocaleString()}
                </dd>
                <dt className="u-eyebrow mt-0.5">{label}</dt>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* ---- What it answers ------------------------------------------- */}
      <section>
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border-default pb-2">
          <h2 className="u-display text-title text-ink">What you can ask it</h2>
          <p className="text-xs text-dim">Every surface states its own coverage and limits.</p>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {CAPABILITIES.map((c) => (
            <Link
              key={c.to}
              to={`/${slug}/${c.to}`}
              className="group flex flex-col gap-1.5 rounded-xl border border-border-subtle bg-surface p-4 shadow-card transition-colors hover:border-border-strong hover:bg-elevated focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-analytic"
            >
              <span className="u-eyebrow text-analytic-ink">{c.label}</span>
              <span className="text-[15px] font-semibold leading-snug text-ink">
                {c.question}
              </span>
              <span className="text-xs leading-relaxed text-muted">{c.detail}</span>
              {/* Part of the card, which is itself the link - so this is a
                  visual affordance rather than a second control. It lights up
                  with the card on hover, which is what tells a reader the whole
                  tile is pressable. */}
              <span
                aria-hidden
                className="mt-auto inline-flex items-center gap-1.5 pt-2 text-xs font-medium text-analytic-ink"
              >
                Open
                <ArrowRight className="transition-transform group-hover:translate-x-0.5" />
              </span>
            </Link>
          ))}
        </div>
      </section>

      {/* ---- Form boards ---------------------------------------------- */}
      <section>
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border-default pb-2">
          <h2 className="u-display text-title text-ink">Who has changed</h2>
          <p className="max-w-xl text-xs leading-relaxed text-dim">
            Form is measured against each player's own baseline, so these boards say{' '}
            <em>changed</em>, not <em>best</em>. For who is playing the best cricket outright, see
            the Performance Index.
          </p>
        </div>
        <div className="mt-4">
          <ParScale />
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-3">
        <FormBoard
          title="Players in Form"
          blurb="Furthest above their own recent baseline, weighted by how much cricket the verdict rests on."
          rows={inForm}
          loading={loading}
          slug={slug}
          tone="positive"
        />
        <FormBoard
          title="Rising"
          blurb="Improving within their current run - the trend is upward, not just the level."
          rows={rising}
          loading={loading}
          slug={slug}
          tone="positive"
        />
        <FormBoard
          title="Losing Form"
          blurb="Furthest below their own baseline. A drop here is relative to the player, not to their peers."
          rows={losing}
          loading={loading}
          slug={slug}
          tone="negative"
        />
      </div>

      {/* Section 8's "Latest ICC Movements". Sits below the computed boards
          because it is the one board here this project did NOT derive - it is
          ICC's published list, unmodified, and the separation between a derived
          figure and an official rating is the one Section 6 exists to protect.
          Fetched on its own so an ICC outage cannot blank the boards above. */}
      <IccMovementStrip gender={apiGender} slug={slug} />

      {/* The dataset's scale now sits in the hero, where it is actually read. */}

      <NewsStrip articles={news} loading={loading} slug={slug} />

      <Provenance>
        Form compares a player with their own preceding twelve months, within one competition.
        The figure beside each name is a{' '}
        <strong className="font-semibold text-muted">form score out of 100</strong>: a percentile of
        the par units gained against that baseline, weighted by how much cricket it rests on. The
        meter shows the absolute standard against par, which is what separates "improved to
        excellent" from "improved to still below average". A dotted rule means a thin sample.
      </Provenance>
    </div>
  )
}

/**
 * A compact "who moved in the ICC's list" strip (Section 8).
 *
 * Deliberately movement rather than a trend: only a handful of dated ICC lists
 * are held, because the daily sync began recently and the ICC republishes about
 * weekly. See analytics/icc_movement.py.
 *
 * The rank type is gendered, because the ICC publishes separate lists and a
 * women's scope must not show the men's board. It defaults to the batting list
 * for the format with the most published movement rather than to a fixed one.
 */
function IccMovementStrip({ gender, slug }: { gender: ApiGender; slug: string }) {
  const rankType = gender === 'female' ? 'odiw-batting' : 'odi-batting'
  const [data, setData] = useState<IccMovementReport | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .iccMovement(rankType)
      .then((d) => {
        if (!cancelled) setData(d)
      })
      .catch(() => {
        if (!cancelled) setData(null)
      })
    return () => {
      cancelled = true
    }
  }, [rankType])

  // Absent rather than empty: a strip with no movement in it is noise, and two
  // nearby weekly snapshots are often identical.
  if (!data || (data.risers.length === 0 && data.fallers.length === 0)) return null

  const rows = [...data.risers.slice(0, 3), ...data.fallers.slice(0, 3)]

  return (
    <section className="rounded-xl border border-border-subtle bg-surface shadow-card">
      <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border-subtle px-4 py-3">
        <h2 className="text-sm font-semibold tracking-tight text-ink">Latest ICC movements</h2>
        <ActionLink to={`/${slug}/icc-rankings`} weight="secondary">All ICC rankings</ActionLink>
      </header>
      <p className="px-4 pt-2 text-xs text-dim">
        ODI batting, {data.current_date} against {data.previous_date}. ICC's own positions,
        published rather than computed here.
      </p>
      <ul className="grid gap-x-5 px-4 py-2 sm:grid-cols-2">
        {rows.map((m) => {
          const up = m.places_gained > 0
          return (
            <li
              key={`${m.player_name}-${m.position}`}
              className="flex items-center gap-2 py-1.5 text-sm"
            >
              <span
                className={`w-3 shrink-0 text-center text-xs ${
                  up ? 'text-positive-ink' : 'text-negative-ink'
                }`}
                aria-hidden
              >
                {up ? '\u25b2' : '\u25bc'}
              </span>
              <span className="min-w-0 flex-1 truncate text-ink">
                {m.player_identifier ? (
                  <Link
                    to={`/${slug}/players/${m.player_identifier}`}
                    className="hover:text-analytic-ink"
                  >
                    {m.player_name}
                  </Link>
                ) : (
                  m.player_name
                )}
              </span>
              <span className="tnum shrink-0 text-xs text-muted">
                {m.previous_position} <ArrowRight className="mx-0.5" /> {m.position}
              </span>
              <span
                className={`tnum w-8 shrink-0 text-right text-xs font-semibold ${
                  up ? 'text-positive-ink' : 'text-negative-ink'
                }`}
              >
                {up ? '+' : ''}
                {m.places_gained}
              </span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
