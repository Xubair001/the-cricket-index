"""Sports news: articles, publishers, and the pipeline's own health.

A fourth source family beside /api/matches (Cricsheet), /api/rankings
(computed here) and /api/icc/* (ICC's published figures), and separated from
them for the same reason those three are separated from each other: an
article is editorial copy, not a measurement, and nothing it says feeds a
derived figure.

/api/news/health is part of the product surface rather than an ops endpoint.
The archive is a deliberate subset of cricket journalism, gathered under
per-publisher policies, and a reader looking at a thin feed should be able to
see whether cricket was quiet or a publisher stopped answering.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import news, schemas
from ..database import get_db

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("", response_model=schemas.PaginatedNews)
def list_news(
    # Optional here, unlike the browse endpoints, where it is required. Gender
    # is a schema property of teams and players; an article is not gendered,
    # and demanding one would drop every article we could not link to a side.
    # What this filter CAN do is asymmetric - see news.list_articles - so it
    # stays optional and the pages that use it say which rule applied.
    gender: str | None = Query(default=None, pattern="^(male|female)$"),
    source: str | None = Query(default=None),
    player: str | None = Query(default=None, description="Cricsheet player identifier"),
    team_id: int | None = Query(default=None),
    tag: str | None = Query(default=None, description="tag slug"),
    q: str | None = Query(default=None, min_length=2, description="free text search"),
    include_syndicated: bool = Query(
        default=False,
        description="Include bodies that duplicate another article already listed",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.PaginatedNews:
    items, total = news.list_articles(
        db, source=source, gender=gender, player_identifier=player, team_id=team_id,
        tag=tag, search=q, include_syndicated=include_syndicated,
        limit=limit, offset=offset,
    )
    return schemas.PaginatedNews(
        total=total, limit=limit, offset=offset, items=items
    )


@router.get("/sources", response_model=list[schemas.NewsSourceInfo])
def list_sources(db: Session = Depends(get_db)) -> list[schemas.NewsSourceInfo]:
    """Every registered publisher, disabled ones included, with the reason.

    A source excluded on policy (the BBC's robots.txt forbids systematic
    extraction) is part of the answer to "where does this come from". Hiding
    it would make the archive look like a survey of cricket journalism when
    it is a deliberate subset.
    """
    return [schemas.NewsSourceInfo(**s) for s in news.sources(db)]


@router.get("/health", response_model=schemas.NewsHealth)
def health(db: Session = Depends(get_db)) -> schemas.NewsHealth:
    return schemas.NewsHealth(**news.health(db))


@router.get("/{article_id}", response_model=schemas.NewsArticleDetail)
def get_news(article_id: int, db: Session = Depends(get_db)) -> schemas.NewsArticleDetail:
    article = news.get_article(db, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    return schemas.NewsArticleDetail(**article)
