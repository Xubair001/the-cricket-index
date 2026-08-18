"""Read queries for the news archive, and the one place content policy is enforced.

Kept out of queries.py, which is already 64 KB of Cricsheet aggregates and
shares nothing with this beyond the database file. Nothing here touches a
derived cricket figure and nothing in queries.py needs to know news exists.

The load-bearing part of this module is `_body_for`. Each publisher is
ingested under a content policy recorded on its row, and that policy is
applied HERE, on the way out, rather than at ingest time. Storing the full
body and capping the response is deliberate:

  * entity linking, search and syndication detection all need the whole text,
    and truncating at ingest would degrade them permanently;
  * the policy can be corrected without a re-scrape if a licence is obtained
    or withdrawn, which is not true of text thrown away on the way in.
"""
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# How much of an 'extract' publisher's body the API will return. Enough to be
# a useful preview and to show a search hit in context; well short of a
# republication. 'full' publishers are uncapped, 'metadata_only' get nothing
# because there is no body to give.
EXTRACT_SNIPPET_CHARS = 400


def _body_for(policy: str, body_text: str | None, body_html: str | None) -> dict:
    """Body fields for one article, capped to what its publisher permits.

    Returns `body_truncated` and `content_policy` on every article rather than
    only on capped ones, so a client can always tell a short article from a
    trimmed one. A silently truncated body that looks complete is the failure
    mode this exists to prevent.
    """
    if policy == "metadata_only" or not body_text:
        return {"body_text": None, "body_html": None, "body_truncated": False}
    if policy == "extract":
        snippet = body_text[:EXTRACT_SNIPPET_CHARS]
        truncated = len(body_text) > EXTRACT_SNIPPET_CHARS
        if truncated:
            # Cut on a word boundary; a snippet ending mid-word reads as a bug.
            snippet = snippet.rsplit(" ", 1)[0] + "…"
        return {"body_text": snippet, "body_html": None, "body_truncated": truncated}
    return {"body_text": body_text, "body_html": body_html, "body_truncated": False}


_LIST_SQL = """
SELECT a.article_id, a.title, a.standfirst, a.canonical_url, a.published_at,
       a.updated_at, a.section, a.word_count, a.source_key, a.body_text,
       a.body_html, a.syndication_of_article_id,
       p.name AS publisher_name, p.content_policy, p.attribution,
       i.cdn_url, i.width, i.height, ai.alt_text, ai.caption, ai.credit
FROM news_articles a
JOIN news_publishers p ON p.publisher_id = a.publisher_id
LEFT JOIN news_article_images ai
       ON ai.article_id = a.article_id AND ai.role = 'hero'
LEFT JOIN news_images i ON i.image_id = ai.image_id
"""


def _row_to_article(row: Any, include_body: bool) -> dict:
    body = _body_for(row.content_policy, row.body_text, row.body_html)
    item = {
        "article_id": row.article_id,
        "title": row.title,
        "standfirst": row.standfirst,
        "url": row.canonical_url,
        "published_at": row.published_at,
        "updated_at": row.updated_at,
        "section": row.section,
        "word_count": row.word_count,
        "source": row.source_key,
        "publisher": row.publisher_name,
        "content_policy": row.content_policy,
        "attribution": row.attribution,
        # Present and non-null means this body is a republication of another
        # article already in the archive. The row is kept rather than hidden:
        # a wire story running in three places is information.
        "syndication_of_article_id": row.syndication_of_article_id,
        "image": (
            {
                "url": row.cdn_url,
                "width": row.width,
                "height": row.height,
                "alt_text": row.alt_text,
                "caption": row.caption,
                "credit": row.credit,
            }
            if row.cdn_url
            else None
        ),
    }
    if include_body:
        item.update(body)
    else:
        item["body_truncated"] = body["body_truncated"]
    return item


# Articles positively identified as women's cricket, through a team link whose
# gender was established from explicit markers in the text.
_FEMALE_LINKED = """
EXISTS (SELECT 1 FROM news_article_entities ge
        JOIN teams gt ON gt.team_id = ge.team_id
        WHERE ge.article_id = a.article_id
          AND ge.entity_type = 'team'
          AND gt.gender = 'female')
"""


