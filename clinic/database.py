from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_engine(url: str):
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("DATABASE_URL must use postgresql+psycopg://")
    return create_engine(url, pool_pre_ping=True, isolation_level="READ COMMITTED")


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
