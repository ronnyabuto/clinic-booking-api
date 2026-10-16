from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def make_engine(url: str):
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("DATABASE_URL must use postgresql+psycopg://")
    parsed = make_url(url)
    if "connect_timeout" not in parsed.query:
        parsed = parsed.update_query_dict({"connect_timeout": "10"})
    return create_engine(parsed, pool_pre_ping=True, isolation_level="READ COMMITTED")


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
