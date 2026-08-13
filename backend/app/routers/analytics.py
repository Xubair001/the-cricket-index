"""Analytics endpoints -- the vocabulary and the workings, not one screen's data.

These are deliberately domain-shaped rather than component-shaped. `/periods`
exists so the UI renders whatever windows the analytics layer actually supports
instead of keeping a second copy of that list that drifts; `/par` exists because
§30 requires that a derived figure can be traced to the numbers behind it, and
every impact score in the product is computed against these.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas
from ..analytics import impact, periods
from ..database import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/periods", response_model=list[schemas.PeriodOption])
def list_periods() -> list[schemas.PeriodOption]:
    """The period windows the analytics layer supports."""
    return [schemas.PeriodOption(**p) for p in periods.describe()]


@router.get("/par", response_model=list[schemas.ParFigures])
def par_figures(db: Session = Depends(get_db)) -> list[schemas.ParFigures]:
    """Measured par performance per competition and gender.

    Every one of these is computed from this dataset, not configured. They are
    what "a typical performance" means everywhere else in the product, so
    exposing them is what lets a user check an impact figure rather than take it
    on trust.
    """
    table = impact.par_table(db)
    return [
        schemas.ParFigures(
            competition_key=key,
            gender=gender,
            scoring_rate=round(par.scoring_rate, 2),
            economy=round(par.economy, 2),
            runs_per_wicket=round(par.runs_per_wicket, 2),
            mean_impact=round(par.mean_impact, 2),
            balls=par.balls,
        )
        for (key, gender), par in sorted(table.slices().items())
    ]
