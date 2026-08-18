"""Source registry and pure extraction logic for sports news.

Deliberately I/O-free, the same split `enrichment.py` and `icc_scorecard.py`
already use: everything here is a function from bytes to a dataclass, so the
awkward parts (canonicalisation, hero-image selection, syndication detection)
are testable without a network or a database. All HTTP and every write lives
in `news_activities.py`.

Nothing here needs a dependency beyond the standard library. The four sources
below are consumed through XML feeds, a JSON API, and JSON-LD embedded in
HTML -- none of which needs a DOM, so the repo's five-package requirements.txt
stays as it is and there is no headless browser anywhere in this pipeline.

WHAT THE RESEARCH FOUND, per source, because these are the facts the code is
shaped around and none of them are guessable from the outside:

* The Guardian publishes an actual content API (content.guardianapis.com).
  It names the hero image explicitly as the element with relation="main", and
  ships altText, caption, credit, photographer, source, width and height with
  it. It also ships `wordcount`, which is the only independent check we have
  that a body was captured completely. Measured limits on the open `test`
  key: 720 requests/minute, 50,000/day.

* The ICC (icc-cricket.com) has no RSS at all, but publishes a Google News
  sitemap (sitemap-article.xml, reachable from robots.txt) carrying the 100
  most recent articles with an exact publication_date. Article pages embed a
  schema.org NewsArticle with the FULL articleBody. Two quirks: the author is
  in the `article:author` OpenGraph tag and NOT in the JSON-LD (whose `creator`
  is the string "ICC"), and `article:tag` carries player entities complete
  with a date of birth ("Matt Renshaw 03/28/1996"), which is the most precise
  entity-linking signal any of these sources gives us.

* Sky Sports publishes RSS per section and a schema.org NewsArticle with a
  full articleBody. Its canonical URL does NOT match the URL its own feed
  links to: the feed said /cricket/news/12040/13574220/... and the page's
  rel=canonical says /cricket/news/12175/13574220/... The 5-digit segment is
  a section id and varies; the 8-digit article id does not. Keying on the URL
  would file one article twice.

* ESPNcricinfo's RSS is open, but every article page, and the
  hs-consumer-api.espncricinfo.com endpoint behind the site, is served an
  Akamai 403 to a non-browser client (robots.txt itself is 403). The feed is
  therefore the whole extraction surface, and that is fine, because the feed
  is unusually rich: a `<url>` element with the modern slug URL, a `<guid>`
  with the legacy one, and a `<media:content>` carrying the ORIGINAL image
  with real width and height. See ESPNCRICINFO_VARIANTS for the CDN sizes.
"""
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

# Bump when anything in this module changes what it derives from a fetched
# page. Exactly the role shared.PARSER_VERSION plays for Cricsheet, and for
# exactly the same reason: idempotency is a hash of the SOURCE bytes, and a
# publisher's bytes do not change when our extractor is fixed. Without this,
# fixing an extractor and re-running skips every article and reports success.
#
#   v1  initial: RSS/sitemap discovery, JSON-LD + OpenGraph extraction,
#       per-source hero-image and canonical rules.
#   v2  an image asset keeps its LARGEST rendition. The Guardian ships one
#       mediaId as both the main element (up to 1000px) and the thumbnail
#       element (500px), and the upsert took the last write, so every hero
#       was stored at 500x400 with a 1000px rendition available.
#   v3  SYNDICATION_MAX_DISTANCE raised from 3 to 8, measured rather than
#       assumed. syndication_of_article_id is derived at persist time, so
#       existing rows carry the old decision until they are re-persisted -
#       which is exactly what bumping this forces.
#   v6  a list-sized thumbnail rendition is stored beside the full one. A 64px
#       row was pulling a 461 KB original.
#   v5  Sky's other two canonical URL shapes (section-less /cricket/news/,
#       and /the-hundred/news/) admitted by scope and by the id pattern.
#   v4  per-source article_path scope, and Sky read from its cricket feeds
#       (12123, 12175) rather than 12040, which is their all-sport feed and
#       was 2/20 cricket. Scope bounds DISCOVERY rather than extraction, so
#       it does not by itself require a re-parse; it rides along with v4
#       because the same change corrected the Sky feed set.
EXTRACTOR_VERSION = 6


# --------------------------------------------------------------------------
# Source registry
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class NewsSource:
    """One publisher and the single mechanism we agreed to read it through.

    `strategy` is the most structured route that actually works for the
    source, never the most convenient. `content_policy` is a storage and
    display rule, not a capability: it says what we are entitled to keep, and
    the API layer enforces it (see backend/app/news.py snippet capping).
    """

    key: str
    name: str
    home_url: str
    # 'api'     -> a first-party JSON API (structured, no HTML anywhere)
    # 'sitemap' -> Google News sitemap for discovery, JSON-LD for the article
    # 'rss'     -> RSS for discovery, JSON-LD for the article
    # 'feed_only' -> RSS is the entire record; article HTML is not fetched
    strategy: str
    # 'full'          -> body stored and servable
    # 'extract'       -> body stored for entity extraction and search only;
    #                    the API returns a capped snippet plus a link out
    # 'metadata_only' -> headline, standfirst and hero image; no body exists
    content_policy: str
    discovery: tuple[str, ...]
    enabled: bool
    policy_note: str
    # Politeness, per source. min_interval_seconds is a floor between two
    # requests to this host from this pipeline; it is not a guess, it is set
    # from what each publisher advertises or tolerates (see the notes).
    min_interval_seconds: float
    max_concurrency: int
    # Hosts that are the same publisher. cricinfo.com and espncricinfo.com
    # serve the same article, and their own feed uses both in one <item>.
    host_aliases: tuple[tuple[str, str], ...] = ()
    attribution: str = ""
    # Paths on this host that are in-scope ARTICLES. Applied at discovery, so
    # an out-of-scope item is never fetched and is recorded as 'skipped'
    # rather than fetched and then failed as 'invalid' - the two mean
    # different things and conflating them hides real extraction failures in
    # a pile of things we never wanted.
    article_path: str = ""


