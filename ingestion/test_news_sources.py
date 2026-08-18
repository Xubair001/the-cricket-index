"""Tests for the news extraction logic. Run directly:

    cd ingestion && python test_news_sources.py

Plain asserts and a tiny runner rather than pytest, because this repo has five
runtime dependencies and adding a test framework to run twenty assertions is a
worse trade than fifteen lines of harness. CI byte-compiles this file with the
rest of ingestion/, so a syntax error is caught there; the assertions run here.

Every fixture below is a REDUCTION of a real response captured from the live
source, not an invention. Where a test encodes a source quirk, the comment
names the observation it came from - the point of these is to fail if a
publisher changes shape, and a fixture nobody ever saw in the wild cannot do
that.
"""
import sys

import news_sources as ns

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILURES.append(name)


def eq(name: str, actual, expected) -> None:
    check(name, actual == expected, f"\n         got:      {actual!r}\n         expected: {expected!r}")


# ---------------------------------------------------------------------------
# Canonicalisation
# ---------------------------------------------------------------------------

def test_canonicalisation() -> None:
    print("canonicalisation")

    # ESPNcricinfo's RSS <link> is the <guid> plus a tracking parameter. Left
    # in, the same article files twice.
    eq("strips ex_cid tracking",
       ns.canonical_url("https://www.cricinfo.com/ci/content/story/1550496.html?ex_cid=OTC-RSS",
                        "espncricinfo"),
       "https://www.espncricinfo.com/ci/content/story/1550496.html")

    # cricinfo.com and espncricinfo.com are the same publisher, and their own
    # feed uses both hosts inside one <item>.
    eq("de-aliases cricinfo.com",
       ns.canonical_url("http://www.cricinfo.com/story/foo-123", "espncricinfo"),
       "https://www.espncricinfo.com/story/foo-123")

    eq("drops utm_* and fragments",
       ns.canonical_url("https://example.com/a/b/?utm_source=x&keep=1#frag"),
       "https://example.com/a/b?keep=1")

    eq("http upgraded, host lower-cased",
       ns.canonical_url("HTTP://WWW.Example.COM/Path"),
       "https://www.example.com/Path")

    # A path segment is never stripped as "noise": Sky's section id genuinely
    # differs between their feed and their canonical tag, and the fix for that
    # is the article id, not a guess about which digits matter.
    check("keeps path segments intact",
          ns.canonical_url("https://www.skysports.com/cricket/news/12040/13574220/slug")
          .endswith("/cricket/news/12040/13574220/slug"))


def test_article_ids() -> None:
    print("source article ids")

    # All three URL forms ESPNcricinfo uses for one story must give one id.
    for label, url in [
        ("modern slug", "https://www.espncricinfo.com/story/sl-vs-ind-chandimal-1550496"),
        ("legacy html", "https://www.cricinfo.com/ci/content/story/1550496.html"),
        ("with tracking", "https://www.cricinfo.com/ci/content/story/1550496.html?ex_cid=OTC-RSS"),
    ]:
        eq(f"espncricinfo id from {label}",
           ns.source_article_id("espncricinfo", url), "1550496")

    # THE Sky case: their RSS links section 12040, their rel=canonical says
    # 12175, and the article id 13574220 is the same in both. Keying on the
    # URL would file this article twice.
    for section in ("12040", "12175"):
        eq(f"sky id survives section {section}",
           ns.source_article_id(
               "skysports",
               f"https://www.skysports.com/cricket/news/{section}/13574220/aus-v-ban"),
           "13574220")
    # Their canonical tag also drops the section entirely on some articles,
    # and moves The Hundred to its own top-level section.
    eq("sky id with no section segment",
       ns.source_article_id("skysports",
                            "https://www.skysports.com/cricket/news/13508419/aus-t20-exit"),
       "13508419")
    eq("sky id under /the-hundred/",
       ns.source_article_id(
           "skysports",
           "https://www.skysports.com/the-hundred/news/36888/13572600/awards"),
       "13572600")

    eq("icc id is the slug",
       ns.source_article_id("icc",
                            "https://www.icc-cricket.com/news/opener-left-out-second-test"),
       "opener-left-out-second-test")


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def test_dates() -> None:
    print("date parsing")
    eq("RFC 822 GMT", ns.to_iso8601("Tue, 18 Aug 2026 06:20:38 GMT"),
       "2026-08-18T06:20:38Z")

    # Sky stamps every summer pubDate BST. %Z cannot parse it portably, so a
    # naive parse files a 07:00 BST story an hour early in UTC terms.
    eq("RFC 822 BST is converted, not ignored",
       ns.to_iso8601("Tue, 18 Aug 2026 07:00:00 BST"), "2026-08-18T06:00:00Z")

    eq("numeric offset", ns.to_iso8601("Mon, 17 Aug 2026 14:38:15 +0530"),
       "2026-08-17T09:08:15Z")
    # The ICC's JSON-LD is millisecond-precision with a Z.
    eq("ISO with milliseconds", ns.to_iso8601("2026-08-18T03:08:47.454Z"),
       "2026-08-18T03:08:47Z")
    eq("sitemap bare date", ns.to_iso8601("2026-08-18"), "2026-08-18T00:00:00Z")
    # Never guess: a wrong publication date reorders the whole feed.
    eq("unparseable is None", ns.to_iso8601("last Tuesday"), None)
    eq("empty is None", ns.to_iso8601(""), None)


