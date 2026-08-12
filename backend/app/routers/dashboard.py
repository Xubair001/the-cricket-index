from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import queries, schemas
from ..database import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=schemas.DashboardStats)
def dashboard(
    gender: str = Query(pattern="^(male|female)$"),
    db: Session = Depends(get_db),
) -> schemas.DashboardStats:
    return queries.get_dashboard_stats(db, gender)
