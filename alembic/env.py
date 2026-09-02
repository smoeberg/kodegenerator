import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, inspect, pool, text

from alembic import context
from infrastructure.persistence.models import Base

# Some revisions in this migration graph deliberately carry 33-character IDs
# (e.g. 002b_authority_organization_scope, 009_p4_01_execution_replay_ledger),
# which exceed Alembic's default VARCHAR(32) on alembic_version.version_num.
# On a fresh PostgreSQL database that would fail with StringDataRightTruncation.
# We therefore provision alembic_version with a wider column before any
# migration runs, so the full revision chain fits regardless of when the
# table is first created.
_VERSION_NUM_COL = "VARCHAR(128)"

config = context.config
database_url = os.getenv("DATABASE_URL")
if database_url:
    # ConfigParser reserves percent signs for interpolation. Escaping here
    # preserves URL-encoded passwords when Alembic reads the value back.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
if config.config_file_name is not None:
    # Never disable existing loggers: fileConfig(disable_existing_loggers=True)
    # would kill pytest's caplog handlers and application loggers alike.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _widen_version_table(connection) -> None:
    """Ensure alembic_version can hold long revision IDs before migrations run."""
    if connection.dialect.name != "postgresql":
        return
    inspector = inspect(connection)
    has_table = inspector.has_table("alembic_version")
    if not has_table:
        # Belt-and-braces on a truly fresh database: provision the table wide
        # now so Alembic does not create it at VARCHAR(32) during upgrade.
        connection.execute(
            text(
                f"CREATE TABLE alembic_version (version_num {_VERSION_NUM_COL} NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
    else:
        connection.execute(
            text(
                f"ALTER TABLE alembic_version "
                f"ALTER COLUMN version_num TYPE {_VERSION_NUM_COL}"
            )
        )


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _widen_version_table(connection)
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
