from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # SQLite specific
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables and seed initial data."""
    from app.models.orm import Base as OrmBase  # avoid circular import
    OrmBase.metadata.create_all(bind=engine)
    _seed_initial_data()


def _seed_initial_data():
    """Seed two Profile rows and one AppSettings row if they don't exist."""
    from app.models.orm import Profile, AppSettings
    db = SessionLocal()
    try:
        if not db.query(Profile).filter(Profile.id == 1).first():
            db.add(Profile(id=1, display_name="Profile 1"))
        if not db.query(Profile).filter(Profile.id == 2).first():
            db.add(Profile(id=2, display_name="Profile 2"))
        if not db.query(AppSettings).filter(AppSettings.id == 1).first():
            db.add(AppSettings(
                id=1,
                strava_sync_interval_minutes=15,
                backup_enabled=True,
                backup_retention_days=30,
            ))
        db.commit()
    finally:
        db.close()
