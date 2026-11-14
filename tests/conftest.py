import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine

from reconciliation.db import query


@pytest.fixture
def database():
    load_dotenv()
    url = os.getenv("RECON_TEST_DATABASE_URL")
    if not url:
        if os.getenv("RECON_REQUIRE_POSTGRES"):
            pytest.fail("Set RECON_TEST_DATABASE_URL for the requested PostgreSQL suite")
        pytest.skip("Set RECON_TEST_DATABASE_URL to enable real PostgreSQL tests")
    if not url.startswith("postgresql+psycopg://"):
        pytest.fail("Integration tests require PostgreSQL with the Psycopg driver")
    schema = f"test_{uuid4().hex}"
    admin = create_engine(url, connect_args={"connect_timeout": 3})
    with admin.begin() as conn:
        query(conn, f'CREATE SCHEMA "{schema}"')
    db = create_engine(url, pool_pre_ping=True, connect_args={"options": f"-c search_path={schema}"})
    try:
        root = Path(__file__).resolve().parents[1]
        config = Config(str(root / "alembic.ini"))
        with db.connect() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        yield db
    finally:
        db.dispose()
        with admin.begin() as conn:
            query(conn, f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()
