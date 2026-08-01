import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


DATABASE_URL = get_required_env("DATABASE_URL")


def get_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    try:
        return int(raw_value)
    except ValueError:
        return default


engine_options = {
    "pool_pre_ping": True,
}

if not DATABASE_URL.startswith("sqlite"):
    engine_options.update(
        {
            "pool_size": get_int_env("DB_POOL_SIZE", 5),
            "max_overflow": get_int_env("DB_MAX_OVERFLOW", 5),
            "pool_timeout": get_int_env("DB_POOL_TIMEOUT", 15),
            "pool_recycle": get_int_env("DB_POOL_RECYCLE", 300),
            "pool_use_lifo": True,
        }
    )

engine = create_engine(DATABASE_URL, **engine_options)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
