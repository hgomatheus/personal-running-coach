"""Profiles router — GET /api/v1/profiles, GET/PUT /api/v1/profiles/{profile_id}."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.orm import Profile
from app.models.schemas import ProfileResponse, ProfileUpdate

router = APIRouter(tags=["profiles"])

VALID_PROFILE_IDS = {1, 2}


def _get_profile_or_404(profile_id: int, db: Session) -> Profile:
    if profile_id not in VALID_PROFILE_IDS:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.get("/profiles", response_model=list[ProfileResponse])
def list_profiles(db: Session = Depends(get_db)):
    """Return both profile records."""
    return db.query(Profile).order_by(Profile.id).all()


@router.get("/profiles/{profile_id}", response_model=ProfileResponse)
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    """Return a single profile; 404 if not found or id not in {1, 2}."""
    return _get_profile_or_404(profile_id, db)


@router.put("/profiles/{profile_id}", response_model=ProfileResponse)
def update_profile(
    profile_id: int,
    body: ProfileUpdate,
    db: Session = Depends(get_db),
):
    """Update profile fields and return the updated record."""
    profile = _get_profile_or_404(profile_id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile
