from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import dashboard, matches, players, rankings, teams

app = FastAPI(title="The Cricket Index API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(rankings.router)
app.include_router(teams.router)
app.include_router(players.router)
app.include_router(matches.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
