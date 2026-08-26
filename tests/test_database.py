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
