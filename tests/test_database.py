from sqlalchemy import create_engine, inspect, text

from app.database import _upgrade_contacts_schema


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