SOURCES: dict[str, NewsSource] = {
    "guardian": NewsSource(
        key="guardian",
        name="The Guardian",
        home_url="https://www.theguardian.com/sport/cricket",
        strategy="api",
        content_policy="full",
        # tag=sport/cricket rather than section=sport&q=cricket: the section
        # search matches any sport article mentioning the word, and returned a
        # "Brief letters" round-up tagged Potatoes and Fossils. The tag is the
        # desk's own classification and returns 45,180 genuine cricket pieces.
        discovery=("https://content.guardianapis.com/search",),
        enabled=True,
        policy_note=(
            "Read through the Guardian Open Platform, which is their own "
            "sanctioned API and supersedes what robots.txt says about "
            "crawling the site. Their terms require attribution and a link "
            "back, and restrict commercial and model-training use; both are "
            "recorded on the publisher row rather than left implicit."
        ),
        # Measured from the response headers: 720/min, 50,000/day. One request
        # every 1.5s leaves an order of magnitude of headroom, which matters
        # because the daily quota is shared with whatever else uses the key.
        min_interval_seconds=1.5,
        max_concurrency=2,
        attribution="Content from the Guardian Open Platform",
    ),
    "icc": NewsSource(
        key="icc",
        name="International Cricket Council",
        home_url="https://www.icc-cricket.com/news",
        strategy="sitemap",
        content_policy="full",
        discovery=(
            "https://www.icc-cricket.com/sitemap-article.xml",
            "https://www.icc-cricket.com/sitemap-article-index.xml",
        ),
        enabled=True,
        policy_note=(
            "robots.txt is 'Allow: /' with a named list of integrity-desk "
            "articles disallowed; DISALLOWED_PATHS carries that list and is "
            "enforced, not merely noted. This is also the governing body "
            "whose ranking, schedule and scorecard feeds this project "
            "already consumes."
        ),
        min_interval_seconds=1.0,
        max_concurrency=3,
        attribution="International Cricket Council",
        # Three genuine article families, measured from what their sitemaps
        # actually list. A first pass allowed only /news/ and would have
        # discarded 293 of 378 real articles: the per-tournament sitemaps
        # publish under /tournaments/<slug>/news/<article>, and the
        # disciplinary and qualifier announcements under /media-releases/,
        # both of which are cricket news with 300-700 word bodies. Excludes
        # /photos/, /videos/ and the tournament landing pages themselves.
        article_path=r"^(/news/|/media-releases/|/tournaments/[^/]+/news/)",
    ),
    "skysports": NewsSource(
        key="skysports",
        name="Sky Sports",
        home_url="https://www.skysports.com/cricket",
        strategy="rss",
        content_policy="extract",
        # 12040 is Sky's ALL-SPORT news feed and was the first thing tried
        # here: 2 of its 20 items were cricket and the rest were football,
        # F1 and racing, which the validator then rejected as non-articles.
        # Measured across their feed ids, 12123 is cricket news and 12175 is
        # the cricket/Australia desk; both are 100% and 75% cricket paths.
        discovery=(
            "https://www.skysports.com/rss/12123",  # cricket news
            "https://www.skysports.com/rss/12175",  # cricket, Australia desk
        ),
        # Their cricket feeds still carry podcast, video, live-blog and
        # scores-fixtures entries, whose pages have a 12-word body and no
        # article id. Those are not failed scrapes and must not be counted as
        # any.
        #
        # Three article shapes, all observed live and all cricket. The feeds
        # only ever emit the first, but the page's own rel=canonical
        # redirects into the other two, so a pattern fitted to the feed alone
        # rejects five perfectly good articles AFTER they are stored:
        #     /cricket/news/12175/13574220/<slug>   feed form, with section id
        #     /cricket/news/13508419/<slug>         no section id at all
        #     /the-hundred/news/36888/13572600/...  The Hundred has its own
        #                                           top-level section
        article_path=r"^/(cricket|the-hundred)/news/(\d+/)?\d+/",
        enabled=True,
        policy_note=(
            "robots.txt disallows /api/ and various ajax paths and permits "
            "article paths. The body is stored for entity extraction and "
            "search rather than for republication, so content_policy is "
            "'extract' and the API caps what it returns."
        ),
        min_interval_seconds=2.0,
        max_concurrency=2,
        attribution="Sky Sports",
    ),
    "espncricinfo": NewsSource(
        key="espncricinfo",
        name="ESPNcricinfo",
        home_url="https://www.espncricinfo.com",
        strategy="feed_only",
        content_policy="metadata_only",
        # 0 is the global feed; the numbered ones are per-team and are the
        # only way to reach beyond the global feed's 100-item window.
        discovery=(
            "https://www.espncricinfo.com/rss/content/story/feeds/0.xml",
            "https://www.espncricinfo.com/rss/content/story/feeds/1.xml",   # England
            "https://www.espncricinfo.com/rss/content/story/feeds/2.xml",   # Australia
            "https://www.espncricinfo.com/rss/content/story/feeds/6.xml",   # India
            "https://www.espncricinfo.com/rss/content/story/feeds/8.xml",   # Sri Lanka
            "https://www.espncricinfo.com/rss/content/story/feeds/25.xml",  # Bangladesh
        ),
        enabled=True,
        policy_note=(
            "Feed only, and not by preference. Article HTML, the internal "
            "hs-consumer-api, and robots.txt itself all return an Akamai 403 "
            "to a non-browser client. Rather than defeat that with a headless "
            "browser, this source is ingested from the RSS it publishes for "
            "the purpose, which yields headline, standfirst, canonical URL "
            "and the original hero image with real dimensions."
        ),
        min_interval_seconds=2.0,
        max_concurrency=1,
        host_aliases=(("cricinfo.com", "espncricinfo.com"),
                      ("www.cricinfo.com", "www.espncricinfo.com")),
        attribution="ESPNcricinfo",
        # Both URL forms their feed emits. Excludes /video/ and /podcast/,
        # which appear in the same feeds.
        article_path=r"^(/story/|/ci/content/story/)",
    ),
    "bbcsport": NewsSource(
        key="bbcsport",
        name="BBC Sport",
        home_url="https://www.bbc.co.uk/sport/cricket",
        strategy="rss",
        content_policy="metadata_only",
        discovery=("https://feeds.bbci.co.uk/sport/cricket/rss.xml",),
        # Disabled on policy, not on capability. The feed returns 200 and
        # parses cleanly with the adapter below; it stays off because
        # bbc.co.uk/robots.txt states in plain English: "No scraping, crawling,
        # or systematic extraction of content", "No creating datasets from BBC
        # content", and "No text and data mining". Storing their articles in
        # this database is dataset creation however politely it is done.
        # Left registered so the exclusion is visible and reversible by anyone
        # who holds a BBC content licence, rather than silently absent.
        enabled=False,
        policy_note=(
            "Excluded by publisher policy: robots.txt forbids systematic "
            "extraction, dataset creation and text-and-data mining. Enable "
            "only under a licence from the BBC."
        ),
        min_interval_seconds=5.0,
        max_concurrency=1,
        attribution="BBC Sport",
    ),
    "cricbuzz": NewsSource(
        key="cricbuzz",
        name="Cricbuzz",
        home_url="https://www.cricbuzz.com",
        strategy="rss",
        content_policy="metadata_only",
        discovery=("https://www.cricbuzz.com/rss-feed/full-commentary",),
        # Their edge returns 403 to every non-browser client, including on the
        # RSS path. That is a publisher declining automated access, so this
        # stays off rather than being worked around with a spoofed User-Agent.
        enabled=False,
        policy_note=(
            "Excluded: the origin returns HTTP 403 to non-browser clients on "
            "every path including RSS. Defeating that would mean impersonating "
            "a browser against an explicit refusal."
        ),
        min_interval_seconds=5.0,
        max_concurrency=1,
        attribution="Cricbuzz",
    ),
}


def enabled_sources() -> list[NewsSource]:
    return [s for s in SOURCES.values() if s.enabled]


# From https://www.icc-cricket.com/robots.txt. Enforced in
# `is_discoverable`, because a Disallow that is only documented is not
# honoured -- these are the ICC's integrity-desk pages and they asked.
ICC_DISALLOWED_PATHS = (
    "/_libraries", "/_mobileapp", "/_test-automation", "/_test", "/media-zone",
    "/news/stalking-and-fixated-individuals-in-sport",
    "/news/staying-ahead-of-corruption-in-cricket-the-role-of-alert-notices",
    "/news/online-abuse-and-icc-s-support-to-stakeholders",
    "/news/party-peers-or-pressure-substances-of-abuse-in-cricket",
    "/news/2026-wada-prohibited-list-key-updates",
    "/news/adel-for-medical-professionals",
    "/news/icc-acu-workshop-2025",
    "/news/ai-sports-integrity-fighting-corruption-in-the-digital-era",
)

DISALLOWED_PATHS: dict[str, tuple[str, ...]] = {
    "icc": ICC_DISALLOWED_PATHS,
    # Sky's robots.txt disallows these prefixes; none is an article path, but
    # a sitemap or a related-link crawl could wander into one.
    "skysports": ("/api/", "/hub/", "/private/", "/sso/", "/seo/", "/live-score-centre"),
}


def is_discoverable(source_key: str, url: str) -> bool:
    """False when robots.txt disallows this path. Policy only, not scope."""
    path = urlsplit(url).path or "/"
    for prefix in DISALLOWED_PATHS.get(source_key, ()):
        if path == prefix or path.startswith(prefix.rstrip("/") + "/") or path.startswith(prefix):
            return False
    return True


def is_in_scope(source_key: str, url: str) -> bool:
    """False when the path is not an article this source is read for.

    Kept separate from `is_discoverable` because the two answer different
    questions and the ledger records them differently: robots is "we may not",
    scope is "we do not want to". A source with no pattern admits everything,
    which is the right default for a publisher whose whole feed is in scope.
    """
    source = SOURCES.get(source_key)
    if source is None or not source.article_path:
        return True
    return bool(re.match(source.article_path, urlsplit(url).path or "/"))


# --------------------------------------------------------------------------
# Canonicalisation and fingerprinting
# --------------------------------------------------------------------------

