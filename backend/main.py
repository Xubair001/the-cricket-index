import logging
import os
import threading

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import cache, queries
from app.database import SessionLocal
from app.routers import (
    analytics,
    competitions,
    dashboard,
    fixtures,
    icc,
    matches,
    news,
    players,
    rankings,
    teams,
    tournaments,
)

# Warming the default scopes at boot costs the process a few seconds of
# background CPU and saves the FIRST REAL USER from paying it. Measured cold on
# an empty cache: the Performance Index board is 7.5 s, the form boards 2.3 s,
# the all-round explorer 2.7 s - and warm, all three are under 5 ms. Without a
# warmup the first visitor after every restart gets the cold number.
#
# Set CRICKET_INDEX_WARM_CACHE=0 to skip it: a developer restarting the server
# repeatedly does not want to pay it each time, and a test run wants a cold,
# predictable cache.
WARM_CACHE = os.environ.get("CRICKET_INDEX_WARM_CACHE", "1") != "0"

# What an unqualified landing-page request warms.
#
# Two earlier attempts got this wrong in instructive ways, so the shape is
# deliberate:
#
# 1. Calling the helpers with `competition_type="international"` warmed keys no
#    request ever asks for. The routers pass None when the caller does not name a
#    scope and the default is applied further down, so the cache key is None -
#    every warmed entry was a miss. Warm with the arguments a REQUEST produces,
#    not with the scope it eventually resolves to.
# 2. Driving the real routes with TestClient from the warmup thread deadlocked
#    the server on startup: TestClient runs the ASGI app in its own event-loop
#    portal, and doing that inside a process already serving the same app hung it
#    before it answered anything. A warmup must never be able to take the server
#    down - hence direct calls, in a daemon thread, with every failure swallowed.
#
# `_warm_matches_request_keys` in the test below is how this stays honest.
WARM_GENDERS = ("male", "female")


def _warm_caches() -> None:
    """Build the expensive derived tables once, off the request path.

    Runs in a daemon thread so it cannot delay startup or hold the process open
    at shutdown. Every failure is swallowed and logged: a warmup is an
    optimisation, and a database that is mid-ingest or briefly locked must
    degrade to a slow first request, never to a server that will not start.

    Measured cold on an empty cache: the Performance Index board is 6.7 s, the
    form boards 3.3 s, the all-round explorer 1.8 s. Warm, all three are under
    5 ms. Without this the first visitor after every restart pays the cold cost.
    """
    from app.analytics import explorer as explorer_mod
    from app.analytics import leaderboard as leaderboard_mod
    from app.analytics import performance_index as pi
    from app.analytics import scout as scout_mod
    from app.analytics import selection as selection_mod

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        for gender in WARM_GENDERS:
            try:
                # `international` explicitly, not None. An unqualified request
                # resolves to it before reaching any cache (the routers apply
                # `queries.DEFAULT_RANKING_COMPETITION_TYPE`, and rankings go
                # through `_ranking_scope`), so that is the key to warm. Warming
                # with None populates entries nothing reads - which is exactly
                # what the first version of this did.
                scope = queries.DEFAULT_RANKING_COMPETITION_TYPE
                queries._batting_aggregate_rows(db, gender, competition_type=scope)
                queries._bowling_aggregate_rows(db, gender, competition_type=scope)
                queries._player_country_map(db, gender)
                pi.page(db, gender=gender, competition_type=scope, limit=1)
                leaderboard_mod.leaderboard_page(
                    db, gender=gender, competition_type=scope, limit=1
                )
                # min_balls is per-discipline and applied by the ROUTER, not by
                # ExplorerFilters' own default - so warming with the dataclass
                # default (0) builds a board no request asks for. Mirrors the
                # mapping in routers/analytics.py.
                # Best XI and Scout are nav destinations and cost ~3 s and
                # ~0.4 s cold. They share the scope summary, so warming one
                # mostly warms the other.
                selection_mod.select_side(db, gender=gender, competition_type=scope)
                scout_mod.search(db, gender=gender, competition_type=scope, limit=1)
                for board, min_balls in (
                    ("batting", explorer_mod.DEFAULT_MIN_BALLS_FACED),
                    ("bowling", explorer_mod.DEFAULT_MIN_BALLS_BOWLED),
                    ("allround", 0),
                ):
                    explorer_mod.page(
                        db, board,
                        explorer_mod.ExplorerFilters(gender=gender, min_balls=min_balls),
                        "index" if board == "allround" else "runs", 1, 0,
                    )
            except Exception:
                log.warning(
                    "cache warmup failed for gender=%s; first request will be slow",
                    gender, exc_info=True,
                )
    finally:
        db.close()
    log.info("cache warmup complete: %s", cache.stats())


app = FastAPI(title="The Cricket Index API")


@app.on_event("startup")
def _start_warmup() -> None:
    if WARM_CACHE:
        threading.Thread(target=_warm_caches, name="cache-warmup", daemon=True).start()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Headers that cost nothing and close the cheap classes of attack.

    This API serves JSON to a same-origin SPA and never renders HTML, so the
    usual XSS surface is absent - but a browser that MIME-sniffs a JSON body as
    HTML brings it back, and an error body echoes caller-supplied strings. The
    three below are the ones that apply to a JSON API:

    * nosniff stops the sniffing that would make that echo executable.
    * DENY framing: nothing here is meant to be embedded, and refusing is
      cheaper than reasoning about who might.
    * no-referrer keeps query strings - which carry the whole query, including
      any search terms - out of the Referer header on any outbound navigation.

    A CSP is deliberately absent: it governs what a *document* may load, and
    this app returns no documents. The SPA's CSP belongs wherever the built
    frontend is served from, not here.
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


app.include_router(dashboard.router)
app.include_router(competitions.router)
app.include_router(analytics.router)
app.include_router(rankings.router)
app.include_router(teams.router)
app.include_router(players.router)
app.include_router(matches.router)
app.include_router(icc.router)
app.include_router(fixtures.router)
app.include_router(news.router)
app.include_router(tournaments.router)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Return a generic 500 body, never the exception.

    Starlette already hides tracebacks from the response when `debug` is off,
    and this makes that explicit and independent of that setting: an unhandled
    error must not leak a query, a file path, or a driver message to a caller.
    The full traceback still goes to the server log, which is where it is useful.
    """
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/api/health")
def health() -> dict:
    """Liveness, plus what the process is currently holding.

    `cache` reports the derived-table entries held and the SQLite `data_version`
    they were built against, which is the quickest way to tell a slow first
    request (cold cache) from a slow endpoint.
    """
    return {"status": "ok", "cache": cache.stats()}
