from alembic import context
from sqlalchemy import create_engine

from reconciliation.db import database_url


def migrate(connection):
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    migrate(connection)
elif context.is_offline_mode():
    raise RuntimeError("Use an online PostgreSQL connection for migrations")
else:
    with create_engine(database_url(migration=True)).connect() as connection:
        migrate(connection)
