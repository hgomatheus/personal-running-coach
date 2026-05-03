import os
import shutil
import logging
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from app.models.orm import BackupRecord
from app.config import get_settings

logger = logging.getLogger(__name__)


def run_backup(db: Session) -> BackupRecord:
    """
    Create a timestamped SQLite backup in the backup directory.
    Returns a BackupRecord (already committed to DB).
    """
    settings = get_settings()
    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Source DB path (strip sqlite:/// prefix)
    db_path = settings.database_url.replace("sqlite:///", "")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_filename = f"running_coach_backup_{timestamp}.db"
    backup_path = backup_dir / backup_filename

    record = BackupRecord(
        completed_at=datetime.now(timezone.utc),
        file_path=str(backup_path),
        size_bytes=0,
        success=False,
    )

    try:
        shutil.copy2(db_path, backup_path)
        record.size_bytes = backup_path.stat().st_size
        record.success = True
        logger.info(f"Backup completed: {backup_path} ({record.size_bytes} bytes)")
    except Exception as e:
        record.error_message = str(e)
        logger.error(f"Backup failed: {e}")

    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def prune_backups(db: Session, retain: int = 30) -> int:
    """
    Delete backup files and records beyond the retention limit.
    Keeps the `retain` most recent successful backups.
    Returns the number of backups deleted.
    """
    settings = get_settings()
    backup_dir = Path(settings.backup_dir)

    # Get all backup records ordered by completion time descending
    all_records = (
        db.query(BackupRecord)
        .filter(BackupRecord.success == True)
        .order_by(BackupRecord.completed_at.desc())
        .all()
    )

    to_delete = all_records[retain:]
    deleted_count = 0

    for record in to_delete:
        try:
            path = Path(record.file_path)
            if path.exists():
                path.unlink()
            db.delete(record)
            deleted_count += 1
        except Exception as e:
            logger.warning(f"Failed to delete backup {record.file_path}: {e}")

    if deleted_count > 0:
        db.commit()
        logger.info(f"Pruned {deleted_count} old backup(s)")

    return deleted_count
