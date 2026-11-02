"""Schema upgrades and a checked adoption path for the development prototype."""
from pathlib import Path
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.autogenerate import compare_metadata
from sqlalchemy import inspect
from app.core.db import get_engine
from app.models.models import Base

def alembic_config():
    return Config(str(Path(__file__).resolve().parents[2]/'alembic.ini'))

def upgrade_schema():
    command.upgrade(alembic_config(),'head')

def adopt_existing_schema():
    engine=get_engine()
    with engine.connect() as connection:
        tables=inspect(connection).get_table_names()
        if 'alembic_version' in tables:
            raise RuntimeError('Database already has migration history. Run upgrade instead.')
        differences=compare_metadata(MigrationContext.configure(connection,opts={'compare_type':True}),Base.metadata)
        legacy_baseline = len(differences) == 1 and differences[0][0] == "add_column" and differences[0][2] == "workflows" and differences[0][3].name == "monitoring_enabled"
        if differences and not legacy_baseline:
            raise RuntimeError('Existing schema differs from the migration baseline; back up and resolve the schema difference before adoption.')
    command.stamp(alembic_config(), "0001_initial" if legacy_baseline else "head")

def current_revision():
    with get_engine().connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()
