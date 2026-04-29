import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker


load_dotenv()


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return database_url


DATABASE_URL = _normalize_database_url(
    os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/acadextract",
    )
)
DB_SCHEMA = os.getenv("DB_SCHEMA", "student_app")

engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args={"options": f"-csearch_path={DB_SCHEMA}"},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()


with engine.begin() as connection:
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}" AUTHORIZATION CURRENT_USER'))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
