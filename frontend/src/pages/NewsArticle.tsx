import { useEffect, useState } from 'react'
import { ArrowLeft, ArrowRight } from '../components/Icon'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { NewsArticleDetail, NewsEntity } from '../api/types'
import { useGender } from '../gender/useGender'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { SourceChip } from '../components/NewsItem'
import { timeAgo } from '../format'
import { Panel, Provenance } from '../components/ui'

/**
 * One article, and the thing that makes it worth having in this product at all:
 * the players, sides and competitions it is about, resolved to rows we hold.
 *
 * The body is shown only as far as the publisher's terms allow, and the page
 * says which rule applied rather than letting a capped read look like a whole
 * one. The canonical link is the primary action throughout - this is an index
 * entry, not a replacement for the masthead.
 */

/** How a link was established. Shown, not hidden - the strength differs a lot. */
const CONFIDENCE_NOTE: Record<string, string> = {
  tag_dob:
    "The publisher tagged this person with a date of birth, and it matches this player's. Effectively exact.",
  tag_name:
    'Resolved from a publisher tag through the surname-and-initial index, which refuses to answer when more than one player fits.',
  body_name: "The side's name appears in the text, and the text established which gender's side.",
  body_name_men_default:
    "The side's name appears in the text, but nothing established a gender, so the men's side was taken. A default, not a finding.",
}

const POLICY_NOTE: Record<string, string> = {
  full: 'This publisher permits the full text.',
  extract:
    'This publisher is indexed rather than republished, so only an opening extract is shown here.',
  metadata_only:
    'This publisher serves article pages only to browsers, so there is no body to show. The headline, standfirst and lead image come from the feed they publish for the purpose.',
}

/** True when the body's opening is the standfirst restated. */
function bodyOpensWith(body: string | null, standfirst: string): boolean {
  if (!body) return false
  const norm = (t: string) =>
    t.replace(/[\u2018\u2019\u201c\u201d]/g, "'").replace(/\s+/g, ' ').trim().toLowerCase()
  const lead = norm(standfirst).slice(0, 80)
  // 80 characters is long enough that a shared stock phrase cannot trip it and
  // short enough to survive the publisher truncating the standfirst mid-word.
  return lead.length >= 40 && norm(body).startsWith(lead)
}

function EntityLink({ entity, slug }: { entity: NewsEntity; slug: string }) {
  const note = CONFIDENCE_NOTE[entity.confidence] ?? entity.confidence
  const chip =
    'rounded-lg border border-border-default bg-surface px-2.5 py-1 text-xs text-ink transition-colors hover:border-border-strong hover:bg-elevated'

  if (entity.type === 'player' && entity.player_identifier) {
    return (
      <Link to={`/${slug}/players/${entity.player_identifier}`} className={chip} title={note}>
        {entity.player_name ?? entity.mention}
      </Link>
    )
  }
  if (entity.type === 'team' && entity.team_id) {
    return (
      <Link to={`/${slug}/teams/${entity.team_id}`} className={chip} title={note}>
        {entity.team_name ?? entity.mention}
      </Link>
    )
  }
  return (
    <span className={`${chip} cursor-default text-muted`} title={note}>
      {entity.competition_name ?? entity.mention}
    </span>
  )
}

