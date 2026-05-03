"""Data export and import endpoints — JSON, CSV, iCal."""
import csv
import io
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.orm import Run, TrainingPlan, Workout, Profile
from app.models.schemas import ImportDataRequest
from app.services.data_export_service import export_profile, import_profile

logger = logging.getLogger(__name__)

router = APIRouter(tags=["data-export"])


# ---------------------------------------------------------------------------
# JSON export / import
# ---------------------------------------------------------------------------

@router.get("/profiles/{profile_id}/export/json")
def export_json(profile_id: int, db: Session = Depends(get_db)):
    """Export all profile data as a downloadable JSON file."""
    try:
        data = export_profile(profile_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    json_bytes = json.dumps(data, indent=2, default=str).encode("utf-8")
    filename = f"profile_{profile_id}_export.json"
    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/profiles/{profile_id}/import/json")
async def import_json(
    profile_id: int,
    mode: str = Query("merge", regex="^(merge|replace)$"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Import profile data from a previously exported JSON file.
    mode=merge: skip existing records.
    mode=replace: delete all existing data first.
    """
    raw = await file.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"Invalid JSON: {e}")

    try:
        stats = import_profile(data, profile_id, mode, db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"detail": "Import complete", "stats": stats, "mode": mode}


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@router.get("/profiles/{profile_id}/export/csv")
def export_csv(profile_id: int, db: Session = Depends(get_db)):
    """Export all runs for a profile as a CSV file."""
    runs = (
        db.query(Run)
        .filter(Run.profile_id == profile_id)
        .order_by(Run.date.desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "date", "distance_km", "duration_seconds", "avg_pace_min_km",
        "avg_heart_rate", "elevation_gain_metres", "run_type", "notes",
    ])

    for run in runs:
        avg_pace_str = ""
        if run.avg_pace_sec_per_km:
            mins = int(run.avg_pace_sec_per_km // 60)
            secs = int(run.avg_pace_sec_per_km % 60)
            avg_pace_str = f"{mins}:{secs:02d}"

        writer.writerow([
            run.date.isoformat(),
            round(run.distance_metres / 1000, 2),
            run.duration_seconds,
            avg_pace_str,
            run.avg_heart_rate or "",
            run.elevation_gain_metres or "",
            run.run_type or "",
            run.notes or "",
        ])

    csv_bytes = output.getvalue().encode("utf-8")
    filename = f"runs_profile_{profile_id}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# iCal export
# ---------------------------------------------------------------------------

@router.get("/profiles/{profile_id}/export/ical")
def export_ical(profile_id: int, db: Session = Depends(get_db)):
    """Export the active training plan as an iCal (.ics) file."""
    active_plan = (
        db.query(TrainingPlan)
        .filter(
            TrainingPlan.profile_id == profile_id,
            TrainingPlan.status == "active",
        )
        .first()
    )
    if active_plan is None:
        raise HTTPException(status_code=404, detail="No active training plan found")

    workouts = (
        db.query(Workout)
        .filter(
            Workout.plan_id == active_plan.id,
            Workout.profile_id == profile_id,
            Workout.workout_type != "rest",
        )
        .order_by(Workout.scheduled_date)
        .all()
    )

    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    profile_name = profile.display_name if profile else f"Profile {profile_id}"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Personal Running Coach//EN",
        f"X-WR-CALNAME:{profile_name} Training Plan",
        "X-WR-TIMEZONE:UTC",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for workout in workouts:
        date_str = workout.scheduled_date.strftime("%Y%m%d")
        uid = f"workout-{workout.id}@running-coach"
        summary = workout.workout_type
        description = workout.coaching_note or f"{workout.workout_type.title()} workout"
        # Escape special characters for iCal
        description = description.replace("\n", "\\n").replace(",", "\\,")

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART;VALUE=DATE:{date_str}",
            f"DTEND;VALUE=DATE:{date_str}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{description}",
            f"CATEGORIES:{workout.workout_type.upper()}",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    ical_content = "\r\n".join(lines) + "\r\n"

    filename = f"training_plan_profile_{profile_id}.ics"
    return Response(
        content=ical_content.encode("utf-8"),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