def list_articles(
    db: Session,
    source: str | None = None,
    gender: str | None = None,
    player_identifier: str | None = None,
    team_id: int | None = None,
    tag: str | None = None,
    search: str | None = None,
    include_syndicated: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """The news list, newest first.

    `include_syndicated` defaults to False so a reader sees each story once.
    The duplicates are excluded, never deleted: `syndication_of_article_id`
    still names the original, and passing the flag returns the whole set.

    `gender` is ASYMMETRIC, and deliberately so, because the underlying
    inference is. An article is never tagged with a gender by its publisher;
    `link_news_entities` reads one from explicit markers ("women's", "WBBL",
    "Women's T20 World Cup") and returns nothing when there are none. So:

        female   the article has a link to a women's side. A positive fact.
        male     the article has NO link to a women's side. An absence.

    Filtering men's news the same way as women's would be wrong twice over: it
    would drop every article this pipeline could not link to any team at all
    (roughly 40% of the ESPNcricinfo headlines, which carry no tags and no
    body), and it would present a default as a finding. Stating the rule this
    way keeps "we know this is women's cricket" separate from "nothing said
    otherwise", which is the same distinction `body_name_men_default` records
    on the row itself.
    """
    where = ["1=1"]
    params: dict[str, Any] = {}
    joins = ""

    if source:
        where.append("a.source_key = :source")
        params["source"] = source
    if gender == "female":
        where.append(_FEMALE_LINKED)
    elif gender == "male":
        where.append(f"NOT {_FEMALE_LINKED}")
    if not include_syndicated:
        where.append("a.syndication_of_article_id IS NULL")
    if player_identifier:
        joins += """
        JOIN news_article_entities pe
          ON pe.article_id = a.article_id
         AND pe.entity_type = 'player'
         AND pe.player_identifier = :player_identifier
        """
        params["player_identifier"] = player_identifier
    if team_id:
        joins += """
        JOIN news_article_entities te
          ON te.article_id = a.article_id
         AND te.entity_type = 'team'
         AND te.team_id = :team_id
        """
        params["team_id"] = team_id
    if tag:
        joins += """
        JOIN news_article_tags nat ON nat.article_id = a.article_id
        JOIN news_tags nt ON nt.tag_id = nat.tag_id AND nt.slug = :tag
        """
        params["tag"] = tag
    if search:
        # LIKE rather than FTS5. The archive is thousands of rows, not
        # millions, and an FTS index is a second copy of every body plus a
        # trigger to keep it current. Worth revisiting if this grows, and
        # noted rather than pretended away.
        where.append("(a.title LIKE :q OR a.standfirst LIKE :q OR a.body_text LIKE :q)")
        params["q"] = f"%{search}%"

    clause = " AND ".join(where)
    total = db.execute(
        text(f"SELECT COUNT(DISTINCT a.article_id) FROM news_articles a {joins} WHERE {clause}"),
        params,
    ).scalar_one()

    rows = db.execute(
        text(
            f"{_LIST_SQL} {joins} WHERE {clause} "
            "GROUP BY a.article_id "
            # NULLs last so an article with no publication date sinks to the
            # bottom rather than heading the feed.
            "ORDER BY a.published_at IS NULL, a.published_at DESC, a.article_id DESC "
            "LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    ).all()
    return [_row_to_article(r, include_body=False) for r in rows], total


def get_article(db: Session, article_id: int) -> dict | None:
    row = db.execute(
        text(f"{_LIST_SQL} WHERE a.article_id = :id GROUP BY a.article_id"),
        {"id": article_id},
    ).first()
    if row is None:
        return None

    article = _row_to_article(row, include_body=True)
    article["authors"] = [
        r.name
        for r in db.execute(
            text(
                """SELECT au.name FROM news_article_authors aa
                   JOIN news_authors au ON au.author_id = aa.author_id
                   WHERE aa.article_id = :id ORDER BY aa.position"""
            ),
            {"id": article_id},
        ).all()
    ]
    article["tags"] = [
        {"kind": r.kind, "value": r.value, "slug": r.slug}
        for r in db.execute(
            text(
                """SELECT t.kind, t.value, t.slug FROM news_article_tags at
                   JOIN news_tags t ON t.tag_id = at.tag_id
                   WHERE at.article_id = :id ORDER BY t.kind, t.value"""
            ),
            {"id": article_id},
        ).all()
    ]
    article["entities"] = [
        {
            "type": r.entity_type,
            "mention": r.mention,
            "confidence": r.confidence,
            "player_identifier": r.player_identifier,
            "player_name": r.player_name,
            "team_id": r.team_id,
            "team_name": r.team_name,
            "competition_id": r.competition_id,
            "competition_name": r.competition_name,
        }
        for r in db.execute(
            text(
                """SELECT e.entity_type, e.mention, e.confidence,
                          e.player_identifier,
                          COALESCE(pl.display_name, pl.name) AS player_name,
                          e.team_id, t.name AS team_name,
                          e.competition_id, c.display_name AS competition_name
                   FROM news_article_entities e
                   LEFT JOIN players pl ON pl.identifier = e.player_identifier
                   LEFT JOIN teams t ON t.team_id = e.team_id
                   LEFT JOIN competitions c ON c.competition_id = e.competition_id
                   WHERE e.article_id = :id
                   ORDER BY e.entity_type, e.confidence"""
            ),
            {"id": article_id},
        ).all()
    ]
    article["images"] = [
        {
            "url": r.cdn_url, "role": r.role, "width": r.width, "height": r.height,
            "alt_text": r.alt_text, "caption": r.caption, "credit": r.credit,
            "image_type": r.image_type,
        }
        for r in db.execute(
            text(
                """SELECT i.cdn_url, ai.role, i.width, i.height, ai.alt_text,
                          ai.caption, ai.credit, ai.image_type
                   FROM news_article_images ai
                   JOIN news_images i ON i.image_id = ai.image_id
                   WHERE ai.article_id = :id ORDER BY ai.position"""
            ),
            {"id": article_id},
        ).all()
    ]

    meta = db.execute(
        text(
            """SELECT meta_title, meta_description, og_json, twitter_json, schema_type
               FROM news_article_metadata WHERE article_id = :id"""
        ),
        {"id": article_id},
    ).first()
    article["metadata"] = (
        {
            "meta_title": meta.meta_title,
            "meta_description": meta.meta_description,
            "schema_type": meta.schema_type,
            "open_graph": json.loads(meta.og_json) if meta.og_json else {},
            "twitter": json.loads(meta.twitter_json) if meta.twitter_json else {},
        }
        if meta
        else None
    )

    # Every other article whose body is the same text. Surfaced rather than
    # hidden: seeing that one squad announcement ran in three places IS the
    # syndication feature.
    article["syndications"] = [
        {"article_id": r.article_id, "source": r.source_key, "url": r.canonical_url}
        for r in db.execute(
            text(
                """SELECT article_id, source_key, canonical_url FROM news_articles
                   WHERE syndication_of_article_id = :id
                      OR (article_id != :id
                          AND syndication_of_article_id = (
                              SELECT syndication_of_article_id FROM news_articles
                              WHERE article_id = :id))"""
            ),
            {"id": article_id},
        ).all()
    ]
    return article


def sources(db: Session) -> list[dict]:
    """Every registered publisher, INCLUDING the disabled ones and why.

    A source excluded on policy is part of the answer to "where does this
    come from", and hiding it would make the archive look like a complete
    survey of cricket journalism when it is a deliberate subset.
    """
    return [
        {
            "key": r.key, "name": r.name, "home_url": r.home_url,
            "strategy": r.strategy, "content_policy": r.content_policy,
            "attribution": r.attribution, "policy_note": r.policy_note,
            "enabled": bool(r.enabled), "last_synced_at": r.last_synced_at,
            "articles": r.articles,
        }
        for r in db.execute(
            text(
                """SELECT p.*, (SELECT COUNT(*) FROM news_articles a
                                WHERE a.publisher_id = p.publisher_id) AS articles
                   FROM news_publishers p ORDER BY articles DESC, p.key"""
            )
        ).all()
    ]


def health(db: Session) -> dict:
    """Pipeline state, for the page to declare rather than imply.

    Carries the ledger counts including 'invalid' and 'failed', because a
    reader looking at a thin feed deserves to know whether cricket was quiet
    or whether a publisher stopped answering.
    """
    ledger = {r.status: r.n for r in db.execute(
        text("SELECT status, COUNT(*) AS n FROM news_ingestions GROUP BY status")
    ).all()}
    per_source = [
        {"source": r.source_key, "articles": r.n, "latest": r.latest,
         "with_hero": r.with_hero, "linked_players": r.linked}
        for r in db.execute(
            text(
                """SELECT a.source_key, COUNT(*) AS n, MAX(a.published_at) AS latest,
                          SUM(CASE WHEN EXISTS (SELECT 1 FROM news_article_images ai
                                                WHERE ai.article_id = a.article_id
                                                  AND ai.role = 'hero')
                                   THEN 1 ELSE 0 END) AS with_hero,
                          SUM(CASE WHEN EXISTS (SELECT 1 FROM news_article_entities e
                                                WHERE e.article_id = a.article_id
                                                  AND e.entity_type = 'player')
                                   THEN 1 ELSE 0 END) AS linked
                   FROM news_articles a GROUP BY a.source_key ORDER BY n DESC"""
            )
        ).all()
    ]
    degraded = [
        {"source": r.source_key, "feed": r.feed_url, "failures": r.consecutive_failures,
         "last_status": r.last_status, "last_fetched_at": r.last_fetched_at}
        for r in db.execute(
            text(
                """SELECT * FROM news_feed_state WHERE consecutive_failures > 0
                   ORDER BY consecutive_failures DESC"""
            )
        ).all()
    ]
    return {
        "ledger": ledger,
        "sources": per_source,
        "degraded_feeds": degraded,
        "syndicated": db.execute(
            text("SELECT COUNT(*) FROM news_articles "
                 "WHERE syndication_of_article_id IS NOT NULL")
        ).scalar_one(),
        "entity_links": {
            r.confidence: r.n for r in db.execute(
                text("SELECT confidence, COUNT(*) AS n FROM news_article_entities "
                     "GROUP BY confidence")
            ).all()
        },
    }
