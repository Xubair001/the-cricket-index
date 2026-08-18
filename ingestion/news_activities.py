"""Temporal activities for sports news ingestion.

Separate module from activities.py only because that file is already 1,000
lines of Cricsheet, ICC and Wikidata work; the pattern is identical and the
worker registers both the same way. Everything here is I/O plus writes, and
every pure function it calls lives in news_sources.py -- the same split
activities.py has with enrichment.py and icc_scorecard.py.

The pipeline the brief asks for maps onto activities like this:

    discover_news        Discovery
    fetch_news_batch     Fetch -> Parse -> Extract -> Validate -> Normalize
                         -> Deduplicate -> Persist
    link_news_entities   (post-pass, needs the article rows to exist)
    probe_news_images    Process Images
    news_retry_sweep     re-queues what failed, with backoff

Fetch through Persist are ONE activity rather than seven. That is a
deliberate departure from a literal reading of the pipeline, on the same
reasoning `ingest_match` is one activity rather than a child workflow per
step: they are a single unit of work over one in-memory document, and
splitting them would mean either carrying a whole article body through
workflow history seven times or refetching the page at every step. The
boundaries that DO matter -- a network call to a third party, a database
write, a long-running batch -- are activity boundaries, and every one of them
is separately retryable.
"""
import asyncio
import json
import os
import random
import re
import sqlite3
import struct
import time
from datetime import datetime, timedelta, timezone
from email.utils import formatdate, parsedate_to_datetime

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from db import get_connection
from enrichment import build_name_index, resolve_player
from shared import NewsBatchResult
import news_sources as ns

# Sent on every request. A real contact URL rather than a browser string: the
# whole point of the source selection above is that nothing here needs to
# pretend to be a browser, and a publisher who wants to rate-limit or block
# this pipeline should be able to identify it and do so.
USER_AGENT = os.environ.get(
    "NEWS_USER_AGENT",
    "TheCricketIndexBot/1.0 (+https://github.com/; cricket news indexer)",
)

# The Guardian Open Platform key. `test` is their published open key and is
# what this falls back to, so the source works out of the box; it is rate
# limited to 720/min and 50,000/day, which the limiter below stays well under.
GUARDIAN_API_KEY = os.environ.get("GUARDIAN_API_KEY", "test")

# Whether to spend a ranged GET measuring an image whose dimensions no source
# declared. Off by default: it is one extra request per image and the layout
# degrades gracefully without it. Never stores the bytes.
IMAGE_PROBE_ENABLED = os.environ.get("NEWS_IMAGE_PROBE", "0") == "1"

HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

# Consecutive failed discovery passes before a source is skipped outright.
# Set to 3 so a single bad deploy at the publisher's end does not stop us
# trying tomorrow, while a source that has genuinely moved or revoked access
# stops costing a fetch on every run.
CIRCUIT_BREAKER_THRESHOLD = 3
CIRCUIT_BREAKER_COOLDOWN = timedelta(hours=6)

# Retry ladder for a URL that failed to fetch or extract. Capped at 5 attempts:
# past that the failure is structural (the page has moved, or our extractor
# does not understand it) and a sixth identical request will not discover that.
RETRY_BACKOFF_HOURS = (0.25, 1, 6, 24, 72)
MAX_ATTEMPTS = len(RETRY_BACKOFF_HOURS)

MAX_RETRY_AFTER = 60.0


# --------------------------------------------------------------------------
# Politeness: one limiter per source, shared by every activity in the worker
# --------------------------------------------------------------------------

