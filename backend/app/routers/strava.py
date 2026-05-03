"""Strava OAuth and sync endpoints."""
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.orm import StravaToken, ImportRecord
from app.models.schemas import BulkImportResponse
from app.services import strava_client
from app.services.strava_bulk_importer import parse_zip, import_activities

logger = logging.getLogger(__name__)

router = APIRouter(tags=["strava"])

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------

@router.get("/profiles/{profile_id}/strava/auth")
async def strava_auth(profile_id: int):
    """Redirect the user to Strava's OAuth authorisation page."""
    settings = get_settings()
    callback_url = (
        f"{settings.app_base_url}/api/v1/profiles/{profile_id}/strava/callback"
    )
    url = (
        f"{STRAVA_AUTH_URL}"
        f"?client_id={settings.strava_client_id}"
        f"&redirect_uri={callback_url}"
        f"&response_type=code"
        f"&scope=activity:read_all"
        f"&state={profile_id}"
    )
    return RedirectResponse(url=url)


@router.get("/profiles/{profile_id}/strava/callback")
async def strava_callback(
    profile_id: int,
    code: str,
    background_tasks: BackgroundTasks,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    """Handle Strava OAuth callback, exchange code, trigger 90-day import."""
    try:
        await strava_client.exchange_code(code, profile_id, db)
    except Exception as e:
        logger.error(f"Strava OAuth exchange failed for profile {profile_id}: {e}")
        raise HTTPException(status_code=400, detail=f"OAuth exchange failed: {e}")

    # Trigger 90-day background import
    background_tasks.add_task(_initial_import, profile_id)

    settings = get_settings()
    return RedirectResponse(url=f"{settings.app_base_url}/settings?strava=connected")


async def _initial_import(profile_id: int):
    """Background task: import last 90 days of Strava activities."""
    from app.database import SessionLocal
    from app.services.strava_sync import sync_profile

    db = SessionLocal()
    try:
        # Set last_sync_at to 90 days ago so sync_profile fetches 90 days
        token = db.query(StravaToken).filter(StravaToken.profile_id == profile_id).first()
        if token:
            token.last_sync_at = datetime.now(timezone.utc) - timedelta(days=90)
            db.commit()
        await sync_profile(profile_id, db)
    except Exception as e:
        logger.error(f"Initial Strava import failed for profile {profile_id}: {e}")
    finally:
        db.close()


@router.delete("/profiles/{profile_id}/strava/disconnect")
async def strava_disconnect(profile_id: int, db: Session = Depends(get_db)):
    """Revoke Strava token. Run data is retained."""
    revoked = await strava_client.revoke_token(profile_id, db)
    if not revoked:
        raise HTTPException(status_code=404, detail="No Strava connection found")
    return {"detail": "Strava disconnected. Run data retained."}


@router.get("/profiles/{profile_id}/strava/status")
def strava_status(profile_id: int, db: Session = Depends(get_db)):
    """Return Strava connection status for the profile."""
    token = db.query(StravaToken).filter(StravaToken.profile_id == profile_id).first()
    if token is None:
        return {"connected": False, "athlete_id": None, "last_sync_at": None, "sync_error": None}
    return {
        "connected": True,
        "athlete_id": token.athlete_id,
        "last_sync_at": token.last_sync_at,
        "sync_error": token.sync_error,
    }


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------

@router.post("/profiles/{profile_id}/strava/bulk-import", response_model=BulkImportResponse)
async def strava_bulk_import(
    profile_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Accept a Strava export ZIP and bulk-import all Run activities."""
    file_bytes = await file.read()
    try:
        records = parse_zip(file_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse ZIP: {e}")

    result = import_activities(records, profile_id, db, source_filename=file.filename)

    return BulkImportResponse(**result)


@router.get("/profiles/{profile_id}/strava/import-history")
def strava_import_history(profile_id: int, db: Session = Depends(get_db)):
    """Return list of past bulk import records for the profile."""
    records = (
        db.query(ImportRecord)
        .filter(ImportRecord.profile_id == profile_id)
        .order_by(ImportRecord.imported_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "imported_at": r.imported_at,
            "activities_imported": r.activities_imported,
            "duplicates_skipped": r.duplicates_skipped,
            "parse_errors": r.parse_errors,
            "vdot_calculated": r.vdot_calculated,
            "source_filename": r.source_filename,
        }
        for r in records
    ]
