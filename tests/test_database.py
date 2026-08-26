from sqlalchemy import create_engine, inspect, text

from app.database import _migrate_legacy_addresses, _upgrade_contacts_schema


def test_upgrade_adds_photo_to_legacy_contacts_table():
    legacy_engine = create_engine("sqlite+pysqlite:///:memory:")
    with legacy_engine.begin() as connection:
        connection.execute(text("CREATE TABLE contacts (id INTEGER PRIMARY KEY)"))

    _upgrade_contacts_schema(legacy_engine)

    columns = {column["name"] for column in inspect(legacy_engine).get_columns("contacts")}
    assert columns == {"id", "photo"}


def test_upgrade_is_idempotent():
    legacy_engine = create_engine("sqlite+pysqlite:///:memory:")
    with legacy_engine.begin() as connection:
        connection.execute(text("CREATE TABLE contacts (id INTEGER PRIMARY KEY)"))

    _upgrade_contacts_schema(legacy_engine)
    _upgrade_contacts_schema(legacy_engine)

    columns = [column["name"] for column in inspect(legacy_engine).get_columns("contacts")]
    assert columns.count("photo") == 1


def test_legacy_address_is_migrated_once():
    legacy_engine = create_engine("sqlite+pysqlite:///:memory:")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE contacts (
                    id INTEGER PRIMARY KEY,
                    address VARCHAR(300), city VARCHAR(120), state VARCHAR(120),
                    postal_code VARCHAR(20), country VARCHAR(120)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE addresses (
                    id INTEGER PRIMARY KEY,
                    contact_id INTEGER NOT NULL,
                    "type" VARCHAR(10) NOT NULL,
                    street VARCHAR(300),
                    city VARCHAR(120), state VARCHAR(120),
                    postal_code VARCHAR(20), country VARCHAR(120)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO contacts (id, address, city, state, postal_code, country)
                VALUES (1, '1 Market St', 'San Francisco', 'CA', '94105', 'USA')
                """
            )
        )

    _migrate_legacy_addresses(legacy_engine)
    _migrate_legacy_addresses(legacy_engine)

    with legacy_engine.connect() as connection:
        rows = connection.execute(
            text('SELECT contact_id, "type", street, city FROM addresses')
        ).mappings().all()
    assert rows == [
        {"contact_id": 1, "type": "Home", "street": "1 Market St", "city": "San Francisco"}
    ]


def test_legacy_migration_skips_blank_addresses_and_trims_values():
    legacy_engine = create_engine("sqlite+pysqlite:///:memory:")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE contacts (
                    id INTEGER PRIMARY KEY,
                    address VARCHAR(300), city VARCHAR(120), state VARCHAR(120),
                    postal_code VARCHAR(20), country VARCHAR(120)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE addresses (
                    id INTEGER PRIMARY KEY,
                    contact_id INTEGER NOT NULL,
                    "type" VARCHAR(10) NOT NULL,
                    street VARCHAR(300), city VARCHAR(120), state VARCHAR(120),
                    postal_code VARCHAR(20), country VARCHAR(120)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO contacts (id, address, city, state, postal_code, country)
                VALUES
                    (1, '', '   ', NULL, NULL, NULL),
                    (2, '  2 Main St  ', ' Seattle ', NULL, NULL, ' USA ')
                """
            )
        )

    _migrate_legacy_addresses(legacy_engine)

    with legacy_engine.connect() as connection:
        rows = connection.execute(
            text('SELECT contact_id, street, city, country FROM addresses ORDER BY contact_id')
        ).mappings().all()
    assert rows == [
        {"contact_id": 2, "street": "2 Main St", "city": "Seattle", "country": "USA"}
    ]


def test_legacy_migration_keeps_existing_and_legacy_addresses():
    legacy_engine = create_engine("sqlite+pysqlite:///:memory:")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE contacts (
                    id INTEGER PRIMARY KEY,
                    address VARCHAR(300), city VARCHAR(120), state VARCHAR(120),
                    postal_code VARCHAR(20), country VARCHAR(120)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE addresses (
                    id INTEGER PRIMARY KEY,
                    contact_id INTEGER NOT NULL,
                    "type" VARCHAR(10) NOT NULL,
                    street VARCHAR(300), city VARCHAR(120), state VARCHAR(120),
                    postal_code VARCHAR(20), country VARCHAR(120)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO contacts (id, address, city)
                VALUES (1, 'Legacy Home', 'Boston')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO addresses (contact_id, "type", street, city)
                VALUES (1, 'Work', 'Existing Work', 'Cambridge')
                """
            )
        )

    _migrate_legacy_addresses(legacy_engine)
    _migrate_legacy_addresses(legacy_engine)

    with legacy_engine.connect() as connection:
        rows = connection.execute(
            text('SELECT "type", street FROM addresses ORDER BY id')
        ).mappings().all()
    assert rows == [
        {"type": "Work", "street": "Existing Work"},
        {"type": "Home", "street": "Legacy Home"},
    ]