export function NewsArticle() {
  const { slug } = useGender()
  const { articleId } = useParams<{ articleId: string }>()
  const [article, setArticle] = useState<NewsArticleDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!articleId) return
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .newsArticle(Number(articleId))
      .then((a) => {
        if (!cancelled) setArticle(a)
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
  }, [articleId])

  if (loading) return <LoadingSpinner />
  if (error) return <ErrorMessage message={error} />
  if (!article) return <ErrorMessage message="Article not found" />

  const players = article.entities.filter((e) => e.type === 'player')
  const teams = article.entities.filter((e) => e.type === 'team')
  const competitions = article.entities.filter((e) => e.type === 'competition')
  const hero = article.images.find((i) => i.role === 'hero') ?? article.images[0]
  const keywords = article.tags.filter((t) => t.kind === 'keyword' || t.kind === 'entity')

  // The ICC's og:description and JSON-LD description are the article's own
  // opening paragraphs, cut to length. Rendering both puts the same sentence
  // on screen twice, the first copy ending mid-clause. Suppress the standfirst
  // when the body already starts with it. Compared on a normalised prefix
  // because the two differ in whitespace and curly quotes.
  const showStandfirst =
    !!article.standfirst && !bodyOpensWith(article.body_text, article.standfirst)

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/${slug}/news`} className="text-xs text-muted hover:text-ink">
          <ArrowLeft className="mr-1" /> All news
        </Link>
      </div>

      <article>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <SourceChip publisher={article.publisher} />
          <span className="tnum text-[11px] text-dim">{timeAgo(article.published_at)}</span>
          {article.section && <span className="text-[11px] text-dim">· {article.section}</span>}
        </div>

        <h1 className="u-display mt-3 max-w-3xl text-title text-ink">{article.title}</h1>

        {showStandfirst && (
          <p className="mt-3 max-w-2xl text-base leading-relaxed text-muted">
            {article.standfirst}
          </p>
        )}

        <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-dim">
          {article.authors.length > 0 && <span>By {article.authors.join(', ')}</span>}
          {article.word_count > 0 && <span className="tnum">{article.word_count} words</span>}
          <a
            href={article.url}
            target="_blank"
            rel="noopener noreferrer external"
            className="font-medium text-analytic-ink hover:underline"
          >
            Read the full article at {article.publisher} <ArrowRight className="ml-1" />
          </a>
        </p>

        {hero && (
          <figure className="mt-5">
            <img
              src={hero.url}
              alt={hero.alt_text ?? ''}
              width={hero.width ?? undefined}
              height={hero.height ?? undefined}
              loading="lazy"
              onError={(e) => {
                e.currentTarget.style.display = 'none'
              }}
              className="w-full max-w-3xl rounded-xl bg-sunken object-cover"
            />
            {(hero.caption || hero.credit) && (
              <figcaption className="mt-2 max-w-3xl text-xs leading-relaxed text-dim">
                {hero.caption}
                {hero.caption && hero.credit && ' · '}
                {hero.credit}
              </figcaption>
            )}
          </figure>
        )}

        {article.body_text ? (
          <div className="mt-6 max-w-2xl space-y-3 text-[15px] leading-relaxed text-ink">
            {article.body_text
              .split('\n')
              .map((p) => p.trim())
              .filter(Boolean)
              .map((paragraph, i) => (
                <p key={i}>{paragraph}</p>
              ))}
          </div>
        ) : null}

        {/* Always rendered, for every policy, so a reader can tell a short
            article from a trimmed one and a licence boundary from a gap. */}
        <p className="mt-4 max-w-2xl rounded-lg border border-dashed border-border-default px-3 py-2 text-xs leading-relaxed text-muted">
          {article.body_truncated ? 'Extract shown. ' : ''}
          {POLICY_NOTE[article.content_policy]}{' '}
          <a
            href={article.url}
            target="_blank"
            rel="noopener noreferrer external"
            className="text-analytic-ink hover:underline"
          >
            Continue at {article.publisher}
          </a>
          {article.attribution && <span className="block mt-1 text-dim">{article.attribution}</span>}
        </p>
      </article>

      {(players.length > 0 || teams.length > 0 || competitions.length > 0) && (
        <Panel
          title="What this is about"
          blurb="Resolved to rows this product holds, so an article is a way into a player or a side rather than a dead end. Hover any chip for how the link was established."
        >
          <div className="space-y-3">
            {players.length > 0 && (
              <div>
                <p className="u-eyebrow mb-1.5">Players</p>
                <div className="flex flex-wrap gap-1.5">
                  {players.map((e) => (
                    <EntityLink key={`p-${e.mention}`} entity={e} slug={slug} />
                  ))}
                </div>
              </div>
            )}
            {teams.length > 0 && (
              <div>
                <p className="u-eyebrow mb-1.5">Sides</p>
                <div className="flex flex-wrap gap-1.5">
                  {teams.map((e) => (
                    <EntityLink key={`t-${e.mention}`} entity={e} slug={slug} />
                  ))}
                </div>
              </div>
            )}
            {competitions.length > 0 && (
              <div>
                <p className="u-eyebrow mb-1.5">Competitions</p>
                <div className="flex flex-wrap gap-1.5">
                  {competitions.map((e) => (
                    <EntityLink key={`c-${e.mention}`} entity={e} slug={slug} />
                  ))}
                </div>
              </div>
            )}
          </div>
        </Panel>
      )}

      {article.syndications.length > 0 && (
        <Panel
          title="Also published elsewhere"
          blurb="These carry a near-identical body. Kept rather than merged, because which mastheads ran a story is itself information."
          bodyClassName="divide-y divide-border-subtle"
        >
          {article.syndications.map((s) => (
            <a
              key={s.article_id}
              href={s.url}
              target="_blank"
              rel="noopener noreferrer external"
              className="block px-4 py-2.5 text-sm text-ink transition-colors hover:bg-elevated"
            >
              <SourceChip publisher={s.source} /> <span className="ml-1 text-muted">{s.url}</span>
            </a>
          ))}
        </Panel>
      )}

      {keywords.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="u-eyebrow mr-1">Publisher tags</span>
          {keywords.map((t) => (
            <Link
              key={`${t.kind}-${t.slug}`}
              to={`/${slug}/news?tag=${encodeURIComponent(t.slug)}`}
              className="rounded bg-elevated px-2 py-0.5 text-[11px] text-muted ring-1 ring-inset ring-border-subtle transition-colors hover:text-ink"
            >
              {t.value}
            </Link>
          ))}
        </div>
      )}

      <Provenance>
        Held as an index entry, not a copy: the canonical URL above is the article, and the text
        here is bounded by what the publisher permits. Entity links are drawn only from a
        publisher's own tags or from a side named in the text - a player's name is never matched
        out of prose, because "Root", "Khan" and "Ali" appear constantly and a wrong link would
        attach this article to the wrong person's profile with nothing on the page to reveal it.
        Nothing on this page feeds any figure this product computes.
      </Provenance>
    </div>
  )
}