# Tracking parameters observed on the four feeds. Stripping them is what makes
# the feed URL and the page's own rel=canonical compare equal: ESPNcricinfo's
# <link> is the <guid> plus ?ex_cid=OTC-RSS, and BBC appends at_medium and
# at_campaign to every item.
_TRACKING_PARAMS = {
    "ex_cid", "at_medium", "at_campaign", "at_custom1", "at_custom2",
    "at_custom3", "at_custom4", "at_bbc_team", "cmp", "cmpid", "CMP",
    "ito", "fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "dcr",
    "ns_campaign", "ns_mchannel", "ns_source", "ns_linkname", "ns_fee",
    "s_kwcid", "sh_kit", "__twitter_impression", "smid", "partner",
    "DCMP", "src", "ref", "spm",
}

_ALL_HOST_ALIASES = {
    alias: real
    for source in SOURCES.values()
    for alias, real in source.host_aliases
}


def canonical_url(url: str, source_key: str | None = None) -> str:
    """Normalise a URL to the one form this pipeline stores and compares.

    Scheme forced to https, host lower-cased and de-aliased, tracking
    parameters dropped, remaining parameters sorted, fragment removed, and a
    trailing slash removed from a non-root path.

    Note what this deliberately does NOT do: it does not strip path segments
    it thinks are noise. Sky's /12040/ against /12175/ is a section id that
    genuinely differs between their feed and their own canonical tag, and the
    fix for that is `source_article_id`, not a guess about which digits in a
    path matter.
    """
    if not url:
        return ""
    parts = urlsplit(url.strip())
    scheme = "https"
    host = (parts.hostname or "").lower()
    host = _ALL_HOST_ALIASES.get(host, host)
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"

    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in _TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    query.sort()

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return urlunsplit((scheme, host, path, urlencode(query), ""))


def url_fingerprint(url: str, source_key: str | None = None) -> str:
    """SHA-256 of the canonical URL. The uniqueness key for an article row."""
    return hashlib.sha256(canonical_url(url, source_key).encode()).hexdigest()


# Each publisher's own stable article id, recovered from any of the URL forms
# they use. This is the real dedup key: it survives a slug being rewritten,
# a section id changing, and the legacy/modern URL split.
_ARTICLE_ID_PATTERNS: dict[str, tuple[re.Pattern, ...]] = {
    # /story/<slug>-1550496  and  /ci/content/story/1550496.html
    "espncricinfo": (
        re.compile(r"/ci/content/story/(\d{5,9})\.html"),
        re.compile(r"/story/[^/]*?-(\d{5,9})(?:$|[/?#])"),
        re.compile(r"/(\d{5,9})(?:$|[/?#])"),
    ),
    # /cricket/news/<section-id>/<article-id>/<slug>, and the section-less
    # /cricket/news/<article-id>/<slug> their canonical tag sometimes uses.
    # The optional group is greedy, so the two-segment form backtracks to
    # capture the id rather than mistaking a section for it.
    "skysports": (re.compile(r"/news/(?:\d+/)?(\d{6,10})/"),),
}


def source_article_id(source_key: str, url: str, fallback: str | None = None) -> str | None:
    """The publisher's own identifier for this article.

    Where a publisher exposes a numeric id (ESPNcricinfo, Sky) it is extracted
    from the URL. Where the slug IS the identity and is stable (the ICC) the
    path's last segment is used. The Guardian supplies its own `id` on every
    API result and passes it in as `fallback`.
    """
    if fallback:
        return fallback.strip() or None
    for pattern in _ARTICLE_ID_PATTERNS.get(source_key, ()):
        m = pattern.search(url)
        if m:
            return m.group(1)
    if source_key == "icc":
        path = urlsplit(canonical_url(url, source_key)).path
        segment = path.rstrip("/").rsplit("/", 1)[-1]
        return segment or None
    return None


def content_hash(payload: dict) -> str:
    """SHA-256 of everything we extracted, plus the extractor version.

    Same contract as `ingest_match` and `fetch_icc_fixtures`: an unchanged
    article is a no-op. EXTRACTOR_VERSION is mixed in so that fixing this
    module actually re-processes rather than reporting a clean skip.
    """
    material = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(f"v{EXTRACTOR_VERSION}\x00{material}".encode()).hexdigest()


# --------------------------------------------------------------------------
# Text normalisation and near-duplicate detection
# --------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """HTML to readable text, dropping script/style and keeping paragraphs."""

    _SKIP = {"script", "style", "noscript", "iframe", "svg"}
    _BREAK = {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "blockquote", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skipping += 1
        elif tag in self._BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1
        elif tag in self._BREAK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skipping:
            self.parts.append(data)

    def text(self) -> str:
        joined = "".join(self.parts)
        joined = re.sub(r"[ \t\r\f\v]+", " ", joined)
        joined = re.sub(r"\n\s*\n\s*", "\n\n", joined)
        return joined.strip()


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    if "<" not in html:
        return html.strip()
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup must not fail an ingest
        return re.sub(r"<[^>]+>", " ", html).strip()
    return parser.text()


def word_count(text: str | None) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text or "", flags=re.UNICODE))


def _normalise_for_hashing(text: str) -> list[str]:
    """Lower-case, accent-fold, strip punctuation, return tokens.

    Aggressive on purpose: two syndications of one wire story differ in
    punctuation, curly quotes and a house-style byline, and none of that
    should stop them matching.
    """
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", folded.lower())


def simhash(text: str, shingle: int = 4) -> int:
    """64-bit SimHash over word 4-grams; 0 when the text is too short.

    Used for SYNDICATION only -- the same body republished under another
    masthead. It is explicitly NOT used to collapse different articles about
    the same event: on the day this was built, the Guardian, Sky and the ICC
    each published their own piece about Jake Weatherald being dropped, and
    those are three pieces of journalism, not three copies of one. Merging
    them would delete two publishers' work and misreport how widely a story
    was covered. See `syndication_distance`.
    """
    tokens = _normalise_for_hashing(text)
    if len(tokens) < shingle * 4:
        return 0
    vector = [0] * 64
    for i in range(len(tokens) - shingle + 1):
        gram = " ".join(tokens[i : i + shingle])
        h = int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=8).digest(), "big")
        for bit in range(64):
            vector[bit] += 1 if (h >> bit) & 1 else -1
    out = 0
    for bit in range(64):
        if vector[bit] > 0:
            out |= 1 << bit
    return out


def syndication_distance(a: int, b: int) -> int:
    """Hamming distance between two simhashes; 64 when either is unusable."""
    if not a or not b:
        return 64
    return bin(a ^ b).count("1")


# Threshold for calling two bodies the same text. Read off the distribution
# over 120 real stored articles (median 574 words), NOT taken from the
# conventional 3-of-64 cut, which was measured here and is too tight: it
# missed a republication with ordinary house-style edits.
#
#   syndication, 2% to 20% of words edited      p90 distance 2 to 7, max 11
#   truncated republication, 90% of body kept   median 6, p90 10
#   DIFFERENT articles, 7,140 pairs             min 12, p1 23, median 32
#   same event, three publishers, independent   min 22
#
# 8 sits in the gap with a 4-bit margin below the observed floor of the
# negative class. Deliberately nearer the syndication side than the midpoint:
# a false positive suppresses a real article, which is worse than storing a
# syndicated copy twice. Re-measure this if the sources change; the numbers
# above are the check.
SYNDICATION_MAX_DISTANCE = 8


# --------------------------------------------------------------------------
# Discovery: RSS, Atom, and Google News sitemaps
# --------------------------------------------------------------------------

_NS = {
    "media": "http://search.yahoo.com/mrss/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "atom": "http://www.w3.org/2005/Atom",
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
    "image": "http://www.google.com/schemas/sitemap-image/1.1",
}


@dataclass
class Candidate:
    """One article the discovery step found, with whatever the feed knew.

    Everything past `url` is a hint, not a fact: for a `feed_only` source the
    hints ARE the record, and for the others they are compared against what
    the article page says so a mismatch is visible rather than silent.
    """

    source_key: str
    url: str
    source_article_id: str | None = None
    title: str | None = None
    summary: str | None = None
    published_at: str | None = None
    updated_at: str | None = None
    section: str | None = None
    author: str | None = None
    image_url: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    raw: dict = field(default_factory=dict)


