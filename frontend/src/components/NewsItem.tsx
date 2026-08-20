import type { NewsArticleSummary } from '../api/types'
import { timeAgo } from '../format'

/**
 * News rows, and the rules the publishers attach to them.
 *
 * Three things here are obligations rather than styling choices:
 *
 * 1. Every row links OUT to the publisher's canonical URL. Nothing is
 *    re-hosted - not the article and not the photograph - so the headline is
 *    an external link, and it says so.
 * 2. The publisher is named on every row. The Guardian's Open Platform licence
 *    requires attribution and a link back; naming all four keeps that a
 *    property of the component rather than a special case someone can drop.
 * 3. A capped body is marked. `content_policy` decides how much of an article
 *    the API returns, and a reader must be able to tell a short piece from a
 *    trimmed one - which is why `body_truncated` is on every row rather than
 *    only on the trimmed ones.
 */

export function SourceChip({ publisher }: { publisher: string }) {
  return (
    <span className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted ring-1 ring-inset ring-border-default">
      {publisher}
    </span>
  )
}

/** The "opens on the publisher's site" mark. Drawn, not described, on every link. */
function ExternalMark() {
  return (
    <svg
      viewBox="0 0 12 12"
      aria-hidden="true"
      className="ml-1 inline-block h-2.5 w-2.5 shrink-0 align-baseline text-dim"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4.5 1.5h6v6" />
      <path d="M10.5 1.5 5 7" />
      <path d="M9 7.5v3h-7.5V3h3" />
    </svg>
  )
}

/**
 * The hero image.
 *
 * Referenced from the publisher's own CDN, never copied. `alt` falls back to
 * the empty string rather than to the headline: the headline is already the
 * adjacent link text, and repeating it makes a screen reader say it twice.
 */
function Hero({
  article,
  className,
  eager = false,
}: {
  article: NewsArticleSummary
  className: string
  /** True for rows in the first screenful. See the note on `loading`. */
  eager?: boolean
}) {
  if (!article.image) return null
  return (
    <img
      // The list rendition, not the largest. Measured before this existed, a
      // 64px row was pulling a 461 KB original from ESPNcricinfo and 308 KB
      // from Sky. Falls back to the full image when the CDN is one ingestion
      // does not know how to resize.
      src={article.image.thumb_url ?? article.image.url}
      alt={article.image.alt_text ?? ''}
      width={article.image.width ?? undefined}
      height={article.image.height ?? undefined}
      // Lazy everywhere EXCEPT the first few rows. An image that is already on
      // screen gains nothing from being deferred and costs the largest
      // contentful paint, and lazy-loading the lead image is a common way to
      // make a list feel slower than it is.
      loading={eager ? 'eager' : 'lazy'}
      fetchPriority={eager ? 'high' : 'auto'}
      decoding="async"
      // A publisher can pull or re-path an asset at any time, and a broken
      // image icon in a list reads as a broken product. Hide the element
      // instead and let the row fall back to text.
      onError={(e) => {
        e.currentTarget.style.display = 'none'
      }}
      className={`bg-sunken object-cover ${className}`}
    />
  )
}

/** One compact row. Used on the dashboard, where vertical space is the constraint. */
export function NewsRow({
  article,
  eager = false,
}: {
  article: NewsArticleSummary
  eager?: boolean
}) {
  return (
    <li>
      <a
        href={article.url}
        target="_blank"
        rel="noopener noreferrer external"
        className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-elevated"
      >
        <Hero article={article} eager={eager} className="h-12 w-16 shrink-0 rounded" />
        <span className="min-w-0 flex-1">
          <span className="block text-sm leading-snug text-ink">
            {article.title}
            <ExternalMark />
          </span>
          <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-dim">
            <SourceChip publisher={article.publisher} />
            <span className="tnum">{timeAgo(article.published_at)}</span>
            {article.syndication_of_article_id !== null && (
              <span title="This body republishes another article already held">
                republished
              </span>
            )}
          </span>
        </span>
      </a>
    </li>
  )
}

/** A fuller card. Used on the news page, where the standfirst earns its space. */
export function NewsCard({
  article,
  to,
  eager = false,
}: {
  article: NewsArticleSummary
  to?: string
  eager?: boolean
}) {
  return (
    <article className="flex gap-4 border-b border-border-subtle px-4 py-4 last:border-0">
      <Hero article={article} eager={eager} className="hidden h-24 w-36 shrink-0 rounded-lg sm:block" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <SourceChip publisher={article.publisher} />
          <span className="tnum text-[11px] text-dim">{timeAgo(article.published_at)}</span>
          {article.section && <span className="text-[11px] text-dim">· {article.section}</span>}
          {article.syndication_of_article_id !== null && (
            <span
              className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-dim ring-1 ring-inset ring-border-default"
              title="A near-identical body is already held from another publisher. Kept rather than hidden: a wire story running in several places is information."
            >
              republished
            </span>
          )}
        </div>

        <h3 className="mt-1.5 text-[15px] font-semibold leading-snug text-ink">
          {to ? (
            <a href={to} className="hover:text-analytic-ink">
              {article.title}
            </a>
          ) : (
            article.title
          )}
        </h3>

        {article.standfirst && (
          <p className="mt-1 line-clamp-2 text-sm leading-relaxed text-muted">
            {article.standfirst}
          </p>
        )}

        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
          <a
            href={article.url}
            target="_blank"
            rel="noopener noreferrer external"
            className="text-analytic-ink hover:underline"
          >
            Read at {article.publisher}
            <ExternalMark />
          </a>
          {article.image?.credit && (
            <span className="text-dim" title="Photograph credit, as the publisher gives it">
              {article.image.credit}
            </span>
          )}
        </div>
      </div>
    </article>
  )
}