class _SourceLimiter:
    """Per-source minimum interval plus a concurrency cap.

    Two separate controls because they answer different questions. The
    semaphore bounds how many sockets we hold open to one publisher at once;
    the interval bounds how fast we ask, which is the thing a publisher's
    rate limiter actually measures. A semaphore alone would let N concurrent
    requests all fire in the same millisecond and then idle.

    Scope is the worker process. Two workers on the same task queue would each
    hold their own limiter and together exceed the floor, which is why the
    intervals are set an order of magnitude below what each source advertises
    rather than at the line. A cross-worker limiter would need shared state
    that this project's single-SQLite-file architecture has no good home for,
    and pretending otherwise would be worse than saying so.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._next_allowed: dict[str, float] = {}

    def _lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def semaphore(self, source: ns.NewsSource) -> asyncio.Semaphore:
        if source.key not in self._semaphores:
            self._semaphores[source.key] = asyncio.Semaphore(source.max_concurrency)
        return self._semaphores[source.key]

    async def wait(self, source: ns.NewsSource) -> None:
        async with self._lock(source.key):
            now = time.monotonic()
            due = self._next_allowed.get(source.key, 0.0)
            if due > now:
                await asyncio.sleep(due - now)
            # Jitter so that four sources released together by one workflow do
            # not stay in lockstep for the whole run.
            interval = source.min_interval_seconds * random.uniform(0.9, 1.2)
            self._next_allowed[source.key] = time.monotonic() + interval

    def penalise(self, source: ns.NewsSource, seconds: float) -> None:
        """Push the next allowed time out after a 429 or a 5xx."""
        self._next_allowed[source.key] = max(
            self._next_allowed.get(source.key, 0.0), time.monotonic() + seconds
        )


_LIMITER = _SourceLimiter()


async def _polite_get(
    client: httpx.AsyncClient,
    source: ns.NewsSource,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    attempts: int = 3,
) -> httpx.Response | None:
    """One GET, rate limited, with backoff on throttling and 5xx.

    Returns the response for any status the caller should act on (including
    304 and 404), and None once retries are exhausted. Retry-After is honoured
    up to MAX_RETRY_AFTER for exactly the reason `_wikidata_get` documents:
    past that cap, letting Temporal retry the activity later is a better use
    of the time than a blocked coroutine holding a start_to_close budget.
    """
    delay = 2.0
    for attempt in range(attempts):
        await _LIMITER.wait(source)
        async with _LIMITER.semaphore(source):
            try:
                resp = await client.get(url, params=params, headers=headers)
            except httpx.HTTPError as e:
                activity.logger.warning(f"{source.key}: {url} transport error {e!r}")
                if attempt == attempts - 1:
                    return None
                await asyncio.sleep(delay)
                delay *= 2
                continue

        if resp.status_code == 429 or resp.status_code >= 500:
            wait = float(resp.headers.get("retry-after") or delay)
            if wait > MAX_RETRY_AFTER:
                activity.logger.warning(
                    f"{source.key}: HTTP {resp.status_code} asks for {wait:.0f}s, "
                    f"above the {MAX_RETRY_AFTER:.0f}s cap; giving up so Temporal "
                    f"can retry after the throttle clears"
                )
                _LIMITER.penalise(source, MAX_RETRY_AFTER)
                return None
            _LIMITER.penalise(source, wait)
            activity.logger.info(
                f"{source.key}: HTTP {resp.status_code} on {url}, retrying in {wait:.0f}s "
                f"({attempt + 1}/{attempts})"
            )
            await asyncio.sleep(wait)
            delay *= 2
            continue
        return resp
    return None


# --------------------------------------------------------------------------
# Small database helpers
# --------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sync_publishers(conn: sqlite3.Connection) -> dict[str, int]:
    """Mirror the code registry into news_publishers and return key -> id.

    The registry is the source of truth; this table exists so articles can FK
    to a publisher entity and so the display obligations (attribution, content
    policy) travel with the data rather than only with the code that wrote it.
    """
    ids: dict[str, int] = {}
    for source in ns.SOURCES.values():
        conn.execute(
            """INSERT INTO news_publishers
                   (key, name, home_url, strategy, content_policy,
                    attribution, policy_note, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   name=excluded.name, home_url=excluded.home_url,
                   strategy=excluded.strategy,
                   content_policy=excluded.content_policy,
                   attribution=excluded.attribution,
                   policy_note=excluded.policy_note,
                   enabled=excluded.enabled""",
            (source.key, source.name, source.home_url, source.strategy,
             source.content_policy, source.attribution, source.policy_note,
             1 if source.enabled else 0),
        )
    for key, publisher_id in conn.execute(
        "SELECT key, publisher_id FROM news_publishers"
    ):
        ids[key] = publisher_id
    return ids


def _breaker_is_open(conn: sqlite3.Connection, source_key: str) -> bool:
    """True when this source has failed enough times, recently enough, to skip.

    Read from news_feed_state rather than from a counter held in memory, so
    that a source which is genuinely down stays skipped across workflow runs
    and worker restarts instead of costing a full round of failures every day.
    """
    row = conn.execute(
        """SELECT MAX(consecutive_failures), MAX(last_fetched_at)
           FROM news_feed_state WHERE source_key = ?""",
        (source_key,),
    ).fetchone()
    if not row or row[0] is None:
        return False
    failures, last_fetched = row
    if failures < CIRCUIT_BREAKER_THRESHOLD:
        return False
    if not last_fetched:
        return True
    try:
        when = datetime.fromisoformat(last_fetched)
    except ValueError:
        return True
    # Half-open after the cooldown: one attempt is allowed through, and it
    # either resets the counter or pushes the window out again.
    return datetime.now(timezone.utc) - when < CIRCUIT_BREAKER_COOLDOWN


def _feed_conditional_headers(conn: sqlite3.Connection, feed_url: str) -> dict:
    row = conn.execute(
        "SELECT etag, last_modified FROM news_feed_state WHERE feed_url = ?",
        (feed_url,),
    ).fetchone()
    headers = {}
    if row:
        if row[0]:
            headers["If-None-Match"] = row[0]
        if row[1]:
            headers["If-Modified-Since"] = row[1]
    return headers


def _record_feed_state(
    conn: sqlite3.Connection, feed_url: str, source_key: str,
    resp: httpx.Response | None, items: int,
) -> None:
    status = resp.status_code if resp is not None else 0
    ok = resp is not None and resp.status_code in (200, 304)
    conn.execute(
        """INSERT INTO news_feed_state
               (feed_url, source_key, etag, last_modified, last_fetched_at,
                last_status, consecutive_failures, items_last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(feed_url) DO UPDATE SET
               etag = COALESCE(excluded.etag, news_feed_state.etag),
               last_modified = COALESCE(excluded.last_modified,
                                        news_feed_state.last_modified),
               last_fetched_at = excluded.last_fetched_at,
               last_status = excluded.last_status,
               consecutive_failures = CASE WHEN ? THEN 0
                    ELSE news_feed_state.consecutive_failures + 1 END,
               items_last_seen = excluded.items_last_seen""",
        (
            feed_url, source_key,
            resp.headers.get("etag") if resp is not None else None,
            resp.headers.get("last-modified") if resp is not None else None,
            _now(), status, 0 if ok else 1, items, ok,
        ),
    )


def _queue(
    conn: sqlite3.Connection, source_key: str, url: str, fingerprint: str
) -> bool:
    """Record a discovered URL as pending. True when it is new work.

    The ledger row is written at DISCOVERY, before anything is fetched, which
    is what makes the pipeline resumable: a worker that dies mid-batch leaves
    the remaining URLs marked pending, and the next run picks them up from the
    database rather than from workflow history.
    """
    existing = conn.execute(
        """SELECT status, extractor_version, next_attempt_after, last_error
           FROM news_ingestions WHERE url_fingerprint = ?""",
        (fingerprint,),
    ).fetchone()

    if existing is not None:
        status, version, next_after, last_error = existing
        # Already done at the CURRENT extractor version: genuinely nothing to
        # do. At an older version it is re-queued, which is the news-side
        # equivalent of PARSER_VERSION forcing a Cricsheet re-parse.
        if status in ("stored", "unchanged") and version >= ns.EXTRACTOR_VERSION:
            return False
        if status == "skipped":
            # A 410 is the publisher saying the page is gone for good, so it
            # stays skipped whatever we do to the extractor.
            if "410" in (last_error or ""):
                return False
            # Everything else that was skipped was skipped by a rule in
            # news_sources.py - robots or article_path - and those rules
            # change. Discovery has ALREADY re-applied both before reaching
            # here, so a skipped row that gets this far is one the current
            # rules now admit. Without this, widening a scope pattern leaves
            # the URLs it was narrowed against skipped for ever: correcting
            # the ICC pattern from /news/ to include /media-releases/ and
            # /tournaments/ would have recovered nothing.
            if version >= ns.EXTRACTOR_VERSION:
                return False
        if status == "failed" and next_after and next_after > _now():
            return False
        conn.execute(
            "UPDATE news_ingestions SET status = 'pending', url = ? "
            "WHERE url_fingerprint = ?",
            (url, fingerprint),
        )
        return True

    conn.execute(
        """INSERT INTO news_ingestions
               (url_fingerprint, source_key, url, status, extractor_version,
                attempts, first_attempt_at)
           VALUES (?, ?, ?, 'pending', 0, 0, ?)""",
        (fingerprint, source_key, url, _now()),
    )
    return True


def _mark(
    conn: sqlite3.Connection, fingerprint: str, status: str, *,
    article_id: int | None = None, http_status: int | None = None,
    content_hash: str | None = None, error: str | None = None,
    problems: list[str] | None = None, etag: str | None = None,
    last_modified: str | None = None, bump_attempt: bool = True,
) -> None:
    """Close out one ledger row.

    `next_attempt_after` is only set for 'failed'. An 'invalid' row is NOT
    retried on a schedule: the page was served and parsed and simply was not
    an article, so refetching it in fifteen minutes will produce the same
    non-article. It becomes eligible again when EXTRACTOR_VERSION changes,
    which is the only event that could change the answer.
    """
    attempts_sql = "attempts + 1" if bump_attempt else "attempts"
    next_after = None
    if status == "failed":
        row = conn.execute(
            "SELECT attempts FROM news_ingestions WHERE url_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        attempt_index = min((row[0] if row else 0), MAX_ATTEMPTS - 1)
        if (row[0] if row else 0) < MAX_ATTEMPTS:
            next_after = (
                datetime.now(timezone.utc)
                + timedelta(hours=RETRY_BACKOFF_HOURS[attempt_index])
            ).isoformat(timespec="seconds")

    conn.execute(
        f"""UPDATE news_ingestions
            SET status = ?, article_id = COALESCE(?, article_id),
                http_status = COALESCE(?, http_status),
                content_hash = COALESCE(?, content_hash),
                etag = COALESCE(?, etag),
                last_modified = COALESCE(?, last_modified),
                last_error = ?, problems = ?,
                extractor_version = ?,
                attempts = {attempts_sql},
                last_attempt_at = ?, next_attempt_after = ?
            WHERE url_fingerprint = ?""",
        (status, article_id, http_status, content_hash, etag, last_modified,
         error, json.dumps(problems) if problems else None,
         ns.EXTRACTOR_VERSION, _now(), next_after, fingerprint),
    )


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

@activity.defn
async def discover_news(source_key: str, since: str = "") -> dict:
    """Find candidate articles for one source and queue them in the ledger.

    Returns the url_fingerprints that need work, which the workflow then feeds
    back in batches. Fingerprints rather than URLs: the fingerprint is the
    ledger's primary key, so a resumed generation reads the URL and every
    piece of retry state out of the row instead of trusting a value carried
    through workflow history.

    A source whose circuit breaker is open returns immediately and says so,
    rather than reporting a successful discovery that found nothing.
    """
    source = ns.SOURCES.get(source_key)
    if source is None:
        raise ApplicationError(f"unknown news source '{source_key}'", non_retryable=True)
    if not source.enabled:
        # Not an error. A disabled source is a policy decision recorded in the
        # registry (see bbcsport), and the run should say so plainly.
        return {"source": source_key, "enabled": False, "pending": [],
                "reason": source.policy_note, "seen": 0, "queued": 0}

    with get_connection() as conn:
        _sync_publishers(conn)
        if _breaker_is_open(conn, source_key):
            conn.commit()
            return {"source": source_key, "enabled": True, "pending": [],
                    "breaker_open": True, "seen": 0, "queued": 0,
                    "reason": f"{CIRCUIT_BREAKER_THRESHOLD} consecutive failures"}
        conn.commit()

    if source.strategy == "api":
        candidates, feed_results = await _discover_guardian(source, since)
    elif source.strategy == "sitemap":
        candidates, feed_results = await _discover_sitemap(source)
    else:
        candidates, feed_results = await _discover_rss(source)

    seen = queued = skipped = 0
    pending: list[str] = []
    cutoff = since or None

    with get_connection() as conn:
        for feed_url, resp, count in feed_results:
            _record_feed_state(conn, feed_url, source_key, resp, count)

        for candidate in candidates:
            seen += 1
            url = ns.canonical_url(candidate.url, source_key)
            if not url:
                continue
            # Two separate refusals, recorded separately. robots.txt is
            # enforced here rather than only documented (the ICC names eight
            # integrity-desk articles it does not want crawled); scope keeps
            # a publisher's own off-topic items out. Both land as 'skipped'
            # with a reason, never as 'failed', because neither is a failure
            # and mixing them in would bury real extraction breakage.
            refusal = None
            if not ns.is_discoverable(source_key, url):
                refusal = "robots.txt disallow"
            elif not ns.is_in_scope(source_key, url):
                refusal = "out of scope for this source"
            if refusal:
                fingerprint = ns.url_fingerprint(url, source_key)
                conn.execute(
                    """INSERT OR IGNORE INTO news_ingestions
                           (url_fingerprint, source_key, url, status,
                            extractor_version, attempts, first_attempt_at,
                            last_error)
                       VALUES (?, ?, ?, 'skipped', ?, 0, ?, ?)""",
                    (fingerprint, source_key, url, ns.EXTRACTOR_VERSION, _now(), refusal),
                )
                skipped += 1
                continue
            # An RSS window is whatever the publisher currently lists, so a
            # `since` cut is applied to the feed's own date where it gave one
            # rather than by refetching to find out.
            if cutoff and candidate.published_at and candidate.published_at[:10] < cutoff:
                continue

            fingerprint = ns.url_fingerprint(url, source_key)
            if _queue(conn, source_key, url, fingerprint):
                queued += 1
                pending.append(fingerprint)
            _CANDIDATE_CACHE[fingerprint] = candidate
        conn.commit()

    activity.logger.info(
        f"news discovery {source_key}: {seen} seen, {queued} queued, "
        f"{skipped} skipped (robots or out of scope)"
    )
    return {"source": source_key, "enabled": True, "breaker_open": False,
            "seen": seen, "queued": queued, "skipped": skipped,
            "pending": pending}


# Feed hints, held between the discovery activity and the fetch activity in
# the SAME worker process. Purely an optimisation for `feed_only` sources,
# whose feed item IS the record: with a cache hit ESPNcricinfo needs no
# further request at all. A miss is not a failure -- `fetch_news_batch`
# refetches the feed when it needs a candidate it does not hold, so the
# pipeline stays correct if the two activities land on different workers.
_CANDIDATE_CACHE: dict[str, ns.Candidate] = {}
_CANDIDATE_CACHE_MAX = 5000


def _trim_candidate_cache() -> None:
    if len(_CANDIDATE_CACHE) > _CANDIDATE_CACHE_MAX:
        for key in list(_CANDIDATE_CACHE)[: len(_CANDIDATE_CACHE) - _CANDIDATE_CACHE_MAX]:
            _CANDIDATE_CACHE.pop(key, None)


async def _discover_rss(source: ns.NewsSource):
    """Every configured feed for an RSS source, conditionally fetched."""
    candidates: list[ns.Candidate] = []
    results = []
    with get_connection() as conn:
        conditional = {url: _feed_conditional_headers(conn, url) for url in source.discovery}

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:
        for feed_url in source.discovery:
            resp = await _polite_get(
                client, source, feed_url, headers=conditional.get(feed_url) or None
            )
            if resp is None:
                results.append((feed_url, None, 0))
                continue
            if resp.status_code == 304:
                activity.logger.info(f"{source.key}: {feed_url} unchanged (304)")
                results.append((feed_url, resp, 0))
                continue
            if resp.status_code != 200:
                activity.logger.warning(
                    f"{source.key}: {feed_url} HTTP {resp.status_code}"
                )
                results.append((feed_url, resp, 0))
                continue
            items = ns.parse_rss(resp.text, source.key)
            candidates.extend(items)
            results.append((feed_url, resp, len(items)))
    return _dedupe_candidates(candidates), results


async def _discover_sitemap(source: ns.NewsSource):
    """Google News sitemap, following one level of <sitemapindex>.

    One level only, and the top-level article sitemap is fetched first. The
    ICC's index fans out to 37 per-tournament sitemaps that overlap heavily
    with it; pulling all of them on every daily run would be a large fetch for
    a handful of extra URLs. The index is still followed because that is where
    an article outside the newest 100 lives, and `since` bounds what it costs.
    """
    candidates: list[ns.Candidate] = []
    results = []
    with get_connection() as conn:
        conditional = {url: _feed_conditional_headers(conn, url) for url in source.discovery}

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:
        queue = list(source.discovery)
        seen_feeds: set[str] = set()
        children_followed = 0
        while queue:
            feed_url = queue.pop(0)
            if feed_url in seen_feeds:
                continue
            seen_feeds.add(feed_url)

            resp = await _polite_get(
                client, source, feed_url, headers=conditional.get(feed_url) or None
            )
            if resp is None or resp.status_code == 304:
                results.append((feed_url, resp, 0))
                continue
            if resp.status_code != 200:
                results.append((feed_url, resp, 0))
                continue
            items, children = ns.parse_sitemap(resp.text, source.key)
            candidates.extend(items)
            results.append((feed_url, resp, len(items)))
            for child in children:
                if children_followed >= MAX_CHILD_SITEMAPS:
                    break
                if child not in seen_feeds:
                    queue.append(child)
                    children_followed += 1
    return _dedupe_candidates(candidates), results


# How many child sitemaps one discovery pass will follow. Bounded so a
# publisher restructuring their index cannot turn one run into a full-site
# crawl. The cap is LOGGED when it bites, because a silent truncation reads
# as "covered everything" when it did not.
MAX_CHILD_SITEMAPS = 12


async def _discover_guardian(source: ns.NewsSource, since: str):
    """Paginate the Guardian search endpoint, newest first.

    `use-date=last-modified` rather than published: an article corrected after
    publication needs re-reading, and ordering by publication date would never
    surface it again. `order-by=newest` with that use-date gives a genuine
    incremental cursor.
    """
    candidates: list[ns.Candidate] = []
    results = []
    endpoint = source.discovery[0]
    from_date = since or (
        datetime.now(timezone.utc) - timedelta(days=GUARDIAN_LOOKBACK_DAYS)
    ).date().isoformat()

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:
        page = 1
        while page <= GUARDIAN_MAX_PAGES:
            resp = await _polite_get(
                client, source, endpoint,
                params={
                    "tag": "sport/cricket",
                    "order-by": "newest",
                    "use-date": "last-modified",
                    "from-date": from_date,
                    "page": page,
                    "page-size": ns.GUARDIAN_PAGE_SIZE,
                    "show-fields": ns.GUARDIAN_SHOW_FIELDS,
                    "show-tags": ns.GUARDIAN_SHOW_TAGS,
                    "show-elements": ns.GUARDIAN_SHOW_ELEMENTS,
                    "api-key": GUARDIAN_API_KEY,
                },
            )
            if resp is None or resp.status_code != 200:
                results.append((f"{endpoint}#page={page}", resp, 0))
                break
            payload = resp.json().get("response") or {}
            if payload.get("status") != "ok":
                activity.logger.warning(f"guardian: API status {payload.get('status')}")
                results.append((f"{endpoint}#page={page}", resp, 0))
                break
            page_results = payload.get("results") or []
            for item in page_results:
                candidate = ns.Candidate(
                    source_key="guardian",
                    url=item.get("webUrl") or "",
                    source_article_id=item.get("id"),
                    title=item.get("webTitle"),
                    published_at=ns.to_iso8601(item.get("webPublicationDate")),
                    section=item.get("sectionName"),
                    # The whole article is already in hand, so it travels with
                    # the candidate and the fetch step makes NO second request.
                    # This is the payoff for choosing an API over HTML.
                    raw=item,
                )
                candidates.append(candidate)
            results.append((f"{endpoint}#page={page}", resp, len(page_results)))
            if page >= (payload.get("pages") or 1) or not page_results:
                break
            page += 1
        else:
            activity.logger.info(
                f"guardian: stopped at the {GUARDIAN_MAX_PAGES}-page cap; "
                f"older articles were NOT discovered this run"
            )
    return _dedupe_candidates(candidates), results


# 30 days back and 20 pages of 50 is 1,000 articles per run, comfortably more
# than the Guardian publishes about cricket in a month. A backfill passes an
# explicit `since` and accepts the extra pages.
GUARDIAN_LOOKBACK_DAYS = 30
GUARDIAN_MAX_PAGES = 20


def _dedupe_candidates(candidates: list[ns.Candidate]) -> list[ns.Candidate]:
    """Collapse the same article appearing in several feeds of one source.

    ESPNcricinfo's per-team feeds overlap heavily with the global feed: one
    India-Sri Lanka story is in feeds 0, 6 and 8. Keyed on the canonical URL
    so the overlap costs nothing rather than three fetches.
    """
    out: dict[str, ns.Candidate] = {}
    for candidate in candidates:
        key = ns.canonical_url(candidate.url, candidate.source_key)
        if not key:
            continue
        existing = out.get(key)
        # Keep the richest version: a per-team feed sometimes carries a
        # media:content the global feed omits.
        if existing is None or (candidate.image_url and not existing.image_url):
            out[key] = candidate
    return list(out.values())


# --------------------------------------------------------------------------
# Persist
# --------------------------------------------------------------------------

def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "-"


# How wide a window to search for a syndicated twin. A wire story is
# republished within hours, not weeks, and comparing against every article
# ever stored would be O(n) per insert for a vanishing extra hit rate.
SYNDICATION_WINDOW_DAYS = 3


def _find_syndication_source(
    conn: sqlite3.Connection, article: ns.ExtractedArticle, simhash: int
) -> int | None:
    """The earliest article whose body is the same text as this one.

    Restricted to a different publisher on purpose: two articles from one
    masthead that hash alike are a live blog being re-saved or a running
    update, which is the same article changing rather than a syndication, and
    that case is already handled by content_hash on the same row.
    """
    if not simhash or not article.published_at:
        return None
    try:
        centre = datetime.fromisoformat(article.published_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    low = (centre - timedelta(days=SYNDICATION_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    high = (centre + timedelta(days=SYNDICATION_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    best_id, best_distance = None, ns.SYNDICATION_MAX_DISTANCE + 1
    for article_id, other_hash, _published in conn.execute(
        """SELECT article_id, text_simhash, published_at
           FROM news_articles
           WHERE text_simhash IS NOT NULL
             AND source_key != ?
             AND published_at BETWEEN ? AND ?
             AND syndication_of_article_id IS NULL
           ORDER BY published_at""",
        (article.source_key, low, high),
    ):
        try:
            distance = ns.syndication_distance(simhash, int(other_hash, 16))
        except (TypeError, ValueError):
            continue
        if distance < best_distance:
            best_id, best_distance = article_id, distance
    return best_id if best_distance <= ns.SYNDICATION_MAX_DISTANCE else None


def _persist(
    conn: sqlite3.Connection, publisher_id: int, article: ns.ExtractedArticle,
    content_hash: str,
) -> tuple[int, bool]:
    """Write one validated article. Returns (article_id, changed).

    Upsert on url_fingerprint. The row is REPLACED rather than versioned
    because an article that is corrected is still one article, and
    `updated_at` already records that it moved. `first_seen_at` is preserved
    across updates so the archive keeps when we first saw a story, which is
    not the same fact as when the publisher says they published it.
    """
    fingerprint = ns.url_fingerprint(article.canonical_url, article.source_key)
    simhash = ns.simhash(article.body_text or "")
    now = _now()

    existing = conn.execute(
        "SELECT article_id, content_hash FROM news_articles WHERE url_fingerprint = ?",
        (fingerprint,),
    ).fetchone()

    if existing is None and article.source_article_id:
        # The article MOVED: same publisher, same article id, different URL.
        # Publishers rewrite slugs, and Sky re-files pieces under a different
        # section id. Without this the INSERT satisfies ON CONFLICT
        # (url_fingerprint) - there is no row at the new fingerprint - and
        # then violates UNIQUE (publisher_id, source_article_id), which
        # surfaces as an IntegrityError and a 'failed' row for an article
        # that is perfectly fine. Repoint the existing row instead, which is
        # what "the article moved" actually means.
        moved = conn.execute(
            """SELECT article_id, url_fingerprint FROM news_articles
               WHERE publisher_id = ? AND source_article_id = ?""",
            (publisher_id, article.source_article_id),
        ).fetchone()
        if moved:
            activity.logger.info(
                f"{article.source_key}: article {article.source_article_id} moved to "
                f"{article.canonical_url}"
            )
            conn.execute(
                "UPDATE news_articles SET url_fingerprint = ?, canonical_url = ? "
                "WHERE article_id = ?",
                (fingerprint, article.canonical_url, moved[0]),
            )
            existing = conn.execute(
                "SELECT article_id, content_hash FROM news_articles "
                "WHERE url_fingerprint = ?",
                (fingerprint,),
            ).fetchone()

    if existing and existing[1] == content_hash:
        conn.execute(
            "UPDATE news_articles SET last_seen_at = ? WHERE article_id = ?",
            (now, existing[0]),
        )
        return existing[0], False

    syndication_of = None
    if existing is None:
        syndication_of = _find_syndication_source(conn, article, simhash)

    values = {
        "publisher_id": publisher_id,
        "source_key": article.source_key,
        "source_article_id": article.source_article_id,
        "canonical_url": article.canonical_url,
        "url_fingerprint": fingerprint,
        "discovered_url": article.discovered_url,
        "title": article.title or "",
        "standfirst": article.standfirst,
        "body_html": article.body_html,
        "body_text": article.body_text,
        "word_count": article.word_count,
        "declared_word_count": article.declared_word_count,
        "published_at": article.published_at,
        "updated_at": article.updated_at,
        "section": article.section,
        "language": article.language,
        "sport": "cricket",
        "content_hash": content_hash,
        "text_simhash": f"{simhash:016x}" if simhash else None,
        "syndication_of_article_id": syndication_of,
        "first_seen_at": now,
        "last_seen_at": now,
    }
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    updates = ", ".join(
        f"{c}=excluded.{c}" for c in values
        if c not in ("url_fingerprint", "first_seen_at")
    )
    conn.execute(
        f"""INSERT INTO news_articles ({columns}) VALUES ({placeholders})
            ON CONFLICT(url_fingerprint) DO UPDATE SET {updates}""",
        list(values.values()),
    )
    article_id = conn.execute(
        "SELECT article_id FROM news_articles WHERE url_fingerprint = ?", (fingerprint,)
    ).fetchone()[0]

    schema_type = article.json_ld.get("@type") if isinstance(article.json_ld, dict) else None
    conn.execute(
        """INSERT INTO news_article_metadata
               (article_id, meta_title, meta_description, og_json,
                twitter_json, json_ld, schema_type)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(article_id) DO UPDATE SET
               meta_title=excluded.meta_title,
               meta_description=excluded.meta_description,
               og_json=excluded.og_json, twitter_json=excluded.twitter_json,
               json_ld=excluded.json_ld, schema_type=excluded.schema_type""",
        (article_id, article.meta_title, article.meta_description,
         json.dumps(article.open_graph, ensure_ascii=False) if article.open_graph else None,
         json.dumps(article.twitter, ensure_ascii=False) if article.twitter else None,
         json.dumps(article.json_ld, ensure_ascii=False)[:200_000] if article.json_ld else None,
         schema_type if isinstance(schema_type, str) else None),
    )

    # Satellites are rewritten wholesale rather than diffed: a re-extraction
    # that drops a tag should drop it here too, and an article has at most a
    # handful of each.
    conn.execute("DELETE FROM news_article_authors WHERE article_id = ?", (article_id,))
    for position, name in enumerate(article.authors):
        conn.execute(
            "INSERT OR IGNORE INTO news_authors (publisher_id, name) VALUES (?, ?)",
            (publisher_id, name),
        )
        author_id = conn.execute(
            "SELECT author_id FROM news_authors WHERE publisher_id = ? AND name = ?",
            (publisher_id, name),
        ).fetchone()[0]
        conn.execute(
            """INSERT OR IGNORE INTO news_article_authors
                   (article_id, author_id, position) VALUES (?, ?, ?)""",
            (article_id, author_id, position),
        )

    conn.execute("DELETE FROM news_article_tags WHERE article_id = ?", (article_id,))
    for kind, value in article.tags:
        slug = _slug(value)
        conn.execute(
            "INSERT OR IGNORE INTO news_tags (kind, value, slug) VALUES (?, ?, ?)",
            (kind, value, slug),
        )
        tag_id = conn.execute(
            "SELECT tag_id FROM news_tags WHERE kind = ? AND slug = ?", (kind, slug)
        ).fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO news_article_tags (article_id, tag_id) VALUES (?, ?)",
            (article_id, tag_id),
        )

    conn.execute("DELETE FROM news_article_images WHERE article_id = ?", (article_id,))
    for position, image in enumerate(article.images):
        if not image.url:
            continue
        fingerprint_i = image.fingerprint or ns.image_fingerprint(image.url)
        conn.execute(
            """INSERT INTO news_images
                   (fingerprint, provider, cdn_url, origin_url, width, height, mime_type)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(fingerprint) DO UPDATE SET
                   -- Keep the LARGEST rendition seen, never merely the latest.
                   -- One asset arrives more than once per article: the
                   -- Guardian ships the same mediaId as both the main element
                   -- (widths 140/500/1000) and the thumbnail element (500),
                   -- so a plain "last write wins" replaced the 1000px hero
                   -- with the 500px thumbnail and cost every article its full
                   -- size image. Measured: every stored hero came out 500x400
                   -- when a 1000px rendition existed.
                   cdn_url = CASE
                       WHEN news_images.width IS NULL
                            OR COALESCE(excluded.width, 0) > news_images.width
                       THEN excluded.cdn_url ELSE news_images.cdn_url END,
                   origin_url = CASE
                       WHEN news_images.width IS NULL
                            OR COALESCE(excluded.width, 0) > news_images.width
                       THEN COALESCE(excluded.origin_url, news_images.origin_url)
                       ELSE news_images.origin_url END,
                   height = CASE
                       WHEN news_images.width IS NULL
                            OR COALESCE(excluded.width, 0) > news_images.width
                       THEN COALESCE(excluded.height, news_images.height)
                       ELSE news_images.height END,
                   -- width last: the three CASEs above read its OLD value, and
                   -- SQLite evaluates a SET list against the pre-update row,
                   -- but ordering it last keeps that independent of that rule.
                   width = CASE
                       WHEN news_images.width IS NULL
                            OR COALESCE(excluded.width, 0) > news_images.width
                       THEN COALESCE(excluded.width, news_images.width)
                       ELSE news_images.width END,
                   mime_type = COALESCE(excluded.mime_type, news_images.mime_type)""",
            (fingerprint_i, image.provider, image.url, image.origin_url,
             image.width, image.height, image.mime_type),
        )
        image_id = conn.execute(
            "SELECT image_id FROM news_images WHERE fingerprint = ?", (fingerprint_i,)
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO news_article_images
                   (article_id, image_id, role, position, alt_text, caption,
                    credit, image_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(article_id, image_id, role) DO UPDATE SET
                   position=excluded.position, alt_text=excluded.alt_text,
                   caption=excluded.caption, credit=excluded.credit,
                   image_type=excluded.image_type""",
            (article_id, image_id, image.role, position, image.alt_text,
             image.caption, image.credit, image.image_type),
        )

    return article_id, True


# --------------------------------------------------------------------------
# Fetch -> Parse -> Extract -> Validate -> Normalize -> Deduplicate -> Persist
# --------------------------------------------------------------------------

@activity.defn
async def fetch_news_batch(source_key: str, fingerprints: list[str]) -> dict:
    """Take one batch of queued URLs all the way to stored rows.

    Heartbeats after every item, carrying the index. A worker that dies
    mid-batch is therefore detected within the heartbeat timeout rather than
    at start_to_close, and the ledger rows it had not reached are still
    'pending', so the retry re-does only the tail.

    Nothing here writes an article row unless `validate` is clean. A page that
    parsed but was not an article is recorded as 'invalid' with its reasons,
    which is the specific thing that keeps a failed or partial scrape from
    being counted as successfully processed.
    """
    source = ns.SOURCES.get(source_key)
    if source is None:
        raise ApplicationError(f"unknown news source '{source_key}'", non_retryable=True)

    result = NewsBatchResult()
    # ONE connection for the whole batch, committed after each article rather
    # than at the end. Per-article commit is what keeps the batch resumable -
    # a worker that dies at item 30 keeps the first 29 - and one connection
    # rather than four per article avoids re-running the WAL and foreign-key
    # pragmas 2,000 times over a 500-article run.
    conn = get_connection()
    try:
        publishers = _sync_publishers(conn)
        rows = {
            row[0]: row
            for row in conn.execute(
                f"""SELECT url_fingerprint, url, etag, last_modified, content_hash
                    FROM news_ingestions
                    WHERE url_fingerprint IN ({",".join("?" * len(fingerprints))})""",
                fingerprints,
            )
        } if fingerprints else {}
        conn.commit()
        publisher_id = publishers[source_key]

        # A `feed_only` source needs its feed content, and the discovery
        # activity may have run on another worker. Refetch once for the whole
        # batch rather than per item.
        missing = [f for f in fingerprints if f not in _CANDIDATE_CACHE]
        if missing and source.strategy in ("feed_only", "rss"):
            await _refill_candidate_cache(source)

        async with httpx.AsyncClient(
            follow_redirects=True, timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            for index, fingerprint in enumerate(fingerprints):
                activity.heartbeat(index)
                row = rows.get(fingerprint)
                if row is None:
                    result.skipped += 1
                    continue
                _, url, etag, last_modified, prior_hash = row
                try:
                    outcome = await _process_one(
                        conn, client, source, publisher_id, fingerprint, url,
                        etag, last_modified, prior_hash,
                    )
                except Exception as e:  # noqa: BLE001 - one bad article must not sink the batch
                    activity.logger.warning(f"{source_key}: {url} failed: {e!r}")
                    # Roll back whatever half-written state the failure left
                    # before recording it, or the error row rides along with
                    # a partial article write.
                    conn.rollback()
                    _mark(conn, fingerprint, "failed", error=f"{type(e).__name__}: {e}")
                    conn.commit()
                    outcome = "failed"
                setattr(result, outcome, getattr(result, outcome) + 1)
    finally:
        conn.close()

    _trim_candidate_cache()
    activity.logger.info(
        f"news fetch {source_key}: {result.stored} stored, {result.unchanged} unchanged, "
        f"{result.invalid} invalid, {result.failed} failed, {result.skipped} skipped"
    )
    return {
        "source": source_key, "stored": result.stored, "unchanged": result.unchanged,
        "invalid": result.invalid, "failed": result.failed, "skipped": result.skipped,
    }


async def _refill_candidate_cache(source: ns.NewsSource) -> None:
    """Re-read a source's feeds so `feed_only` items can be extracted.

    Bypasses the conditional-request state deliberately: a 304 here would
    leave the cache empty and every item in the batch unprocessable, which is
    the opposite of what the caller needs.
    """
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:
        for feed_url in source.discovery:
            resp = await _polite_get(client, source, feed_url)
            if resp is None or resp.status_code != 200:
                continue
            for candidate in ns.parse_rss(resp.text, source.key):
                key = ns.url_fingerprint(candidate.url, source.key)
                _CANDIDATE_CACHE.setdefault(key, candidate)


async def _process_one(
    conn: sqlite3.Connection, client: httpx.AsyncClient, source: ns.NewsSource,
    publisher_id: int, fingerprint: str, url: str, etag: str | None,
    last_modified: str | None, prior_hash: str | None,
) -> str:
    """One URL, end to end. Returns the ledger status it was marked with.

    Takes the batch's connection rather than opening its own, and commits at
    every exit, so each article is durable on its own while the batch pays for
    one connection instead of four per item.
    """
    candidate = _CANDIDATE_CACHE.get(fingerprint) or ns.Candidate(
        source_key=source.key, url=url
    )
    http_status = None
    new_etag = new_last_modified = None

    def close(status: str, **kw) -> str:
        _mark(conn, fingerprint, status, **kw)
        conn.commit()
        return status

    # --- Fetch + Parse + Extract ------------------------------------------
    if source.strategy == "api":
        if not candidate.raw:
            # Discovery already had the whole article; without it there is
            # nothing to re-derive, so re-queue rather than guess.
            return close("failed", error="guardian payload not in cache; re-discover")
        article = ns.extract_from_guardian(candidate.raw)

    elif source.strategy == "feed_only":
        if candidate.title is None:
            return close("failed", error="feed item no longer listed")
        article = ns.extract_from_feed_item(candidate)

    else:
        headers = {}
        # Conditional request. Costs one 304 and no body when the publisher
        # has not touched the article since we last read it, which on a
        # three-hourly run is almost every article in the window.
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        resp = await _polite_get(client, source, url, headers=headers or None)
        if resp is None:
            return close("failed", error="no response after retries")

        http_status = resp.status_code
        new_etag = resp.headers.get("etag")
        new_last_modified = resp.headers.get("last-modified")

        if resp.status_code == 304:
            return close("unchanged", http_status=304, bump_attempt=False)
        if resp.status_code in (404, 410):
            # Gone for good. Marked 'skipped' rather than 'failed' so the
            # retry sweep stops asking; a 410 is the publisher's answer.
            return close("skipped", http_status=resp.status_code,
                         error=f"HTTP {resp.status_code}")
        if resp.status_code != 200:
            return close("failed", http_status=resp.status_code,
                         error=f"HTTP {resp.status_code}")
        article = ns.extract_from_html(resp.text, candidate)

    # --- Validate ---------------------------------------------------------
    problems = ns.validate(article)
    if problems:
        activity.logger.info(f"{source.key}: {url} invalid: {'; '.join(problems)}")
        return close("invalid", http_status=http_status, problems=problems,
                     etag=new_etag, last_modified=new_last_modified)

    # --- Normalize + fingerprint -----------------------------------------
    payload = {
        "canonical_url": article.canonical_url,
        "source_article_id": article.source_article_id,
        "title": article.title,
        "standfirst": article.standfirst,
        "body_text": article.body_text,
        "published_at": article.published_at,
        "updated_at": article.updated_at,
        "authors": sorted(article.authors),
        "tags": sorted(article.tags),
        "images": sorted(
            (i.url, i.role, i.caption or "", i.credit or "") for i in article.images
        ),
    }
    hashed = ns.content_hash(payload)
    canonical_fingerprint = ns.url_fingerprint(article.canonical_url, source.key)

    # --- Deduplicate ------------------------------------------------------
    # Two levels. The cheap one: nothing about this article changed since the
    # last run, so skip every write. The structural one lives in the schema as
    # UNIQUE(url_fingerprint) and UNIQUE(publisher_id, source_article_id), and
    # `_persist` upserts onto them.
    if prior_hash == hashed:
        row = conn.execute(
            "SELECT article_id FROM news_articles WHERE url_fingerprint = ?",
            (canonical_fingerprint,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE news_articles SET last_seen_at = ? WHERE article_id = ?",
                (_now(), row[0]),
            )
            return close("unchanged", article_id=row[0], http_status=http_status,
                         bump_attempt=False)

    # --- Persist ----------------------------------------------------------
    article_id, _changed = _persist(conn, publisher_id, article, hashed)
    _mark(conn, fingerprint, "stored", article_id=article_id,
          http_status=http_status, content_hash=hashed,
          etag=new_etag, last_modified=new_last_modified)
    # The canonical URL may differ from the URL we arrived on (Sky), which
    # would otherwise leave a second pending ledger row pointing at the same
    # article forever. Close it out against the same article.
    if canonical_fingerprint != fingerprint:
        conn.execute(
            """INSERT OR IGNORE INTO news_ingestions
                   (url_fingerprint, source_key, url, article_id, status,
                    extractor_version, content_hash, attempts, first_attempt_at,
                    last_attempt_at)
               VALUES (?, ?, ?, ?, 'stored', ?, ?, 1, ?, ?)""",
            (canonical_fingerprint, source.key, article.canonical_url,
             article_id, ns.EXTRACTOR_VERSION, hashed, _now(), _now()),
        )
    conn.commit()
    return "stored"


# --------------------------------------------------------------------------
# Entity linking
# --------------------------------------------------------------------------
#
# Runs as a separate activity after persistence rather than inside the parse,
# because it reads the whole `players` and `teams` tables and doing that once
# per batch is the difference between one index build and one per article.
#
# The resolution rules are the ones this project already uses for ICC rankings
# and ICC scorecards, reused rather than reimplemented: `build_name_index` and
# `resolve_player` from enrichment.py, which refuse to answer when more than
# one player fits. An article that mentions a player we cannot identify simply
# gets no row, exactly as an unmatched ranking entry stays unlinked.

@activity.defn
async def link_news_entities(limit: int = 500) -> dict:
    """Link stored articles to players, teams and competitions.

    Three routes, most precise first:

      tag_dob    The ICC tags people as "Matt Renshaw 03/28/1996". Matching
                 that date against players.date_of_birth is effectively exact
                 and needs no name disambiguation at all. This is the single
                 most valuable thing the reverse-engineering turned up.
      tag_name   A publisher entity or keyword tag resolved through the
                 (surname, initial) index.
      body_name  A team or competition name found in the title or body.

    Player names are NOT scanned for in body text. "Root", "Khan" and "Ali"
    appear in prose constantly, the index is built for scorecard-form names,
    and a wrong link would attach an article to the wrong person's profile
    with nothing on the page to reveal it. Tags are the publisher's own
    assertion about who the article is about, which is a different quality of
    evidence from a substring match.
    """
    linked = {"tag_dob": 0, "tag_name": 0, "body_name": 0}
    considered = 0

    with get_connection() as conn:
        players = list(conn.execute("SELECT identifier, name, gender FROM players"))
        index = build_name_index([(p[0], p[1], p[2]) for p in players])
        by_dob: dict[str, list[str]] = {}
        for identifier, dob in conn.execute(
            "SELECT identifier, date_of_birth FROM players WHERE date_of_birth IS NOT NULL"
        ):
            by_dob.setdefault(dob, []).append(identifier)

        teams = [
            (team_id, name, gender)
            for team_id, name, gender in conn.execute(
                "SELECT team_id, name, gender FROM teams"
            )
        ]
        competitions = list(conn.execute(
            "SELECT competition_id, display_name, gender FROM competitions"
        ))

        # Only articles that have no entity rows yet. Re-running is therefore
        # cheap, and a re-extracted article gets relinked because _persist
        # cascades its entity rows away with the article's tags.
        articles = list(conn.execute(
            """SELECT a.article_id, a.title, a.body_text
               FROM news_articles a
               WHERE NOT EXISTS (
                   SELECT 1 FROM news_article_entities e
                   WHERE e.article_id = a.article_id)
               ORDER BY a.published_at DESC
               LIMIT ?""",
            (limit,),
        ))

        for position, (article_id, title, body_text) in enumerate(articles):
            activity.heartbeat(position)
            considered += 1
            tags = list(conn.execute(
                """SELECT t.kind, t.value FROM news_article_tags at
                   JOIN news_tags t ON t.tag_id = at.tag_id
                   WHERE at.article_id = ?""",
                (article_id,),
            ))
            haystack = f"{title or ''}\n{body_text or ''}"

            for kind, value in tags:
                name, dob = ns.split_person_tag(value)
                identifier = confidence = None

                if dob and len(by_dob.get(dob, [])) == 1:
                    identifier, confidence = by_dob[dob][0], "tag_dob"
                elif dob and len(by_dob.get(dob, [])) > 1:
                    # Several players share the date; fall through to the name
                    # index, which may still resolve it, rather than picking.
                    identifier = _resolve_any_gender(index, name)
                    confidence = "tag_name" if identifier else None
                elif kind in ("entity", "keyword"):
                    # `keyword` is included, and that is safe only because
                    # resolve_player refuses to answer when more than one
                    # player fits. The Guardian and Sky do not mark up people
                    # separately from topics: "Joe Root" and "Ben Stokes" sit
                    # in the same tag list as "Cricket", "Birdwatching" and
                    # "Australia sport". Measured over all 63 distinct keyword
                    # tags in the archive, this resolves 6 - Flintoff, Flower,
                    # Stokes, McCullum, Brook, Root, every one correct - and
                    # refuses the other 57. Without it those two publishers
                    # contribute no player links at all, because only the ICC
                    # tags people explicitly.
                    identifier = _resolve_any_gender(index, name)
                    confidence = "tag_name" if identifier else None

                if identifier and confidence:
                    changed = conn.execute(
                        """INSERT OR IGNORE INTO news_article_entities
                               (article_id, entity_type, player_identifier,
                                mention, confidence)
                           VALUES (?, 'player', ?, ?, ?)""",
                        (article_id, identifier, name, confidence),
                    ).rowcount
                    if changed:
                        linked[confidence] += 1

            # Gender is a schema property here: men's and women's "Australia"
            # are different team_ids. An article does not declare one, so it
            # is inferred from explicit markers and the confidence records
            # which of the two happened. Linking to a gendered row without
            # saying the gender was defaulted would be a silent guess; adding
            # a fourth confidence value makes it a visible one.
            article_gender = _infer_gender(haystack)
            confidence = "body_name" if article_gender else "body_name_men_default"
            wanted_gender = article_gender or "male"
            matched_teams = 0
            for team_id, name, gender in teams:
                if matched_teams >= MAX_TEAMS_PER_ARTICLE:
                    break
                # Word-boundary match. Names under four characters are skipped
                # because a short side name matches inside ordinary words.
                if len(name) < 4 or gender != wanted_gender:
                    continue
                if re.search(rf"\b{re.escape(name)}\b", haystack):
                    changed = conn.execute(
                        """INSERT OR IGNORE INTO news_article_entities
                               (article_id, entity_type, team_id, mention, confidence)
                           VALUES (?, 'team', ?, ?, ?)""",
                        (article_id, team_id, name, confidence),
                    ).rowcount
                    matched_teams += 1
                    if changed:
                        linked["body_name"] += 1

            # Competitions are gendered on (key, gender) exactly as teams are,
            # so the same rule applies: pick the row matching the inferred
            # gender and record whether that was established or defaulted.
            # Without the filter, INSERT OR IGNORE on
            # (article_id, entity_type, mention) kept whichever gender the
            # scan happened to reach first.
            for competition_id, display_name, gender in competitions:
                if len(display_name) < 4 or gender != wanted_gender:
                    continue
                if re.search(rf"\b{re.escape(display_name)}\b", haystack, re.I):
                    conn.execute(
                        """INSERT OR IGNORE INTO news_article_entities
                               (article_id, entity_type, competition_id,
                                mention, confidence)
                           VALUES (?, 'competition', ?, ?, ?)""",
                        (article_id, competition_id, display_name, confidence),
                    )
                    break
        conn.commit()

    activity.logger.info(
        f"news entities: {considered} articles, "
        f"{linked['tag_dob']} by tag+DOB, {linked['tag_name']} by tag name, "
        f"{linked['body_name']} teams/competitions by name"
    )
    return {"considered": considered, **linked}


# A match report names both sides plus a handful of others in passing. Four
# is enough for "who is this about" and stops a season preview linking to
# thirty sides.
MAX_TEAMS_PER_ARTICLE = 4

# Markers that a piece is about women's cricket. Deliberately explicit rather
# than statistical: the cost of getting this wrong is filing a women's match
# report under the men's side, which is precisely the conflation this schema's
# gender separation exists to prevent.
_WOMEN_MARKERS = re.compile(
    r"\b(women'?s?|"
    r"WBBL|WPL|The Hundred Women|"
    r"Women'?s? (?:World Cup|Ashes|T20|ODI|Test|Big Bash|Premier League))\b",
    re.I,
)


def _infer_gender(text: str) -> str | None:
    """'female' when the text says so, else None. Never guesses 'male'."""
    return "female" if _WOMEN_MARKERS.search(text or "") else None


def _resolve_any_gender(index: dict, name: str) -> str | None:
    """resolve_player across both genders, refusing when both answer.

    resolve_player needs a gender because men's and women's cricket are
    separate identities throughout this schema, and a news article does not
    carry one. Trying both and requiring exactly one hit keeps the "never
    guess" rule: a name that exists in both registers stays unlinked rather
    than being filed under whichever was tried first.
    """
    hits = {
        resolved
        for gender in ("male", "female")
        if (resolved := resolve_player(index, name, gender)) is not None
    }
    return hits.pop() if len(hits) == 1 else None


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------
#
# Images are REFERENCED, not stored and not proxied. Three reasons, in order
# of weight:
#
#  1. Licensing. Every hero on these four sources is agency photography
#     (Getty, Alamy, PA, Reuters). An RSS or API grant covers reading the
#     metadata; it does not cover making and serving a copy. This project
#     already made the same call for players.image_url, and there the asset
#     was freely licensed Wikimedia, so the argument is stronger here.
#  2. The publishers' CDNs are Cloudinary, Akamai and Fastly. Re-hosting from
#     one SQLite box would be a downgrade in every measurable way.
#  3. Storage. At the observed 130 KB per hero, mirroring a year of four
#     sources is tens of GB beside a 645 MB database.
#
# What IS done is upgrading each URL to the largest rendition the CDN is known
# to serve (news_sources.best_rendition, verified against each CDN), recording
# the asset fingerprint so one photograph is one row across articles, and
# optionally measuring dimensions the source did not declare. The measurement
# reads the image header and discards the bytes; it never keeps a copy.

# Enough of a JPEG/PNG/WebP to reach the header that carries the dimensions.
_IMAGE_HEADER_BYTES = 65536


def _dimensions_from_header(data: bytes) -> tuple[int, int] | None:
    """Width and height straight out of the file header, no image library.

    Covers the three formats these CDNs serve. Returns None rather than a
    guess: a fabricated dimension is worse than a missing one, because a
    layout will act on it.
    """
    if len(data) < 24:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return width, height
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            width = int.from_bytes(data[24:27], "little") + 1
            height = int.from_bytes(data[27:30], "little") + 1
            return width, height
        if chunk == b"VP8 " and len(data) >= 30:
            return (
                int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF,
            )
        if chunk == b"VP8L" and len(data) >= 25:
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        return None
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                return None
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(">HH", data[i + 5 : i + 9])
                return width, height
            segment = struct.unpack(">H", data[i + 2 : i + 4])[0]
            i += 2 + segment
    return None


@activity.defn
async def probe_news_images(limit: int = 200) -> dict:
    """Measure images no source gave dimensions for. Off unless enabled.

    Uses a Range request for the first 64 KB, which is enough for every header
    format above and avoids pulling a 460 KB original to learn two integers.
    Failures are recorded on the row (probe_status) rather than retried, so a
    dead asset costs one request ever.
    """
    if not IMAGE_PROBE_ENABLED:
        return {"enabled": False, "probed": 0, "measured": 0, "failed": 0,
                "reason": "NEWS_IMAGE_PROBE is not set to 1"}

    with get_connection() as conn:
        rows = list(conn.execute(
            """SELECT image_id, cdn_url FROM news_images
               WHERE (width IS NULL OR height IS NULL) AND probed_at IS NULL
               LIMIT ?""",
            (limit,),
        ))

    measured = failed = 0
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:
        for position, (image_id, url) in enumerate(rows):
            activity.heartbeat(position)
            width = height = None
            status = "no-dimensions"
            byte_size = mime = None
            try:
                resp = await client.get(
                    url, headers={"Range": f"bytes=0-{_IMAGE_HEADER_BYTES - 1}"}
                )
                if resp.status_code in (200, 206):
                    mime = resp.headers.get("content-type")
                    byte_size = _int_or_none_str(
                        (resp.headers.get("content-range") or "").rsplit("/", 1)[-1]
                    ) or _int_or_none_str(resp.headers.get("content-length"))
                    found = _dimensions_from_header(resp.content)
                    if found:
                        width, height = found
                        status = "ok"
                        measured += 1
                    else:
                        failed += 1
                else:
                    status = f"http-{resp.status_code}"
                    failed += 1
            except httpx.HTTPError as e:
                status = f"error-{type(e).__name__}"
                failed += 1

            with get_connection() as conn:
                conn.execute(
                    """UPDATE news_images
                       SET width = COALESCE(?, width), height = COALESCE(?, height),
                           mime_type = COALESCE(?, mime_type),
                           byte_size = COALESCE(?, byte_size),
                           probed_at = ?, probe_status = ?
                       WHERE image_id = ?""",
                    (width, height, mime, byte_size, _now(), status, image_id),
                )
                conn.commit()

    activity.logger.info(
        f"news images: probed {len(rows)}, measured {measured}, {failed} unmeasurable"
    )
    return {"enabled": True, "probed": len(rows), "measured": measured, "failed": failed}


def _int_or_none_str(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Retry sweep and progress
# --------------------------------------------------------------------------

@activity.defn
async def news_retry_sweep(limit: int = 200) -> dict:
    """Re-queue failures whose backoff has elapsed.

    Deliberately a separate activity rather than a retry inside the fetch
    loop. A URL that failed because the publisher was down should be tried in
    an hour, not in three seconds, and Temporal's activity retry cannot
    express "later, in a different run" -- that is what the ledger's
    next_attempt_after column is for.

    Rows past MAX_ATTEMPTS are abandoned, not retried forever. Five spaced
    attempts over four days is enough to distinguish an outage from a page
    that has genuinely moved.
    """
    now = _now()
    with get_connection() as conn:
        due = list(conn.execute(
            """SELECT url_fingerprint, source_key FROM news_ingestions
               WHERE status = 'failed'
                 AND attempts < ?
                 AND (next_attempt_after IS NULL OR next_attempt_after <= ?)
               ORDER BY next_attempt_after
               LIMIT ?""",
            (MAX_ATTEMPTS, now, limit),
        ))
        for fingerprint, _source in due:
            conn.execute(
                "UPDATE news_ingestions SET status = 'pending' WHERE url_fingerprint = ?",
                (fingerprint,),
            )
        abandoned = conn.execute(
            "SELECT COUNT(*) FROM news_ingestions WHERE status = 'failed' AND attempts >= ?",
            (MAX_ATTEMPTS,),
        ).fetchone()[0]
        conn.commit()

    by_source: dict[str, int] = {}
    for _fingerprint, source_key in due:
        by_source[source_key] = by_source.get(source_key, 0) + 1
    activity.logger.info(
        f"news retry sweep: {len(due)} re-queued {by_source}, {abandoned} abandoned "
        f"after {MAX_ATTEMPTS} attempts"
    )
    return {"requeued": len(due), "by_source": by_source, "abandoned": abandoned}


@activity.defn
async def record_news_progress(source_key: str, stored: int, unchanged: int,
                               invalid: int, failed: int) -> None:
    """Stamp the publisher's last sync and log a per-source line.

    Reuses `ingestion_progress`'s spirit without reusing its table: that one
    is keyed on competition_key and counts matches, and overloading it would
    make "processed" mean two different things depending on the row.
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE news_publishers SET last_synced_at = ? WHERE key = ?",
            (_now(), source_key),
        )
        conn.commit()
    activity.logger.info(
        f"news progress {source_key}: {stored} stored, {unchanged} unchanged, "
        f"{invalid} invalid, {failed} failed"
    )


@activity.defn
async def news_health() -> dict:
    """A snapshot of what the pipeline currently holds, for observability.

    Read by the daily workflow so its return string is a real report rather
    than a count of what one run happened to touch, and served by
    /api/news/health so the same numbers are visible without Temporal.
    """
    with get_connection() as conn:
        totals = dict(conn.execute(
            "SELECT status, COUNT(*) FROM news_ingestions GROUP BY status"
        ))
        per_source = [
            {"source": row[0], "articles": row[1], "latest": row[2],
             "with_hero": row[3], "linked_players": row[4]}
            for row in conn.execute(
                """SELECT a.source_key, COUNT(*), MAX(a.published_at),
                          SUM(CASE WHEN EXISTS (
                              SELECT 1 FROM news_article_images i
                              WHERE i.article_id = a.article_id AND i.role = 'hero'
                          ) THEN 1 ELSE 0 END),
                          SUM(CASE WHEN EXISTS (
                              SELECT 1 FROM news_article_entities e
                              WHERE e.article_id = a.article_id
                                AND e.entity_type = 'player'
                          ) THEN 1 ELSE 0 END)
                   FROM news_articles a GROUP BY a.source_key ORDER BY 2 DESC"""
            )
        ]
        breakers = [
            {"source": row[0], "failures": row[1], "feed": row[2]}
            for row in conn.execute(
                """SELECT source_key, consecutive_failures, feed_url
                   FROM news_feed_state WHERE consecutive_failures > 0
                   ORDER BY consecutive_failures DESC"""
            )
        ]
        syndicated = conn.execute(
            "SELECT COUNT(*) FROM news_articles WHERE syndication_of_article_id IS NOT NULL"
        ).fetchone()[0]
    return {"ledger": totals, "sources": per_source, "syndicated": syndicated,
            "degraded_feeds": breakers, "extractor_version": ns.EXTRACTOR_VERSION}
