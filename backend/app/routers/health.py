from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check — returns 200 when all services are operational."""
    # Verify DB is reachable
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
