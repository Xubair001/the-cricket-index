"""Check the news archive against the things that are supposed to be true of it.

Not a unit test: ingestion/test_news_sources.py covers the extraction logic in
isolation against fixtures. This checks the LIVE archive, which is where the
failures that matter actually show up - a publisher changing template, a feed
quietly going stale, a canonical rule that stopped collapsing duplicates.

    cd backend && python -m scripts.validate_news [--strict]

Modelled on the reconciliation the deliveries backfill runs (CLAUDE.md: "the
two tables must reconcile"). Exit code is non-zero under --strict if any check
fails, so it can gate a deploy.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.database import SessionLocal

# The scope rules are the ingestion side's, and importing them rather than
# restating them here is what stops the validator drifting from the pipeline
# it validates.
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "ingestion")
)
import news_sources  # noqa: E402

FAILURES: list[str] = []
WARNINGS: list[str] = []


def report(name: str, ok: bool, detail: str = "", warn_only: bool = False) -> None:
    if ok:
        print(f"  ok    {name}{(' - ' + detail) if detail else ''}")
    elif warn_only:
        print(f"  warn  {name} - {detail}")
        WARNINGS.append(name)
    else:
        print(f"  FAIL  {name} - {detail}")
        FAILURES.append(name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero when a check fails")
    parser.add_argument("--stale-hours", type=int, default=48,
                        help="how old the newest article may be before a source "
                             "counts as stale")
    parser.add_argument("--prune-out-of-scope", action="store_true",
                        help="delete stored articles whose path is no longer in "
                             "scope for their source, and mark their ledger rows "
                             "skipped. Use after narrowing or correcting a "
                             "source's feeds or article_path.")
    args = parser.parse_args()
    db = SessionLocal()

    def scalar(sql: str, **params):
        return db.execute(text(sql), params).scalar_one()

    total = scalar("SELECT COUNT(*) FROM news_articles")
    print(f"news archive: {total} articles\n")
    if total == 0:
        print("nothing ingested; run `cd ingestion && python starter.py news` first")
        return 1

    # -- Scope -------------------------------------------------------------
    # An article outside its source's article_path is residue from a feed or
    # pattern that has since been corrected: Sky's feed 12040 turned out to be
    # their all-sport news feed, so 15 football, F1 and tennis pieces landed
    # in a cricket archive. Reported always, removed only when asked.
    print("scope")
    out_of_scope = [
        r for r in db.execute(text(
            "SELECT article_id, source_key, canonical_url, title FROM news_articles"
        )).all()
        if not news_sources.is_in_scope(r.source_key, r.canonical_url)
    ]
    if out_of_scope and args.prune_out_of_scope:
        ids = [r.article_id for r in out_of_scope]
        marks = ",".join(str(int(i)) for i in ids)
        # The ledger row keeps its URL and becomes 'skipped', so discovery
        # does not simply re-queue what was just removed.
        db.execute(text(
            f"""UPDATE news_ingestions
                SET status = 'skipped', article_id = NULL,
                    last_error = 'out of scope for this source'
                WHERE article_id IN ({marks})"""
        ))
        # Satellites are ON DELETE CASCADE, so the article row is enough.
        db.execute(text(f"DELETE FROM news_articles WHERE article_id IN ({marks})"))
        db.commit()
        print(f"  pruned {len(ids)} out-of-scope articles")
        out_of_scope = []
        total = scalar("SELECT COUNT(*) FROM news_articles")
    by_source = Counter(r.source_key for r in out_of_scope)
    report("every stored article is in scope for its source", not out_of_scope,
           f"{len(out_of_scope)} are not {dict(by_source)}; "
           f"re-run with --prune-out-of-scope to remove them")

    # -- Correct article ---------------------------------------------------
    print("correct article")
    report("every article has a title",
           scalar("SELECT COUNT(*) FROM news_articles WHERE title IS NULL OR title = ''") == 0,
           "")
    empty_id = scalar("SELECT COUNT(*) FROM news_articles WHERE source_article_id IS NULL")
    report("every article has its publisher's own id", empty_id == 0,
           f"{empty_id} without one")

    # A 'full' or 'extract' publisher storing a body-less article means the
    # extractor silently accepted a consent wall.
    bodyless = scalar(
        """SELECT COUNT(*) FROM news_articles a
           JOIN news_publishers p ON p.publisher_id = a.publisher_id
           WHERE p.content_policy != 'metadata_only'
             AND (a.body_text IS NULL OR a.word_count < 60)"""
    )
    report("no body-less article from a body-bearing source", bodyless == 0,
           f"{bodyless} articles")

    # -- Canonical URL -----------------------------------------------------
    print("\ncanonical url")
    non_https = scalar("SELECT COUNT(*) FROM news_articles WHERE canonical_url NOT LIKE 'https://%'")
    report("all canonical urls are https", non_https == 0, f"{non_https} are not")

    tracked = scalar(
        """SELECT COUNT(*) FROM news_articles
           WHERE canonical_url LIKE '%utm_%' OR canonical_url LIKE '%ex_cid%'
              OR canonical_url LIKE '%at_medium%' OR canonical_url LIKE '%#%'"""
    )
    report("no tracking parameters survived canonicalisation", tracked == 0,
           f"{tracked} still carry one")

    # The real duplicate test: two rows for one publisher article id.
    dupes = db.execute(text(
        """SELECT source_key, source_article_id, COUNT(*) n FROM news_articles
           WHERE source_article_id IS NOT NULL
           GROUP BY 1, 2 HAVING n > 1 ORDER BY n DESC LIMIT 5"""
    )).all()
    report("no article stored twice under one publisher id", not dupes,
           "; ".join(f"{d.source_key}/{d.source_article_id} x{d.n}" for d in dupes))

    # ...and the weaker one, which should also hold.
    url_dupes = scalar(
        """SELECT COUNT(*) FROM (SELECT url_fingerprint FROM news_articles
                                 GROUP BY 1 HAVING COUNT(*) > 1)"""
    )
    report("url fingerprint is unique", url_dupes == 0, f"{url_dupes} collisions")

    # -- Publication date --------------------------------------------------
    print("\npublication date")
    no_date = scalar("SELECT COUNT(*) FROM news_articles WHERE published_at IS NULL")
    report("every article has a publication date", no_date == 0, f"{no_date} without")

    unparsed = scalar(
        r"""SELECT COUNT(*) FROM news_articles
            WHERE published_at IS NOT NULL
              AND published_at NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T*'"""
    )
    report("every date is ISO-8601", unparsed == 0, f"{unparsed} are not")

    now = datetime.now(timezone.utc)
    future = scalar(
        "SELECT COUNT(*) FROM news_articles WHERE published_at > :t",
        t=(now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    # A handful of embargoed or scheduled pieces is normal; a pile of them
    # means a timezone was mishandled.
    report("no articles dated far in the future", future == 0,
           f"{future} are", warn_only=future < 5)

    # A date that ignored a BST offset lands exactly one hour out; that is
    # invisible per-row, so the check is that the newest article is not older
    # than the feed window.
    for row in db.execute(text(
        """SELECT source_key, MAX(published_at) latest, COUNT(*) n
           FROM news_articles GROUP BY 1 ORDER BY 1"""
    )).all():
        try:
            age = now - datetime.fromisoformat(row.latest.replace("Z", "+00:00"))
            fresh = age < timedelta(hours=args.stale_hours)
            report(f"{row.source_key} is current", fresh,
                   f"newest article is {age.total_seconds() / 3600:.0f}h old "
                   f"({row.n} articles)", warn_only=True)
        except (AttributeError, ValueError):
            report(f"{row.source_key} has a parseable newest date", False, str(row.latest))

    # -- Primary image -----------------------------------------------------
    print("\nprimary image")
    with_hero = scalar(
        "SELECT COUNT(DISTINCT article_id) FROM news_article_images WHERE role = 'hero'"
    )
    coverage = with_hero / total
    report("hero image coverage", coverage > 0.5,
           f"{with_hero}/{total} ({coverage:.0%})", warn_only=coverage > 0.3)

    two_heroes = scalar(
        """SELECT COUNT(*) FROM (SELECT article_id FROM news_article_images
                                 WHERE role = 'hero' GROUP BY 1 HAVING COUNT(*) > 1)"""
    )
    report("at most one hero per article", two_heroes == 0, f"{two_heroes} have more")

    non_https_img = scalar("SELECT COUNT(*) FROM news_images WHERE cdn_url NOT LIKE 'https://%'")
    report("all image urls are https", non_https_img == 0, f"{non_https_img} are not")

    tiny = scalar(
        "SELECT COUNT(*) FROM news_images WHERE width IS NOT NULL AND width < 200"
    )
    report("no hero is a tracking pixel or icon", tiny == 0, f"{tiny} under 200px wide")

    # The bug this catches: the Guardian ships one asset as both the main
    # element (1000px) and the thumbnail (500px), and an upsert taking the
    # last write stored every hero at the thumbnail size.
    downgraded = db.execute(text(
        """SELECT COUNT(*) FROM news_images i
           WHERE EXISTS (SELECT 1 FROM news_article_images ai
                         WHERE ai.image_id = i.image_id AND ai.role = 'hero')
             AND EXISTS (SELECT 1 FROM news_article_images ai2
                         WHERE ai2.image_id = i.image_id AND ai2.role = 'thumbnail')
             AND i.width IS NOT NULL AND i.width <= 500"""
    )).scalar_one()
    report("hero assets kept their largest rendition", downgraded == 0,
           f"{downgraded} heroes stored at thumbnail size", warn_only=True)

    # -- Structured metadata ----------------------------------------------
    print("\nstructured metadata")
    missing_meta = scalar(
        """SELECT COUNT(*) FROM news_articles a
           WHERE NOT EXISTS (SELECT 1 FROM news_article_metadata m
                             WHERE m.article_id = a.article_id)"""
    )
    report("every article has a metadata row", missing_meta == 0, f"{missing_meta} without")

    authored = scalar(
        """SELECT COUNT(DISTINCT article_id) FROM news_article_authors"""
    )
    report("byline coverage", True, f"{authored}/{total} ({authored / total:.0%})")

    # -- Duplicates and syndication ---------------------------------------
    print("\nduplicates and syndication")
    syndicated = scalar(
        "SELECT COUNT(*) FROM news_articles WHERE syndication_of_article_id IS NOT NULL"
    )
    report("syndication detected", True, f"{syndicated} bodies flagged as republications")

    self_syn = scalar(
        """SELECT COUNT(*) FROM news_articles a
           JOIN news_articles b ON b.article_id = a.syndication_of_article_id
           WHERE a.source_key = b.source_key"""
    )
    # Two articles from ONE masthead hashing alike is a running update, not a
    # syndication, and _find_syndication_source excludes same-publisher pairs.
    report("no article is flagged as a syndication of its own publisher",
           self_syn == 0, f"{self_syn} are")

    cycles = scalar(
        """SELECT COUNT(*) FROM news_articles a
           WHERE a.syndication_of_article_id IS NOT NULL
             AND EXISTS (SELECT 1 FROM news_articles b
                         WHERE b.article_id = a.syndication_of_article_id
                           AND b.syndication_of_article_id IS NOT NULL)"""
    )
    report("syndication chains are one level deep", cycles == 0,
           f"{cycles} point at another syndication")

    # -- Failed scrapes are not counted as successes -----------------------
    print("\nfailed scrapes are not counted as successes")
    ledger = Counter({r.status: r.n for r in db.execute(text(
        "SELECT status, COUNT(*) n FROM news_ingestions GROUP BY status"
    )).all()})
    print(f"        ledger: {dict(ledger)}")

    orphan = scalar(
        """SELECT COUNT(*) FROM news_ingestions
           WHERE status IN ('invalid', 'failed', 'skipped') AND article_id IS NOT NULL"""
    )
    report("no failed or invalid ingestion has an article attached", orphan == 0,
           f"{orphan} do")

    stored_no_article = scalar(
        """SELECT COUNT(*) FROM news_ingestions i
           WHERE i.status = 'stored'
             AND NOT EXISTS (SELECT 1 FROM news_articles a
                             WHERE a.article_id = i.article_id)"""
    )
    report("every 'stored' ledger row has its article", stored_no_article == 0,
           f"{stored_no_article} do not")

    unreached = ledger["pending"]
    report("no work left pending", unreached == 0,
           f"{unreached} urls discovered but never fetched", warn_only=True)

    stuck = scalar(
        "SELECT COUNT(*) FROM news_ingestions WHERE status = 'failed' AND attempts >= 5"
    )
    report("no url is stuck retrying forever", stuck == 0,
           f"{stuck} abandoned after 5 attempts", warn_only=True)

    # -- Entity links ------------------------------------------------------
    print("\nentity links")
    bad_link = scalar(
        """SELECT COUNT(*) FROM news_article_entities e
           WHERE e.entity_type = 'player'
             AND (e.player_identifier IS NULL
                  OR NOT EXISTS (SELECT 1 FROM players p
                                 WHERE p.identifier = e.player_identifier))"""
    )
    report("every player link resolves to a real player", bad_link == 0,
           f"{bad_link} do not")

    by_confidence = {r.confidence: r.n for r in db.execute(text(
        "SELECT confidence, COUNT(*) n FROM news_article_entities GROUP BY 1"
    )).all()}
    report("entity link provenance is recorded", True, str(by_confidence))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
    if WARNINGS:
        print(f"{len(WARNINGS)} warning(s): {', '.join(WARNINGS)}")
    if not FAILURES and not WARNINGS:
        print("all checks passed")
    return 1 if (FAILURES and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
