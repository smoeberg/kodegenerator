# infrastructure/database/base.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.ext.declarative import declarative_base
from .models import Base

# Opret database-engine
SQLALCHEMY_DATABASE_URL = "postgresql://user:password@localhost:5432/dor_db"
# For SQLite (udvikling):
# SQLALCHEMY_DATABASE_URL = "sqlite:///./dor.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    """Dependency for FastAPI (hvis vi senere integrerer med API)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialiser databasen (opret tabeller)."""
    Base.metadata.create_all(bind=engine)