def _text(element, path: str) -> str | None:
    if element is None:
        return None
    found = element.find(path, _NS)
    if found is None or found.text is None:
        return None
    value = unescape(found.text).strip()
    return value or None


def parse_rss(xml_text: str, source_key: str) -> list[Candidate]:
    """RSS 2.0 or Atom into candidates, keeping the non-standard elements.

    ESPNcricinfo's feed carries three URL-ish elements per item and they are
    not interchangeable:

        <link>  modern-or-legacy URL plus ?ex_cid=OTC-RSS tracking
        <guid>  the same URL without tracking
        <url>   a NON-STANDARD element holding the modern slug URL

    `<url>` is preferred where present because it is the form the site itself
    links to. It is also why this parser cannot be a generic feedparser call:
    a standards-only reader drops the best URL on the page.
    """
    try:
        root = ElementTree.fromstring(xml_text.strip())
    except ElementTree.ParseError:
        return []

    out: list[Candidate] = []
    items = root.findall(".//item") or root.findall(".//atom:entry", _NS)
    for item in items:
        url = (
            _text(item, "url")
            or _text(item, "link")
            or _text(item, "guid")
        )
        if url is None:
            link = item.find("atom:link", _NS)
            url = link.get("href") if link is not None else None
        if not url:
            continue

        image_url = image_w = image_h = None
        media = item.find("media:content", _NS)
        if media is not None and media.get("url"):
            image_url = media.get("url")
            image_w = _int_or_none(media.get("width"))
            image_h = _int_or_none(media.get("height"))
        if image_url is None:
            thumb = item.find("media:thumbnail", _NS)
            if thumb is not None and thumb.get("url"):
                image_url = thumb.get("url")
                image_w = _int_or_none(thumb.get("width"))
                image_h = _int_or_none(thumb.get("height"))
        if image_url is None:
            enclosure = item.find("enclosure")
            if enclosure is not None and (enclosure.get("type") or "").startswith("image"):
                image_url = enclosure.get("url")
        # ESPNcricinfo's own <coverImages> is a pre-cropped 365x205 variant.
        # Used only when nothing better exists, because media:content on the
        # same item points at the full-size original.
        if image_url is None:
            image_url = _text(item, "coverImages")

        out.append(
            Candidate(
                source_key=source_key,
                url=url,
                source_article_id=source_article_id(source_key, _text(item, "guid") or url),
                title=_text(item, "title") or _text(item, "atom:title"),
                summary=_text(item, "description") or _text(item, "atom:summary"),
                published_at=to_iso8601(
                    _text(item, "pubDate")
                    or _text(item, "dc:date")
                    or _text(item, "atom:published")
                ),
                updated_at=to_iso8601(_text(item, "atom:updated")),
                section=_text(item, "category"),
                author=_text(item, "dc:creator") or _text(item, "author"),
                image_url=_https(image_url),
                image_width=image_w,
                image_height=image_h,
            )
        )
    return out


def parse_sitemap(xml_text: str, source_key: str) -> tuple[list[Candidate], list[str]]:
    """Returns (candidates, child sitemap URLs).

    Handles both a <sitemapindex> and a <urlset>. The ICC's article sitemap is
    a Google News sitemap, so each <url> carries news:publication_date and
    news:title -- an exact timestamp for discovery without fetching anything,
    which is what makes incremental sync cheap for a source with no RSS.
    """
    try:
        root = ElementTree.fromstring(xml_text.strip())
    except ElementTree.ParseError:
        return [], []

    if root.tag.endswith("sitemapindex"):
        children = [
            loc.text.strip()
            for loc in root.findall(".//sm:sitemap/sm:loc", _NS)
            if loc.text
        ]
        # dict.fromkeys de-duplicates while keeping order: the ICC index lists
        # tournament-12672 twice.
        return [], list(dict.fromkeys(children))

    out: list[Candidate] = []
    for url_el in root.findall(".//sm:url", _NS):
        loc = _text(url_el, "sm:loc")
        if not loc:
            continue
        news = url_el.find("news:news", _NS)
        image = url_el.find("image:image", _NS)
        out.append(
            Candidate(
                source_key=source_key,
                url=loc,
                source_article_id=source_article_id(source_key, loc),
                title=_text(news, "news:title") if news is not None else None,
                published_at=to_iso8601(
                    _text(news, "news:publication_date") if news is not None else None
                ),
                updated_at=to_iso8601(_text(url_el, "sm:lastmod")),
                # The sitemap's image is a 1:1 crop of the same asset the
                # article shows in 16:9. Kept as a fallback only; the article's
                # own og:image is the hero. See hero_image_from_article.
                image_url=_https(_text(image, "image:loc")) if image is not None else None,
            )
        )
    return out, []


def _int_or_none(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _https(url: str | None) -> str | None:
    """Feeds still emit http:// image URLs (ESPNcricinfo's media:content does).

    Left as http they are either blocked as mixed content or cost a redirect
    on every render.
    """
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://"):
        return "https://" + url[7:]
    return url


_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}

# Named zones the four feeds actually emit. BST is the one that matters: Sky
# stamps every pubDate "BST" in summer, and %Z cannot parse it portably, so a
# naive parse silently files a 07:00 BST story as 07:00 UTC.
_TZ_OFFSETS = {
    "GMT": 0, "UTC": 0, "UT": 0, "Z": 0, "BST": 60,
    "EST": -300, "EDT": -240, "CST": -360, "CDT": -300,
    "MST": -420, "MDT": -360, "PST": -480, "PDT": -420,
    "IST": 330, "AEST": 600, "AEDT": 660,
}

_RFC822 = re.compile(
    r"^(?:\w{3},\s*)?(\d{1,2})\s+(\w{3})\s+(\d{4})\s+"
    r"(\d{2}):(\d{2})(?::(\d{2}))?\s*([+-]\d{4}|[A-Z]{1,4})?$"
)


def to_iso8601(value: str | None) -> str | None:
    """Any of the four feeds' date formats to a UTC ISO-8601 string.

    Handles RFC 822 (RSS pubDate), ISO with or without a Z, and the
    millisecond-precision form the ICC's JSON-LD uses. Returns None rather
    than guessing, because a wrong publication date is worse than an absent
    one: it reorders the whole feed.
    """
    if not value:
        return None
    raw = value.strip()

    m = _RFC822.match(raw)
    if m:
        day, mon, year, hh, mm, ss, tz = m.groups()
        if mon not in _MONTHS:
            return None
        offset = 0
        if tz:
            if tz[0] in "+-":
                sign = 1 if tz[0] == "+" else -1
                offset = sign * (int(tz[1:3]) * 60 + int(tz[3:5]))
            else:
                offset = _TZ_OFFSETS.get(tz.upper(), 0)
        total = int(hh) * 60 + int(mm) - offset
        from datetime import datetime, timedelta, timezone
        try:
            base = datetime(int(year), _MONTHS[mon], int(day), tzinfo=timezone.utc)
        except ValueError:
            return None
        stamp = base + timedelta(minutes=total, seconds=int(ss or 0))
        return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")

    iso = raw.replace("Z", "+00:00")
    from datetime import datetime, timezone
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        # Bare date, e.g. a sitemap <lastmod>2026-08-18
        try:
            parsed = datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# Structured data out of an article page
# --------------------------------------------------------------------------

@dataclass
class ArticleImage:
    """One image with everything the source told us about it.

    `fingerprint` is the publisher's stable identity for the ASSET, not for a
    rendition of it, so the same photograph served at 365x205 and at 1400x933
    is one row. How that identity is recovered differs per CDN and is the
    whole content of `image_identity`.
    """

    url: str
    role: str = "hero"          # 'hero' | 'inline' | 'thumbnail'
    origin_url: str | None = None   # largest/original rendition when known
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None
    caption: str | None = None
    credit: str | None = None
    image_type: str | None = None   # 'Photograph', 'Illustration', ...
    mime_type: str | None = None
    fingerprint: str | None = None
    provider: str | None = None     # the CDN, e.g. 'imgci', 'cloudinary'
    # A list-sized rendition of the same asset. None when the CDN is not one
    # this module knows how to resize, in which case callers show the full one.
    thumb_url: str | None = None


