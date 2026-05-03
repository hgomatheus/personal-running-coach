"""Manual backup endpoint."""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.schemas import BackupRecordResponse
from app.services.backup_service import run_backup

logger = logging.getLogger(__name__)

router = APIRouter(tags=["backup"])


@router.post("/backup", response_model=BackupRecordResponse)
def trigger_backup(db: Session = Depends(get_db)):
    """Trigger a manual database backup. Returns the backup record."""
    record = run_backup(db)
    return record
