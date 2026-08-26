from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _engine_kwargs(database_url: str) -> dict:
    if not database_url.startswith("sqlite"):
        return {}

    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in database_url or "mode=memory" in database_url:
        # A plain in-memory SQLite database lives and dies with its connection.
        # StaticPool keeps a single connection alive so every request — and every
        # thread FastAPI hands work to — sees the same data for the process's lifetime.
        kwargs["poolclass"] = StaticPool
    return kwargs


settings = get_settings()

# Stable signed-bigint key for PostgreSQL's transaction-scoped advisory lock.
# The hexadecimal bytes spell "SFADDRV1", keeping this migration independent
# from any future schema locks.
_LEGACY_ADDRESS_MIGRATION_LOCK = 0x5346414444525631

engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    **_engine_kwargs(settings.database_url),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_db() -> None:
    """Create or upgrade tables. Called on startup; safe to call repeatedly."""
    from app import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)
    _upgrade_contacts_schema(engine)
    _migrate_legacy_addresses(engine)


def _upgrade_contacts_schema(target_engine: Engine) -> None:
    """Add nullable columns introduced after the original schema was released."""
    inspector = inspect(target_engine)
    if "contacts" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("contacts")}
    if "photo" in columns:
        return

    # The nullable TEXT definition is portable across supported SQLite and
    # PostgreSQL databases and preserves every existing contact.
    with target_engine.begin() as connection:
        connection.execute(text("ALTER TABLE contacts ADD COLUMN photo TEXT"))


def _migrate_legacy_addresses(target_engine: Engine) -> None:
    """Copy each pre-one-to-many address into a Home address exactly once."""
    inspector = inspect(target_engine)
    if not {"contacts", "addresses"}.issubset(inspector.get_table_names()):
        return
    legacy_columns = {"address", "city", "state", "postal_code", "country"}
    contact_columns = {column["name"] for column in inspector.get_columns("contacts")}
    if not legacy_columns.issubset(contact_columns):
        return

    with target_engine.begin() as connection:
        _lock_legacy_address_migration(connection, target_engine.dialect.name)
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS app_schema_migrations (
                    name VARCHAR(200) PRIMARY KEY
                )
                """
            )
        )
        claimed = connection.execute(
            text(
                """
                INSERT INTO app_schema_migrations (name)
                VALUES ('legacy-contact-addresses-v1')
                ON CONFLICT (name) DO NOTHING
                RETURNING name
                """
            )
        ).scalar_one_or_none()
        if claimed is None:
            return

        connection.execute(
            text(
                """
                INSERT INTO addresses
                    (contact_id, "type", street, city, state, postal_code, country)
                SELECT
                    contacts.id,
                    'Home',
                    NULLIF(TRIM(contacts.address), ''),
                    NULLIF(TRIM(contacts.city), ''),
                    NULLIF(TRIM(contacts.state), ''),
                    NULLIF(TRIM(contacts.postal_code), ''),
                    NULLIF(TRIM(contacts.country), '')
                FROM contacts
                WHERE (
                    NULLIF(TRIM(contacts.address), '') IS NOT NULL
                    OR NULLIF(TRIM(contacts.city), '') IS NOT NULL
                    OR NULLIF(TRIM(contacts.state), '') IS NOT NULL
                    OR NULLIF(TRIM(contacts.postal_code), '') IS NOT NULL
                    OR NULLIF(TRIM(contacts.country), '') IS NOT NULL
                )
                """
            )
        )


def _lock_legacy_address_migration(connection: Connection, dialect_name: str) -> None:
    """Serialize PostgreSQL's first marker-table creation and address backfill."""
    if dialect_name != "postgresql":
        return
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _LEGACY_ADDRESS_MIGRATION_LOCK},
    )


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
