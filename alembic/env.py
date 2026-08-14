import os
import sys
from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import SQLModel
from app.database import get_engine
from app.models import Lead, Campaign, User, License, EmailLog, ReplyLog, Suppression

config = context.config
fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

def get_database_url():
    return os.getenv('DATABASE_URL') or config.get_main_option("sqlalchemy.url")


def run_migrations_offline():
    url = get_database_url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