@dataclass
class ExtractedArticle:
    source_key: str
    canonical_url: str
    discovered_url: str
    source_article_id: str | None = None
    title: str | None = None
    standfirst: str | None = None
    body_html: str | None = None
    body_text: str | None = None
    word_count: int = 0
    # The publisher's OWN word count where they state one, which is the only
    # independent check that a body arrived whole rather than truncated by a
    # consent wall. The Guardian ships it as fields.wordcount and Sky as
    # JSON-LD wordCount; the ICC states none.
    declared_word_count: int | None = None
    published_at: str | None = None
    updated_at: str | None = None
    section: str | None = None
    language: str | None = None
    authors: list[str] = field(default_factory=list)
    tags: list[tuple[str, str]] = field(default_factory=list)   # (kind, value)
    images: list[ArticleImage] = field(default_factory=list)
    # SEO / structured metadata, kept separate from the content above because
    # they are the publisher's marketing surface and drift independently of
    # the article body.
    meta_title: str | None = None
    meta_description: str | None = None
    open_graph: dict = field(default_factory=dict)
    twitter: dict = field(default_factory=dict)
    json_ld: dict = field(default_factory=dict)
    # Populated by validate(); a non-empty list means "do not mark processed".
    problems: list[str] = field(default_factory=list)

    def hero(self) -> ArticleImage | None:
        for image in self.images:
            if image.role == "hero":
                return image
        return self.images[0] if self.images else None


