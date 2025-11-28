# from sqlalchemy import create_engine
# from sqlalchemy.orm import sessionmaker, declarative_base

# SQLALCHEMY_DATABASE_URL = "sqlite:///./fantasy.db"

# engine = create_engine(
#     SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
# )
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# Base = declarative_base()
import os  # Wichtig für die Umgebungsvariablen
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# Der neue Code lädt die URL aus der Umgebungsvariable (DATABASE_URL)
# und fügt die notwendige SSL-Konfiguration für Cloud-Hosting hinzu.

SQLALCHEMY_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://user:password@localhost:5432/app_db"  # only fallback
)

if (
    SQLALCHEMY_DATABASE_URL.startswith("postgresql://")
    and "localhost" not in SQLALCHEMY_DATABASE_URL
):
    connect_args = {"sslmode": "require"}
else:
    connect_args = {}

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args=connect_args, pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