# ---------------------------------------------------------------------------
# Feed parsing
# ---------------------------------------------------------------------------

ESPN_RSS = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel><title>Cricket news from Cricinfo.com</title>
<item>
  <title>Chandimal taken to hospital for precautionary scan</title>
  <description>He hurt himself while fielding on the leg-side boundary</description>
  <coverImages>https://p.imgci.com/db/PICTURES/CMS/421300/421335.5.jpg</coverImages>
  <media:content medium="image" url="http://p.imgci.com/db/PICTURES/CMS/421300/421335.jpg"
                 width="1400" height="933" />
  <link>https://www.cricinfo.com/ci/content/story/1550496.html?ex_cid=OTC-RSS</link>
  <guid>https://www.cricinfo.com/ci/content/story/1550496.html</guid>
  <url>https://www.cricinfo.com/story/sl-vs-ind-chandimal-taken-to-hospital-1550496</url>
  <pubDate>Tue, 18 Aug 2026 06:20:38 GMT</pubDate>
</item></channel></rss>"""


def test_rss() -> None:
    print("rss parsing")
    items = ns.parse_rss(ESPN_RSS, "espncricinfo")
    eq("one item", len(items), 1)
    item = items[0]

    # <url> is a NON-STANDARD element carrying the modern slug URL. A
    # standards-only feed reader takes <link> and gets the legacy form with
    # tracking attached, which is why this parser is hand-written.
    check("prefers the non-standard <url> over <link>",
          item.url.endswith("/story/sl-vs-ind-chandimal-taken-to-hospital-1550496"))

    # media:content is the ORIGINAL (1400x933); coverImages is a 365x205 crop.
    check("takes media:content over coverImages", "421335.jpg" in item.image_url)
    eq("declared width", item.image_width, 1400)
    eq("declared height", item.image_height, 933)
    # Feeds still emit http:// image URLs; left alone they are blocked as
    # mixed content or cost a redirect on every render.
    check("image url upgraded to https", item.image_url.startswith("https://"))
    eq("published", item.published_at, "2026-08-18T06:20:38Z")
    eq("id from guid", item.source_article_id, "1550496")


SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
<url>
  <loc>https://www.icc-cricket.com/news/cox-carrying-kohli-s-advice</loc>
  <news:news>
    <news:publication><news:name>ICC</news:name><news:language>en</news:language></news:publication>
    <news:publication_date>2026-08-18T05:19:52+00:00</news:publication_date>
    <news:title>Cox carrying Kohli's advice into Pakistan Test series</news:title>
  </news:news>
  <image:image>
    <image:loc>https://images.icc-cricket.com/image/upload/t_ratio1_1-size20/prd/e3aafsnhjv5lcqwaw5sa</image:loc>
  </image:image>
</url></urlset>"""

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://www.icc-cricket.com/sitemap-article.xml</loc></sitemap>
<sitemap><loc>https://www.icc-cricket.com/sitemap/tournament-12672/sitemap-article.xml</loc></sitemap>
<sitemap><loc>https://www.icc-cricket.com/sitemap/tournament-12672/sitemap-article.xml</loc></sitemap>
</sitemapindex>"""


def test_sitemap() -> None:
    print("sitemap parsing")
    items, children = ns.parse_sitemap(SITEMAP, "icc")
    eq("no children in a urlset", children, [])
    eq("one url", len(items), 1)
    # A Google News sitemap gives an exact timestamp without fetching the
    # page, which is what makes incremental sync cheap for a source with no RSS.
    eq("news publication_date", items[0].published_at, "2026-08-18T05:19:52Z")
    eq("news title", items[0].title, "Cox carrying Kohli's advice into Pakistan Test series")

    items, children = ns.parse_sitemap(SITEMAP_INDEX, "icc")
    eq("index yields no articles", items, [])
    # The ICC's real index lists tournament-12672 twice.
    eq("index de-duplicates children", len(children), 2)


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

def test_images() -> None:
    print("image identity and renditions")

    # One photograph across four ESPNcricinfo renditions is ONE asset.
    base = "https://p.imgci.com/db/PICTURES/CMS/421300/421335"
    prints = {ns.image_fingerprint(f"{base}{v}.jpg") for v in ("", ".1", ".5", ".6")}
    eq("all imgci renditions share one fingerprint", len(prints), 1)

    upgraded, w, h = ns.best_rendition(f"{base}.5.jpg")
    eq("imgci upgrades to the original", upgraded, f"{base}.jpg")
    eq("imgci original dimensions", (w, h), (1400, 933))

    # The bucket is id // 100 * 100, so it is derivable rather than parsed.
    up2, _, _ = ns.best_rendition("https://p.imgci.com/db/PICTURES/CMS/999900/999999.2.jpg")
    eq("imgci bucket derived from the id",
       up2, "https://p.imgci.com/db/PICTURES/CMS/999900/999999.jpg")

    # Sky serves one asset from several host shards at several sizes; only the
    # trailing id is stable.
    a = ns.image_fingerprint("https://e1.365dm.com/26/08/1920x1080/skysports-aus-ban_7322178.jpg")
    b = ns.image_fingerprint("https://e0.365dm.com/26/08/1600x900/skysports-aus-ban_7322178.jpg?20260815")
    eq("365dm shard and size do not change identity", a, b)
    up3, w3, h3 = ns.best_rendition("https://e0.365dm.com/26/08/1600x900/skysports-aus-ban_7322178.jpg")
    check("365dm upgraded to 1920x1080", "1920x1080" in up3 and (w3, h3) == (1920, 1080))

    # ICC is Cloudinary with STRICT transformations: an arbitrary w_1600,c_fill
    # returns HTTP 401, so an upgrade may only use a transform observed live.
    icc_small = ("https://images.icc-cricket.com/image/upload/"
                 "t_ratio16_9-size20-webp/prd/g2zsrwwr45ynqldhxab5")
    icc_square = ("https://images.icc-cricket.com/image/upload/"
                  "t_ratio1_1-size20/prd/g2zsrwwr45ynqldhxab5")
    eq("cloudinary transform is not part of identity",
       ns.image_fingerprint(icc_small), ns.image_fingerprint(icc_square))
    up4, _, _ = ns.best_rendition(icc_small)
    check("cloudinary upgraded only to a verified named transform",
          up4.split("/upload/")[1].split("/")[0] in ns.ICC_NAMED_TRANSFORMS,
          f"got {up4}")
    check("cloudinary size20 upgraded to size50", "size50" in up4, f"got {up4}")

    # An unknown CDN is left alone rather than rewritten on a guess.
    unknown = "https://cdn.example.org/photo.jpg"
    up5, w5, h5 = ns.best_rendition(unknown)
    eq("unknown cdn untouched", (up5, w5, h5), (unknown, None, None))

    # Thumbnails: a list row must not pull the original. Every width below was
    # requested against the live origin, because two of these CDNs whitelist
    # their sizes and a computed one is an error page.
    eq("imgci thumbnail variant",
       ns.thumb_rendition(f"{base}.jpg"), f"{base}.2.jpg")
    check("365dm thumbnail",
          ns.thumb_rendition("https://e0.365dm.com/26/08/1920x1080/skysports-a_7322178.jpg")
          == "https://e0.365dm.com/26/08/384x216/skysports-a_7322178.jpg")
    check("cloudinary thumbnail uses a named transform",
          (ns.thumb_rendition(icc_small) or "").split("/upload/")[1].split("/")[0]
          in ns.ICC_NAMED_TRANSFORMS)
    # media.guim.co.uk serves /140 and /500 and returns HTTP 403 for /300, so
    # the width comes from the verified constant rather than from arithmetic.
    eq("guim thumbnail uses a whitelisted width",
       ns.thumb_rendition(
           "https://media.guim.co.uk/4e1086f9a88ae3633f087e705b8fa310b6086de7/688_0_6880_5504/1000.jpg"),
       "https://media.guim.co.uk/4e1086f9a88ae3633f087e705b8fa310b6086de7/688_0_6880_5504/500.jpg")
    # None, not the original: a caller that gets None knows to fall back,
    # whereas returning the full image would silently reintroduce the weight.
    eq("unknown cdn has no thumbnail", ns.thumb_rendition(unknown), None)


def test_hero_selection() -> None:
    print("hero image selection")
    meta = {"og:image": ["https://images.icc-cricket.com/image/upload/"
                         "t_ratio16_9-size20-webp/prd/abc123"]}
    ld = {"image": {"url": "https://images.icc-cricket.com/image/upload/"
                           "t_ratio1_1-size20/prd/abc123",
                    "caption": "GettyImages-2290027806"}}
    hero = ns.hero_image_from_meta(meta, ld, fallback="https://cdn.example.org/wrong.jpg")
    check("og:image beats the JSON-LD image and the feed fallback",
          "abc123" in hero.url and "example.org" not in hero.url)
    # The ICC's JSON-LD "caption" is the Getty filename, which is provenance.
    eq("caption carried from JSON-LD", hero.caption, "GettyImages-2290027806")
    eq("role", hero.role, "hero")

    # Nothing anywhere means no hero, not a placeholder.
    eq("no image sources gives None", ns.hero_image_from_meta({}, {}, None), None)


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------

ICC_HTML = """<html lang="en"><head>
<title>Opener left out as Australia reveal squad | ICC World Test Championship | ICC</title>
<link rel="canonical" href="https://www.icc-cricket.com/news/opener-left-out"/>
<meta property="og:title" content="Opener left out as Australia reveal squad"/>
<meta property="og:image" content="https://images.icc-cricket.com/image/upload/t_ratio16_9-size20-webp/prd/g2zs"/>
<meta property="article:published_time" content="2026-08-18T03:08:47.454Z"/>
<meta property="article:author" content="Jonathan Healy"/>
<meta property="article:tag" content="ICC World Test Championship"/>
<meta property="article:tag" content="Matt Renshaw 03/28/1996"/>
</head><body>
<script type="application/ld+json">{"@type":"Organization","name":"ICC"}</script>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"NewsArticle",
"headline":"Opener left out as Australia reveal squad for second Test",
"creator":"ICC","datePublished":"2026-08-18T03:08:47.454Z",
"dateModified":"2026-08-18T04:39:51.786Z","articleSection":"News",
"articleBody":"<p>Australia have made one change to their squad for the second and final ICC World Test Championship fixture against Bangladesh in Mackay. Opener Jake Weatherald has been dropped from the 13-player squad, with left-hander Matthew Renshaw named as his replacement after a strong domestic season. The selectors said the change was about stabilising a top order that has struggled for consistency across the past twelve months of international cricket, and that Renshaw had earned his recall on weight of runs alone.</p>"}</script>
</body></html>"""


def test_html_extraction() -> None:
    print("html extraction")
    article = ns.extract_from_html(
        ICC_HTML, ns.Candidate(source_key="icc", url="https://www.icc-cricket.com/news/opener-left-out?utm_source=x")
    )
    eq("canonical from rel=canonical, not the arrival url",
       article.canonical_url, "https://www.icc-cricket.com/news/opener-left-out")

    # THE ICC author quirk: JSON-LD creator is the organisation, article:author
    # is the journalist. Reading JSON-LD first credits every ICC piece to "ICC"
    # and loses every byline in the archive.
    eq("author from OpenGraph, not JSON-LD creator", article.authors, ["Jonathan Healy"])

    # Three ld+json blocks ship on a real ICC page (NewsArticle, Organization,
    # WebSite). Taking the first would pick Organization here.
    check("selects the NewsArticle block, not the first one",
          article.title == "Opener left out as Australia reveal squad for second Test")

    eq("published", article.published_at, "2026-08-18T03:08:47Z")
    eq("updated", article.updated_at, "2026-08-18T04:39:51Z")
    eq("section", article.section, "News")
    check("body extracted from articleBody", (article.word_count or 0) > 60)
    check("body html stripped to text", "<p>" not in (article.body_text or ""))

    # article:tag repeats, one per entity. Collapsing to the last value would
    # throw away every tag but one.
    kinds = dict((v, k) for k, v in article.tags)
    eq("person tag classified as an entity", kinds.get("Matt Renshaw 03/28/1996"), "entity")
    eq("competition tag stays a keyword", kinds.get("ICC World Test Championship"), "keyword")

    # The DOB in the tag is the strongest entity-linking signal any source gives.
    eq("person tag split", ns.split_person_tag("Matt Renshaw 03/28/1996"),
       ("Matt Renshaw", "1996-03-28"))

    check("hero found", article.hero() is not None)
    eq("no validation problems", ns.validate(article), [])

    # <title> carries a site-name tail; og:title and the JSON-LD headline do not.
    check("meta_title keeps the raw <title>", "| ICC" in (article.meta_title or ""))
    check("title does not", "| ICC" not in (article.title or ""))


def test_validation() -> None:
    print("validation")

    def article(**kw):
        base = dict(
            source_key="icc",
            canonical_url="https://www.icc-cricket.com/news/x",
            discovered_url="https://www.icc-cricket.com/news/x",
            source_article_id="x", title="A title",
            body_text=" ".join(["word"] * 200), word_count=200,
            published_at="2026-08-18T00:00:00Z",
        )
        base.update(kw)
        return ns.ExtractedArticle(**base)

    eq("a complete article passes", ns.validate(article()), [])

    # The failure this guards against: a consent wall or a template change
    # that yields a parseable page with no article in it, which a naive
    # pipeline stores as complete and never revisits.
    check("empty body rejected", "no body text" in ns.validate(article(body_text="", word_count=0)))
    check("stub body rejected",
          any("too short" in p for p in ns.validate(article(body_text="a b c", word_count=3))))
    check("missing date rejected", "no publication date" in ns.validate(article(published_at=None)))
    check("missing title rejected", "no title" in ns.validate(article(title="")))

    # A metadata_only source has no body by design. Demanding one would mark
    # every row of a working source failed and hide the ones that broke.
    meta_only = ns.ExtractedArticle(
        source_key="espncricinfo",
        canonical_url="https://www.espncricinfo.com/story/x-1", discovered_url="",
        source_article_id="1", title="A headline", published_at="2026-08-18T00:00:00Z",
    )
    eq("metadata_only source is not asked for a body", ns.validate(meta_only), [])

    # The Guardian states its own word count; ours falling far short means the
    # body was truncated even though it parsed.
    truncated = article(word_count=40, body_text=" ".join(["w"] * 40), declared_word_count=1000)
    check("truncation against a declared count is caught",
          any("truncated" in p for p in ns.validate(truncated)))

    # robots.txt is enforced, not merely documented.
    blocked = article(canonical_url="https://www.icc-cricket.com/news/icc-acu-workshop-2025")
    check("robots-disallowed path rejected",
          any("robots" in p for p in ns.validate(blocked)))


# Article-length bodies, because SimHash distance is length-sensitive and a
# 60-word fixture measures shingle noise rather than the thing under test.
# The real archive's median body is 574 words.
_SYNDICATED_BODY = (
    "Australia have dropped opener Jake Weatherald after their shock home loss to "
    "Bangladesh but retained Marnus Labuschagne for the must-win second Test in "
    "Mackay beginning on Saturday, where the hosts will look to level the series "
    "after a humbling nine wicket defeat in Darwin that put real pressure on the "
    "national selectors to overhaul an ageing batting line up. Weatherald was out "
    "for twenty three in the first innings and did not score in the second innings "
    "of his hometown Test, leaving him averaging twenty point three six across his "
    "twelve Test innings with a single half century to his name. Renshaw returns "
    "having scored heavily in domestic cricket through the winter, and the chair of "
    "selectors said the squad had been chosen to give the top order the stability it "
    "has lacked since the retirement of two long serving batters. Bangladesh, who "
    "recorded their first ever Test win on Australian soil in Darwin, named an "
    "unchanged squad and will look to their seamers again on a surface expected to "
    "offer early movement. The match begins on Saturday and is the final fixture of "
    "the current World Test Championship cycle for both sides."
) * 2

_INDEPENDENT_BODY = (
    "Jake Weatherald has paid the price for an underwhelming performance in "
    "Australia's shock Test defeat to Bangladesh, with Matthew Renshaw drafted "
    "into a thirteen man squad to replace the opener for the second and final "
    "match of a series the hosts must now win to avoid an embarrassing whitewash "
    "on home soil against a side ranked well below them. The selection panel "
    "resisted wider surgery despite calls for it, keeping faith with a middle "
    "order that has been under scrutiny for the better part of a year. Renshaw "
    "last played a Test three years ago and has spent the intervening seasons "
    "accumulating runs in the Sheffield Shield, where his conversion rate has "
    "been among the best in the competition. The captain defended the group after "
    "the Darwin loss, arguing that conditions had been unusually helpful to the "
    "visiting attack and that the batting failures were a matter of application "
    "rather than technique. Bangladesh arrive in Mackay with the series in their "
    "hands and a genuine chance of a result nobody predicted."
) * 2


def test_syndication() -> None:
    print("syndication detection")
    original = ns.simhash(_SYNDICATED_BODY)

    # A syndication is the same body with house-style edits, curly quotes and
    # a different byline. It must still match.
    reprint = ns.simhash(
        _SYNDICATED_BODY.replace("shock home loss", "shock home defeat")
                        .replace("must-win", "must win")
                        .replace("said", "stated")
                        .replace("'", "\u2019")
    )
    distance = ns.syndication_distance(original, reprint)
    check("house-style edits still match",
          distance <= ns.SYNDICATION_MAX_DISTANCE, f"distance {distance}")

    # A syndicator commonly drops the closing paragraphs. Measured median
    # distance for a 90%-kept body is 6, inside the threshold.
    words = _SYNDICATED_BODY.split()
    trimmed = ns.simhash(" ".join(words[: int(len(words) * 0.9)]))
    distance = ns.syndication_distance(original, trimmed)
    check("truncated republication still matches",
          distance <= ns.SYNDICATION_MAX_DISTANCE, f"distance {distance}")

    # ...and three publishers covering one event independently must NOT.
    # Collapsing those would delete two mastheads' work and misreport how
    # widely a story was covered. Measured floor for that class is 22 bits.
    different = ns.simhash(_INDEPENDENT_BODY)
    distance = ns.syndication_distance(original, different)
    check("independent coverage of one event does NOT match",
          distance > ns.SYNDICATION_MAX_DISTANCE, f"distance {distance}")
    check("and does so with real margin, not by a bit or two",
          distance >= ns.SYNDICATION_MAX_DISTANCE * 2, f"distance {distance}")

    # Too short to hash is 0, and 0 must never compare equal to anything.
    eq("short text gives no hash", ns.simhash("three words only"), 0)
    eq("unusable hashes are maximally distant",
       ns.syndication_distance(0, original), 64)


def test_registry() -> None:
    print("source registry")
    # The BBC is registered and OFF. Left visible so the exclusion is a
    # reviewable decision rather than a silent absence.
    check("bbc registered but disabled", not ns.SOURCES["bbcsport"].enabled)
    check("bbc exclusion states the reason",
          "robots.txt" in ns.SOURCES["bbcsport"].policy_note)
    check("cricbuzz disabled", not ns.SOURCES["cricbuzz"].enabled)
    eq("four sources enabled", len(ns.enabled_sources()), 4)

    for source in ns.SOURCES.values():
        check(f"{source.key} declares a rate floor", source.min_interval_seconds > 0)
        check(f"{source.key} explains its policy", len(source.policy_note) > 40)

    # robots.txt enforcement, from the ICC's own disallow list.
    check("icc integrity path disallowed",
          not ns.is_discoverable("icc", "https://www.icc-cricket.com/news/icc-acu-workshop-2025"))
    check("ordinary icc path allowed",
          ns.is_discoverable("icc", "https://www.icc-cricket.com/news/some-match-report"))
    check("sky /api/ disallowed",
          not ns.is_discoverable("skysports", "https://www.skysports.com/api/thing"))

    # Scope is a SEPARATE question from robots, and the ledger records them
    # separately. Sky's cricket feeds carry podcast and video entries whose
    # pages have a 12-word body; fetching and then failing those would bury
    # real extraction breakage under things we never wanted.
    check("sky article path in scope",
          ns.is_in_scope("skysports",
                         "https://www.skysports.com/cricket/news/12175/13574220/slug"))
    check("sky video out of scope",
          not ns.is_in_scope("skysports",
                             "https://www.skysports.com/watch/cricket-video/1/2/clip"))
    check("sky football out of scope",
          not ns.is_in_scope("skysports", "https://www.skysports.com/football/news/1/2/x"))
    check("sky section-less canonical in scope",
          ns.is_in_scope("skysports",
                         "https://www.skysports.com/cricket/news/13508419/aus-t20-exit"))
    check("sky the-hundred in scope",
          ns.is_in_scope("skysports",
                         "https://www.skysports.com/the-hundred/news/36888/13572600/awards"))
    check("sky live blog out of scope",
          not ns.is_in_scope("skysports",
                             "https://www.skysports.com/cricket/live-blog/12123/13574000/x"))
    check("espncricinfo both url forms in scope",
          ns.is_in_scope("espncricinfo", "https://www.espncricinfo.com/story/slug-1550496")
          and ns.is_in_scope("espncricinfo",
                             "https://www.espncricinfo.com/ci/content/story/1550496.html"))
    check("espncricinfo video out of scope",
          not ns.is_in_scope("espncricinfo", "https://www.espncricinfo.com/video/foo-999"))
    check("icc photo gallery out of scope",
          not ns.is_in_scope("icc", "https://www.icc-cricket.com/photos/gallery"))
    # All three ICC article families. Allowing only /news/ would have dropped
    # 293 of 378 real articles measured in the live archive.
    check("icc media release in scope",
          ns.is_in_scope("icc", "https://www.icc-cricket.com/media-releases/thaker-fined"))
    check("icc tournament news in scope",
          ns.is_in_scope(
              "icc",
              "https://www.icc-cricket.com/tournaments/icc-cricket-world-cup-2027/news/miller-aiming-high"))
    check("icc tournament landing page out of scope",
          not ns.is_in_scope(
              "icc", "https://www.icc-cricket.com/tournaments/icc-cricket-world-cup-2027"))
    check("a source with no pattern admits everything",
          ns.is_in_scope("guardian", "https://www.theguardian.com/anything/at/all"))


def test_gender_inference() -> None:
    """Lives here rather than in a second file: one test entry point is worth
    more than keeping the module names aligned. Imported lazily so a missing
    temporalio never stops the pure-extraction tests above from running."""
    print("gender inference")
    from news_activities import _infer_gender

    # THE case this rule exists for. A body-only scan filed both of these as
    # women's cricket, because a report of the MEN'S Hundred final mentions the
    # women's final in the same breath.
    eq("men's final by its headline",
       _infer_gender(
           "Seifert demolition job sets up Manchester Super Giants for maiden men's Hundred title",
           "Manchester Super Giants beat Trent Rockets in the men's final"),
       "male")
    eq("a headline naming neither, body naming both, stays undetermined",
       _infer_gender(
           "The Hundred: Tim Seifert propels Manchester Super Giants to title",
           "Rockets miss out on a clean sweep of men's and women's titles"),
       None)

    eq("women's from the headline",
       _infer_gender("Charlie Dean to captain England Women against Ireland", "..."),
       "female")
    eq("women's from the body when the headline is silent",
       _infer_gender("'Another step forward' as Perry hails T20 World Cup success",
                     "Ellyse Perry has hailed the ICC Women's T20 World Cup"),
       "female")
    eq("nothing established gives None, never a guess",
       _infer_gender("Australia reveal squad for second Test", "Weatherald dropped"),
       None)

    # "men" cannot match inside "women": the 'o' before 'm' is a word
    # character, so the word boundary fails. The two patterns are only safe to
    # test independently because of that.
    eq("'women' does not read as 'men'",
       _infer_gender("Women's Ashes squad named", "The squad for the Women's Ashes"),
       "female")


def test_extractor_version_in_hash() -> None:
    print("extractor version")
    payload = {"title": "x", "body_text": "y"}
    before = ns.content_hash(payload)
    original = ns.EXTRACTOR_VERSION
    try:
        ns.EXTRACTOR_VERSION = original + 1
        after = ns.content_hash(payload)
    finally:
        ns.EXTRACTOR_VERSION = original
    # Without this, fixing the extractor and re-running skips every article
    # and reports success. Exactly the trap PARSER_VERSION exists for.
    check("bumping the extractor version changes the content hash", before != after)


def main() -> int:
    for test in (
        test_canonicalisation, test_article_ids, test_dates, test_rss,
        test_sitemap, test_images, test_hero_selection, test_html_extraction,
        test_validation, test_syndication, test_registry,
        test_gender_inference, test_extractor_version_in_hash,
    ):
        test()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