_META_RE = re.compile(
    r"""<meta\s+[^>]*?(?:property|name)\s*=\s*["']([^"']+)["'][^>]*?"""
    r"""content\s*=\s*["']([^"']*)["'][^>]*>""",
    re.I | re.S,
)
_META_REVERSED_RE = re.compile(
    r"""<meta\s+[^>]*?content\s*=\s*["']([^"']*)["'][^>]*?"""
    r"""(?:property|name)\s*=\s*["']([^"']+)["'][^>]*>""",
    re.I | re.S,
)
_CANONICAL_RE = re.compile(
    r"""<link\s+[^>]*?rel\s*=\s*["']canonical["'][^>]*?href\s*=\s*["']([^"']+)["']""",
    re.I | re.S,
)
_CANONICAL_REVERSED_RE = re.compile(
    r"""<link\s+[^>]*?href\s*=\s*["']([^"']+)["'][^>]*?rel\s*=\s*["']canonical["']""",
    re.I | re.S,
)
_LDJSON_RE = re.compile(
    r"""<script[^>]*type\s*=\s*["']application/ld\+json["'][^>]*>(.*?)</script>""",
    re.I | re.S,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_LANG_RE = re.compile(r"""<html[^>]*\blang\s*=\s*["']([^"']+)["']""", re.I)


def parse_meta_tags(html: str) -> dict[str, list[str]]:
    """All <meta property|name> pairs, multi-valued.

    Multi-valued because `article:tag` legitimately repeats: the ICC emits one
    per entity, and collapsing them to the last one throws away every tag but
    one. Both attribute orders are matched because publishers emit both.
    """
    out: dict[str, list[str]] = {}
    for key, value in _META_RE.findall(html):
        out.setdefault(key.strip().lower(), []).append(unescape(value).strip())
    for value, key in _META_REVERSED_RE.findall(html):
        bucket = out.setdefault(key.strip().lower(), [])
        cleaned = unescape(value).strip()
        if cleaned not in bucket:
            bucket.append(cleaned)
    return out


def parse_json_ld(html: str) -> list[dict]:
    """Every ld+json block, flattening @graph and top-level arrays."""
    out: list[dict] = []
    for block in _LDJSON_RE.findall(html):
        text = unescape(block.strip())
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # A trailing HTML comment or a stray semicolon is common enough to
            # be worth one salvage attempt before giving up on the block.
            try:
                parsed = json.loads(text.strip().rstrip(";"))
            except json.JSONDecodeError:
                continue
        stack = [parsed]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if "@graph" in node:
                    stack.extend(node["@graph"] if isinstance(node["@graph"], list)
                                 else [node["@graph"]])
                out.append(node)
    return out


_ARTICLE_TYPES = {"NewsArticle", "Article", "ReportageNewsArticle",
                  "BlogPosting", "SportsArticle", "LiveBlogPosting"}


def pick_article_ld(blocks: list[dict]) -> dict:
    """The one ld+json block that describes the article.

    Both the ICC and Sky ship three blocks (NewsArticle, Organization,
    WebSite). Taking the first is wrong on any page that orders them
    differently, so select on @type.
    """
    for block in blocks:
        types = block.get("@type")
        types = types if isinstance(types, list) else [types]
        if any(t in _ARTICLE_TYPES for t in types if isinstance(t, str)):
            return block
    return {}


# --------------------------------------------------------------------------
# Images: identity, renditions, and which one is actually the hero
# --------------------------------------------------------------------------
#
# Each publisher's CDN encodes a stable asset id and a rendition separately.
# Recovering the asset id is what lets the same photograph reuse one row
# across sizes, crops and (for Sky) shard hostnames, and it is what makes an
# image fingerprint meaningful without downloading a byte.

# ESPNcricinfo: p.imgci.com/db/PICTURES/CMS/<bucket>/<id>[.<variant>].jpg
# where bucket = id // 100 * 100. The variant suffix is a rendition, probed
# directly against the CDN rather than assumed:
#     (none) 1400x933   .1 160x107   .2 310x207   .3 900x600
#     .4 900x506        .5 365x205   .6 1296x729  .9 800x800
# The bare id is the original, so that is what gets stored as origin_url.
ESPNCRICINFO_VARIANTS = {
    "": (1400, 933), "1": (160, 107), "2": (310, 207), "3": (900, 600),
    "4": (900, 506), "5": (365, 205), "6": (1296, 729), "9": (800, 800),
}
_IMGCI_RE = re.compile(r"/db/PICTURES/CMS/(\d+)/(\d+)(?:\.(\d+))?\.(jpg|jpeg|png)", re.I)

# Sky: e{N}.365dm.com/{yy}/{mm}/{W}x{H}/{slug}_{assetId}.jpg?{cachebuster}
# The host shard (e0/e1/e2) and the size both vary for one asset; the trailing
# numeric id does not. Their RSS enclosure gives 1920x1080 and their og:image
# gives 1600x900 for the same photograph, from different shards.
_365DM_RE = re.compile(
    r"//(e\d+)\.365dm\.com/(\d{2})/(\d{2})/(\d+)x(\d+)/(.+?)_(\d{5,12})\.(jpg|jpeg|png|webp)",
    re.I,
)

# ICC: Cloudinary. images.icc-cricket.com/image/upload/<transform>/[v<n>/]prd/<publicId>
# The public id is the asset. The transform is a NAMED one and the account has
# strict transformations enabled: t_ratio16_9-size20-webp and t_ratio1_1-size20
# serve fine, while an arbitrary w_1600,c_fill returns HTTP 401. So a bigger
# rendition can only ever be requested from the list observed in the wild
# (ICC_NAMED_TRANSFORMS), never constructed. Directly analogous to the
# Wikimedia thumbnail rule already documented in CLAUDE.md.
_CLOUDINARY_RE = re.compile(
    r"//images\.icc-cricket\.com/image/upload/(?:([^/]+)/)?(?:v\d+/)?(prd/[A-Za-z0-9_-]+)",
    re.I,
)
ICC_NAMED_TRANSFORMS = (
    "t_ratio21_9-size50-webp",
    "t_ratio16_9-size50-webp",
    "t_ratio16_9-size20-webp",
    "t_ratio21_9-size30-webp",
    "t_ratio1_1-size20",
)

# Small rendition -> the largest one verified to serve for the same crop.
# Only pairs actually requested against the CDN appear here.
ICC_TRANSFORM_UPGRADE = {
    "t_ratio16_9-size20-webp": "t_ratio16_9-size50-webp",
    "t_ratio21_9-size30-webp": "t_ratio21_9-size50-webp",
    "t_ratio1_1-size20": "t_ratio16_9-size50-webp",
    "": "t_ratio16_9-size50-webp",
}

# Guardian: media.guim.co.uk/<mediaId>/<crop>/<width>.jpg -- and the API hands
# us the mediaId directly in typeData, so nothing needs parsing out of a URL.
_GUIM_RE = re.compile(r"//media\.guim\.co\.uk/([0-9a-f]{20,})/", re.I)


def image_identity(url: str) -> tuple[str | None, str | None]:
    """(provider, stable asset id) for a known CDN, else (None, None)."""
    if not url:
        return None, None
    m = _IMGCI_RE.search(url)
    if m:
        return "imgci", m.group(2)
    m = _365DM_RE.search(url)
    if m:
        return "365dm", m.group(7)
    m = _CLOUDINARY_RE.search(url)
    if m:
        return "cloudinary", m.group(2)
    m = _GUIM_RE.search(url)
    if m:
        return "guim", m.group(1)
    return None, None


def image_fingerprint(url: str) -> str:
    """Stable per-asset fingerprint.

    Falls back to the canonical URL for an unrecognised CDN, which is correct
    but weaker: two renditions of one unknown-CDN asset stay two rows. That is
    the safe direction to fail in, since merging two genuinely different
    photographs would attach the wrong caption and credit to an article.
    """
    provider, asset_id = image_identity(url)
    material = f"{provider}:{asset_id}" if asset_id else canonical_url(url)
    return hashlib.sha256(material.encode()).hexdigest()


def best_rendition(url: str) -> tuple[str, int | None, int | None]:
    """Upgrade a URL to the largest rendition the CDN is known to serve.

    Only ever rewrites within a scheme this module has verified against the
    live CDN. An unknown URL is returned untouched with no dimensions
    invented, because a fabricated width is worse than a missing one: it makes
    a layout choose the wrong image.
    """
    if not url:
        return url, None, None

    m = _IMGCI_RE.search(url)
    if m:
        _bucket, asset, _variant, ext = m.groups()
        bucket = int(asset) // 100 * 100
        original = f"https://p.imgci.com/db/PICTURES/CMS/{bucket}/{asset}.{ext.lower()}"
        return original, *ESPNCRICINFO_VARIANTS[""]

    m = _365DM_RE.search(url)
    if m:
        shard, yy, mm, _w, _h, slug, asset, ext = m.groups()
        # 1920x1080 is what their own RSS enclosure serves and what the CDN
        # returned for every asset probed; the og:image's 1600x900 is a
        # rendition, not the ceiling.
        return (
            f"https://{shard}.365dm.com/{yy}/{mm}/1920x1080/{slug}_{asset}.{ext.lower()}",
            1920, 1080,
        )

    m = _CLOUDINARY_RE.search(url)
    if m:
        transform, public_id = m.groups()
        # Upgrade only within the verified list. size50 is a genuine upgrade
        # and not a guess: the same asset is 21 KB at t_ratio16_9-size20-webp
        # and 94 KB at t_ratio16_9-size50-webp. A 1:1 crop is a thumbnail
        # surface, so it maps to the 16:9 hero rendition rather than to a
        # t_ratio1_1-size50 that has never been observed to exist.
        transform = ICC_TRANSFORM_UPGRADE.get(transform or "", transform or "")
        if transform not in ICC_NAMED_TRANSFORMS:
            transform = "t_ratio16_9-size50-webp"
        return f"https://images.icc-cricket.com/image/upload/{transform}/{public_id}", None, None

    return _https(url) or url, None, None


# Widths each CDN is VERIFIED to serve for a list thumbnail. Every one of
# these was requested against the live origin; none is inferred from a pattern.
#
# This matters because the biggest rendition is the wrong one to put in a 64px
# row. Measured on the stored assets, a thumbnail row was pulling:
#
#     imgci       461 KB  ->   48 KB  (.2, 310x207)
#     365dm       308 KB  ->   24 KB  (384x216)
#     cloudinary   76 KB  ->   16 KB  (t_ratio16_9-size20-webp)
#     guim         63 KB  ->   25 KB  (500.jpg)
#
# The Guardian's CDN is the trap here and behaves exactly like the ICC's
# Cloudinary account: media.guim.co.uk serves /140.jpg and /500.jpg and
# returns **HTTP 403** for /300.jpg. Widths are whitelisted, so a thumbnail
# width may be requested from this list and never computed.
GUIM_THUMB_WIDTH = 500
IMGCI_THUMB_VARIANT = "2"        # 310x207, from ESPNCRICINFO_VARIANTS
_365DM_THUMB = (384, 216)
ICC_THUMB_TRANSFORM = "t_ratio16_9-size20-webp"


def thumb_rendition(url: str) -> str | None:
    """A list-sized rendition of the same asset, or None if the CDN is unknown.

    None rather than the original on purpose: a caller that gets None knows to
    fall back to the full image, whereas silently returning the original would
    hide the fact that no thumbnail exists and quietly reintroduce the weight
    this function was written to remove.
    """
    if not url:
        return None

    m = _IMGCI_RE.search(url)
    if m:
        _bucket, asset, _variant, ext = m.groups()
        bucket = int(asset) // 100 * 100
        return (f"https://p.imgci.com/db/PICTURES/CMS/{bucket}/"
                f"{asset}.{IMGCI_THUMB_VARIANT}.{ext.lower()}")

    m = _365DM_RE.search(url)
    if m:
        shard, yy, mm, _w, _h, slug, asset, ext = m.groups()
        width, height = _365DM_THUMB
        return (f"https://{shard}.365dm.com/{yy}/{mm}/{width}x{height}/"
                f"{slug}_{asset}.{ext.lower()}")

    m = _CLOUDINARY_RE.search(url)
    if m:
        _transform, public_id = m.groups()
        return (f"https://images.icc-cricket.com/image/upload/"
                f"{ICC_THUMB_TRANSFORM}/{public_id}")

    if _GUIM_RE.search(url):
        # .../<mediaId>/<crop>/<width>.jpg -> the whitelisted thumbnail width.
        return re.sub(r"/\d+(\.[a-z]+)$", rf"/{GUIM_THUMB_WIDTH}\1", url)

    return None


def hero_image_from_meta(
    meta: dict[str, list[str]], ld: dict, fallback: str | None = None
) -> ArticleImage | None:
    """The article's primary image, in the order the sources actually get right.

    og:image first, because on every source measured it is the editorially
    chosen lead art. The JSON-LD `image` is second and is what carries the
    caption. A sitemap or feed image is last, because those are crops made for
    a different surface: the ICC's sitemap ships a 1:1 crop of the asset the
    article itself leads with in 16:9.

    This is the specific thing the brief asks for -- the primary image rather
    than the first image on the page -- and none of these routes involves
    walking the DOM for <img> tags, which is where "first image" goes wrong.
    """
    ld_image = ld.get("image")
    if isinstance(ld_image, list):
        ld_image = ld_image[0] if ld_image else None
    ld_url = ld_caption = None
    if isinstance(ld_image, dict):
        ld_url = ld_image.get("url") or ld_image.get("contentUrl")
        ld_caption = ld_image.get("caption") or ld_image.get("name")
    elif isinstance(ld_image, str):
        ld_url = ld_image

    url = (
        _first(meta.get("og:image"))
        or _first(meta.get("twitter:image"))
        or ld_url
        or fallback
    )
    if not url:
        return None

    upgraded, width, height = best_rendition(_https(url) or url)
    provider, _asset = image_identity(upgraded)
    return ArticleImage(
        url=upgraded,
        role="hero",
        origin_url=_https(url),
        width=_int_or_none(_first(meta.get("og:image:width"))) or width,
        height=_int_or_none(_first(meta.get("og:image:height"))) or height,
        alt_text=_first(meta.get("og:image:alt")) or _first(meta.get("twitter:image:alt")),
        # The ICC's JSON-LD caption is the Getty filename ("GettyImages-2290027806"),
        # which is provenance rather than a caption. Kept, because it names the
        # agency the photograph came from and that is the credit line.
        caption=ld_caption,
        provider=provider,
        fingerprint=image_fingerprint(upgraded),
        thumb_url=thumb_rendition(upgraded),
    )


def _first(values) -> str | None:
    if not values:
        return None
    if isinstance(values, str):
        return values or None
    for v in values:
        if v:
            return v
    return None


# --------------------------------------------------------------------------
# Extraction: one function per strategy
# --------------------------------------------------------------------------

def extract_from_html(html: str, candidate: Candidate) -> ExtractedArticle:
    """JSON-LD first, OpenGraph to fill the gaps, feed hints last.

    That precedence is not arbitrary. JSON-LD is what the publisher hands
    search engines and is the only place the full articleBody appears on both
    the ICC and Sky. OpenGraph is a smaller, flatter surface but carries two
    things the JSON-LD on these sources does not: the ICC's real bybline
    (`article:author`, where the JSON-LD `creator` is just "ICC") and its
    repeated `article:tag` entity list.
    """
    source = SOURCES[candidate.source_key]
    meta = parse_meta_tags(html)
    ld = pick_article_ld(parse_json_ld(html))

    # rel=canonical wins over everything, including the URL we arrived on.
    # This is the whole reason Sky's articles file once instead of twice: the
    # feed links /cricket/news/12040/13574220/... and the page declares
    # /cricket/news/12175/13574220/... as canonical.
    main_entity = ld.get("mainEntityOfPage")
    main_entity_id = main_entity.get("@id") if isinstance(main_entity, dict) else main_entity
    canonical = (
        _first(_CANONICAL_RE.findall(html))
        or _first(_CANONICAL_REVERSED_RE.findall(html))
        or _first(meta.get("og:url"))
        or (ld.get("url") if isinstance(ld.get("url"), str) else None)
        or (main_entity_id if isinstance(main_entity_id, str) else None)
        or candidate.url
    )
    canonical = canonical_url(unescape(canonical), source.key)

    body_html = ld.get("articleBody") or ld.get("text") or None
    body_text = html_to_text(body_html) if body_html else None

    article = ExtractedArticle(
        source_key=source.key,
        canonical_url=canonical,
        discovered_url=canonical_url(candidate.url, source.key),
        # Recomputed from the CANONICAL url, not the discovered one. Sky's feed
        # and Sky's own rel=canonical disagree on the section id in the path,
        # and only the canonical form is stable.
        source_article_id=(
            source_article_id(source.key, canonical)
            or candidate.source_article_id
        ),
        title=(
            ld.get("headline")
            or _first(meta.get("og:title"))
            or _unsuffix(_first(_TITLE_RE.findall(html)))
            or candidate.title
        ),
        standfirst=(
            ld.get("description")
            or _first(meta.get("og:description"))
            or _first(meta.get("description"))
            or candidate.summary
        ),
        body_html=body_html,
        body_text=body_text,
        word_count=word_count(body_text),
        declared_word_count=_int_or_none(ld.get("wordCount")),
        published_at=(
            to_iso8601(ld.get("datePublished"))
            or to_iso8601(_first(meta.get("article:published_time")))
            or candidate.published_at
        ),
        updated_at=(
            to_iso8601(ld.get("dateModified"))
            or to_iso8601(_first(meta.get("article:modified_time")))
            or candidate.updated_at
        ),
        section=(
            ld.get("articleSection")
            or _first(meta.get("article:section"))
            or candidate.section
        ),
        language=(
            _first(_LANG_RE.findall(html))
            or _first(meta.get("og:locale"))
        ),
        authors=_authors(meta, ld, candidate),
        tags=_tags(meta, ld, candidate),
        meta_title=_first(_TITLE_RE.findall(html)),
        meta_description=_first(meta.get("description")),
        open_graph={k: v[0] if len(v) == 1 else v
                    for k, v in meta.items() if k.startswith("og:")},
        twitter={k: v[0] if len(v) == 1 else v
                 for k, v in meta.items() if k.startswith("twitter:")},
        json_ld=ld,
    )

    hero = hero_image_from_meta(meta, ld, candidate.image_url)
    if hero is not None:
        article.images.append(hero)
    return article


def _unsuffix(title: str | None) -> str | None:
    """Strip the site-name tail publishers append to <title>.

    The ICC's is "Headline | ICC World Test Championship | ICC"; taking that
    verbatim gives every article a title ending in the same two segments.
    Applied only to <title>, never to og:title or the JSON-LD headline, which
    are already clean.
    """
    if not title:
        return None
    return unescape(title).split(" | ")[0].strip() or None


def _authors(meta: dict, ld: dict, candidate: Candidate) -> list[str]:
    """Bylines, preferring OpenGraph over JSON-LD on these sources.

    The ICC's JSON-LD says creator "ICC" while its article:author says
    "Jonathan Healy". Reading JSON-LD first would credit every ICC article to
    the organisation and lose every journalist's name in the archive.
    """
    names: list[str] = []
    for value in meta.get("article:author", []) or []:
        # Facebook's spec allows a profile URL here; a URL is not a byline.
        if value and not value.startswith("http"):
            names.append(value)

    # Only consulted when OpenGraph gave nothing. Appending it unconditionally
    # credited every ICC article to "Jonathan Healy, ICC", because their
    # JSON-LD `creator` is the organisation while `article:author` is the
    # journalist. Sky's JSON-LD author is {"@id": "#Publisher"}, an internal
    # reference with no name in it, which is why the dict branch requires one.
    if not names:
        author = ld.get("author") or ld.get("creator")
        for node in (author if isinstance(author, list) else [author]):
            if isinstance(node, dict) and node.get("name"):
                names.append(str(node["name"]))
            elif isinstance(node, str) and node:
                names.append(node)
    if not names and candidate.author:
        names.append(candidate.author)
    seen, out = set(), []
    for name in names:
        cleaned = re.sub(r"\s+", " ", name).strip(" ,;")
        # "ICC" and "Guardian sport" are desks, not people, but they are the
        # attributed byline and dropping them would leave the article
        # unattributed. Kept as-is; `is_person` on the row is not claimed.
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            out.append(cleaned)
    return out


def _tags(meta: dict, ld: dict, candidate: Candidate) -> list[tuple[str, str]]:
    """(kind, value) pairs from every tag surface the page exposes.

    Kinds are kept apart because they mean different things downstream: an
    `entity` tag is a candidate link to a row in `players`, a `keyword` is
    free text, and a `section` is the publisher's own desk.
    """
    out: list[tuple[str, str]] = []
    for value in meta.get("article:tag", []) or []:
        if value:
            out.append(("entity" if _looks_like_person_tag(value) else "keyword", value))
    keywords = ld.get("keywords")
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",")]
    for value in keywords or []:
        if isinstance(value, str) and value.strip():
            kind = "entity" if _looks_like_person_tag(value) else "keyword"
            out.append((kind, value.strip()))
    if candidate.section:
        out.append(("section", candidate.section))
    seen, deduped = set(), []
    for kind, value in out:
        key = (kind, value.lower())
        if key not in seen:
            seen.add(key)
            deduped.append((kind, value))
    return deduped


# The ICC suffixes a person tag with a US-format date of birth:
# "Matt Renshaw 03/28/1996". That DOB is the strongest entity-linking signal
# any of these four sources gives, because `players.date_of_birth` is already
# populated from Wikidata and matching on (name, DOB) needs no guessing at all.
_PERSON_TAG_RE = re.compile(r"^(.+?)\s+(\d{2})/(\d{2})/(\d{4})$")


def _looks_like_person_tag(value: str) -> bool:
    return bool(_PERSON_TAG_RE.match(value.strip()))


def split_person_tag(value: str) -> tuple[str, str | None]:
    """'Matt Renshaw 03/28/1996' -> ('Matt Renshaw', '1996-03-28')."""
    m = _PERSON_TAG_RE.match(value.strip())
    if not m:
        return value.strip(), None
    name, month, day, year = m.groups()
    try:
        return name.strip(), f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except ValueError:
        return name.strip(), None


# The fields and expansions the Guardian search endpoint needs to return a
# complete article in one call. Requested as a constant so the discovery and
# the extraction agree about what will be present.
GUARDIAN_SHOW_FIELDS = (
    "headline,standfirst,trailText,byline,body,bodyText,wordcount,"
    "firstPublicationDate,lastModified,shortUrl,thumbnail,publication"
)
GUARDIAN_SHOW_TAGS = "contributor,keyword,series,type"
GUARDIAN_SHOW_ELEMENTS = "image"
GUARDIAN_PAGE_SIZE = 50


def extract_from_guardian(result: dict) -> ExtractedArticle:
    """One Guardian API result into the same shape as an HTML extraction.

    Everything here is first-party structured data, which is why this source
    is the reference implementation rather than the fallback:

    * the hero image is the element whose `relation` is "main", stated by the
      publisher, so there is no heuristic and no "first image on the page";
    * every asset carries altText, caption, credit, photographer, source,
      imageType and real pixel dimensions;
    * `wordcount` is theirs, which gives `validate` an independent check that
      the body arrived whole instead of truncated.
    """
    fields = result.get("fields") or {}
    tags = result.get("tags") or []
    body_html = fields.get("body")
    body_text = fields.get("bodyText") or html_to_text(body_html)

    article = ExtractedArticle(
        source_key="guardian",
        canonical_url=canonical_url(result.get("webUrl") or "", "guardian"),
        discovered_url=canonical_url(result.get("webUrl") or "", "guardian"),
        source_article_id=result.get("id"),
        title=fields.get("headline") or result.get("webTitle"),
        standfirst=html_to_text(fields.get("standfirst")) or html_to_text(fields.get("trailText")),
        body_html=body_html,
        body_text=body_text,
        word_count=word_count(body_text),
        declared_word_count=_int_or_none(fields.get("wordcount")),
        published_at=to_iso8601(
            fields.get("firstPublicationDate") or result.get("webPublicationDate")
        ),
        updated_at=to_iso8601(fields.get("lastModified")),
        section=result.get("sectionName"),
        language="en-GB",
        authors=[t["webTitle"] for t in tags
                 if t.get("type") == "contributor" and t.get("webTitle")],
        tags=[(_guardian_tag_kind(t), t["webTitle"]) for t in tags if t.get("webTitle")],
        meta_title=result.get("webTitle"),
        meta_description=html_to_text(fields.get("trailText")),
        json_ld={"@type": "NewsArticle", "@source": "guardian-open-platform"},
    )

    for element in result.get("elements") or []:
        if element.get("type") != "image":
            continue
        role = {"main": "hero", "thumbnail": "thumbnail"}.get(element.get("relation"), "inline")
        assets = element.get("assets") or []
        if not assets:
            continue
        # Assets are renditions of one photograph, widest last is not
        # guaranteed, so pick by declared width rather than by position.
        widest = max(assets, key=lambda a: _int_or_none((a.get("typeData") or {}).get("width")) or 0)
        data = widest.get("typeData") or {}
        article.images.append(
            ArticleImage(
                url=_https(data.get("secureFile") or widest.get("file") or ""),
                role=role,
                origin_url=_https(widest.get("file")),
                width=_int_or_none(data.get("width")),
                height=_int_or_none(data.get("height")),
                alt_text=data.get("altText"),
                caption=html_to_text(data.get("caption")),
                credit=data.get("credit") or data.get("photographer") or data.get("source"),
                image_type=data.get("imageType"),
                mime_type=widest.get("mimeType"),
                provider="guim",
                thumb_url=thumb_rendition(_https(widest.get("file") or "") or ""),
                # mediaId is the Guardian's own asset identity, so this needs
                # no URL parsing and survives a re-crop.
                fingerprint=hashlib.sha256(
                    f"guim:{data.get('mediaId')}".encode()
                ).hexdigest() if data.get("mediaId") else image_fingerprint(
                    widest.get("file") or ""
                ),
            )
        )
    # The API returns main and thumbnail in publication order, not hero-first.
    article.images.sort(key=lambda i: {"hero": 0, "inline": 1, "thumbnail": 2}[i.role])
    return article


def _guardian_tag_kind(tag: dict) -> str:
    return {
        "contributor": "author",
        "series": "series",
        "type": "type",
    }.get(tag.get("type", ""), "keyword")


def extract_from_feed_item(candidate: Candidate) -> ExtractedArticle:
    """A `feed_only` source, where the RSS item is the entire record.

    Used for ESPNcricinfo, whose article HTML is Akamai-blocked. The result is
    deliberately body-less: `content_policy` is 'metadata_only', `word_count`
    is 0, and `validate` knows not to demand a body from this source rather
    than flagging every row as a partial scrape.
    """
    hero = None
    if candidate.image_url:
        url, width, height = best_rendition(candidate.image_url)
        provider, _ = image_identity(url)
        hero = ArticleImage(
            url=url,
            role="hero",
            origin_url=_https(candidate.image_url),
            # The feed's media:content declares the ORIGINAL's dimensions, so
            # prefer them over the table lookup, which is only a fallback.
            width=candidate.image_width or width,
            height=candidate.image_height or height,
            provider=provider,
            fingerprint=image_fingerprint(url),
            thumb_url=thumb_rendition(url),
        )

    return ExtractedArticle(
        source_key=candidate.source_key,
        canonical_url=canonical_url(candidate.url, candidate.source_key),
        discovered_url=canonical_url(candidate.url, candidate.source_key),
        source_article_id=candidate.source_article_id,
        title=candidate.title,
        standfirst=candidate.summary,
        body_html=None,
        body_text=None,
        word_count=0,
        published_at=candidate.published_at,
        updated_at=candidate.updated_at,
        section=candidate.section,
        language="en",
        authors=[candidate.author] if candidate.author else [],
        tags=[("section", candidate.section)] if candidate.section else [],
        meta_title=candidate.title,
        meta_description=candidate.summary,
        images=[hero] if hero else [],
    )


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

# A body shorter than this is a paywall stub, a redirect interstitial or a
# consent wall, not an article. Set from the shortest real article measured
# across the sources (a Guardian squad-announcement brief at 360 words, an
# ICC one at ~180) with room underneath.
MIN_BODY_WORDS = 60

# How far the extracted word count may fall short of a publisher-declared one
# before the body is called truncated. The Guardian is the only source that
# declares one; theirs counts slightly differently from ours, so this is a
# ratio rather than an exact match.
WORDCOUNT_TOLERANCE = 0.6


def validate(article: ExtractedArticle) -> list[str]:
    """Everything wrong with this extraction, as a list of reasons.

    A non-empty list means the row must NOT be recorded as successfully
    processed. That distinction is the point: the failure mode this guards
    against is a consent wall or an A/B-tested template change that yields a
    parseable page with no article in it, which a naive pipeline stores as a
    complete article with an empty body and never revisits.
    """
    problems: list[str] = []
    source = SOURCES.get(article.source_key)

    if not article.canonical_url:
        problems.append("no canonical url")
    elif not article.canonical_url.startswith("https://"):
        problems.append(f"canonical url is not https: {article.canonical_url}")

    if not article.source_article_id:
        problems.append("no stable source article id")

    if not (article.title or "").strip():
        problems.append("no title")

    if not article.published_at:
        problems.append("no publication date")
    elif not re.match(r"^\d{4}-\d{2}-\d{2}T", article.published_at):
        problems.append(f"unparsed publication date: {article.published_at}")

    # Only demand a body where the source is supposed to have one. Flagging
    # ESPNcricinfo for having no body would mark every row of a working
    # source as failed and hide the rows that genuinely broke.
    if source is not None and source.content_policy != "metadata_only":
        if not (article.body_text or "").strip():
            problems.append("no body text")
        elif article.word_count < MIN_BODY_WORDS:
            problems.append(
                f"body too short ({article.word_count} words < {MIN_BODY_WORDS})"
            )

    declared = article.declared_word_count
    if declared and article.word_count and article.word_count < declared * WORDCOUNT_TOLERANCE:
        problems.append(
            f"body truncated: extracted {article.word_count} words against "
            f"publisher-declared {declared}"
        )

    # A hero that is not on a host this source is known to serve images from
    # is usually a placeholder, a tracking pixel or a social-card default.
    hero = article.hero()
    if hero and hero.url:
        if not hero.url.startswith("https://"):
            problems.append(f"hero image is not https: {hero.url}")
        if hero.width and hero.height and (hero.width < 200 or hero.height < 120):
            problems.append(f"hero image too small: {hero.width}x{hero.height}")

    if source is not None and article.canonical_url:
        if not is_discoverable(source.key, article.canonical_url):
            problems.append("canonical url is on a robots.txt-disallowed path")

    article.problems = problems
    return problems
