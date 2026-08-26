import base64


BASE = "/api/v1/contacts"

PNG_PHOTO = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "sqlite"


def test_create_contact(client, payload):
    response = client.post(BASE, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["email"] == "ada@example.com"
    assert body["full_name"] == "Ada Lovelace"
    assert body["created_at"] and body["updated_at"]


def test_create_contact_with_photo(client, payload):
    response = client.post(BASE, json={**payload, "photo": PNG_PHOTO})

    assert response.status_code == 201
    assert response.json()["photo"] == PNG_PHOTO


def test_create_contact_with_multiple_addresses(client, payload):
    addresses = [
        {
            "type": "Home",
            "street": "1 Market St",
            "city": "San Francisco",
            "state": "CA",
            "postal_code": "94105",
            "country": "USA",
        },
        {
            "type": "Work",
            "street": "1 Hacker Way",
            "city": "Menlo Park",
            "state": "CA",
            "postal_code": "94025",
            "country": "USA",
        },
    ]
    response = client.post(BASE, json={**payload, "addresses": addresses})

    assert response.status_code == 201
    stored = response.json()["addresses"]
    assert [address["type"] for address in stored] == ["Home", "Work"]
    assert all(address["id"] > 0 for address in stored)


def test_create_rejects_invalid_address_type(client, payload):
    response = client.post(
        BASE,
        json={**payload, "addresses": [{"type": "Vacation", "street": "Beach"}]},
    )

    assert response.status_code == 422


def test_create_rejects_empty_address(client, payload):
    response = client.post(
        BASE,
        json={**payload, "addresses": [{"type": "Home"}]},
    )

    assert response.status_code == 422


def test_create_rejects_whitespace_only_address(client, payload):
    response = client.post(
        BASE,
        json={**payload, "addresses": [{"type": "Home", "street": "   "}]},
    )

    assert response.status_code == 422


def test_create_trims_address_fields(client, payload):
    response = client.post(
        BASE,
        json={
            **payload,
            "addresses": [{"type": "Work", "street": "  1 Market St  ", "city": " SF "}],
        },
    )

    assert response.status_code == 201
    assert response.json()["addresses"][0]["street"] == "1 Market St"
    assert response.json()["addresses"][0]["city"] == "SF"


def test_create_rejects_unsupported_photo_type(client, payload):
    gif = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
    response = client.post(BASE, json={**payload, "photo": gif})

    assert response.status_code == 422


def test_create_rejects_photo_with_mismatched_content(client, payload):
    response = client.post(
        BASE,
        json={**payload, "photo": PNG_PHOTO.replace("image/png", "image/jpeg")},
    )

    assert response.status_code == 422


def test_create_rejects_oversized_photo(client, payload):
    oversized_png = b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024)
    photo = "data:image/png;base64," + base64.b64encode(oversized_png).decode()
    response = client.post(BASE, json={**payload, "photo": photo})

    assert response.status_code == 422


def test_create_requires_valid_email(client, payload):
    response = client.post(BASE, json={**payload, "email": "not-an-email"})
    assert response.status_code == 422


def test_create_requires_names(client, payload):
    response = client.post(BASE, json={**payload, "first_name": ""})
    assert response.status_code == 422


def test_duplicate_email_conflicts(client, payload):
    assert client.post(BASE, json=payload).status_code == 201
    response = client.post(BASE, json={**payload, "email": "ADA@example.com"})
    assert response.status_code == 409


def test_get_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.get(f"{BASE}/{contact_id}")
    assert response.status_code == 200
    assert response.json()["id"] == contact_id


def test_get_missing_contact_returns_404(client):
    assert client.get(f"{BASE}/9999").status_code == 404


def test_list_pagination_and_total(client, payload):
    for index in range(5):
        client.post(BASE, json={**payload, "email": f"user{index}@example.com"})

    response = client.get(BASE, params={"limit": 2, "offset": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2 and body["offset"] == 2


def test_list_search(client, payload):
    client.post(BASE, json=payload)
    client.post(
        BASE,
        json={**payload, "first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com", "company": "US Navy"},
    )

    hits = client.get(BASE, params={"search": "hopper"}).json()
    assert hits["total"] == 1
    assert hits["items"][0]["last_name"] == "Hopper"

    by_company = client.get(BASE, params={"search": "navy"}).json()
    assert by_company["total"] == 1

    misses = client.get(BASE, params={"search": "nobody"}).json()
    assert misses["total"] == 0


def test_list_sorting(client, payload):
    client.post(BASE, json={**payload, "last_name": "Zhang", "email": "z@example.com"})
    client.post(BASE, json={**payload, "last_name": "Adams", "email": "a@example.com"})

    names = [
        item["last_name"]
        for item in client.get(BASE, params={"sort_by": "last_name", "order": "asc"}).json()["items"]
    ]
    assert names == ["Adams", "Zhang"]


def test_list_rejects_bad_sort_field(client):
    assert client.get(BASE, params={"sort_by": "; DROP TABLE contacts"}).status_code == 422


def test_patch_updates_only_sent_fields(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == "+1-000-000-0000"
    assert body["first_name"] == "Ada"
    assert body["company"] == "Analytical Engines"


def test_patch_can_remove_photo(client, payload):
    contact_id = client.post(BASE, json={**payload, "photo": PNG_PHOTO}).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"photo": None})

    assert response.status_code == 200
    assert response.json()["photo"] is None


def test_patch_preserves_addresses_when_omitted(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"company": "New Company"})

    assert response.status_code == 200
    assert len(response.json()["addresses"]) == 1


def test_patch_replaces_addresses_when_supplied(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    replacement = [{"type": "Other", "street": "42 New Road", "country": "UK"}]
    response = client.patch(f"{BASE}/{contact_id}", json={"addresses": replacement})

    assert response.status_code == 200
    assert response.json()["addresses"][0]["type"] == "Other"
    assert response.json()["addresses"][0]["street"] == "42 New Road"


def test_patch_duplicate_email_conflicts(client, payload):
    first = client.post(BASE, json=payload).json()["id"]
    client.post(BASE, json={**payload, "email": "grace@example.com"})
    response = client.patch(f"{BASE}/{first}", json={"email": "grace@example.com"})
    assert response.status_code == 409


def test_patch_same_email_is_allowed(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"email": payload["email"]})
    assert response.status_code == 200


def test_put_replaces_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Grace Hopper"
    assert body["company"] is None  # omitted fields are cleared by PUT


def test_put_preserves_photo_when_resubmitted(client, payload):
    contact_id = client.post(BASE, json={**payload, "photo": PNG_PHOTO}).json()["id"]
    response = client.put(f"{BASE}/{contact_id}", json={**payload, "photo": PNG_PHOTO})

    assert response.status_code == 200
    assert response.json()["photo"] == PNG_PHOTO


def test_put_replaces_entire_address_collection(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    replacement = [
        {"type": "Work", "street": "100 Main St"},
        {"type": "Other", "street": "PO Box 7"},
    ]
    response = client.put(f"{BASE}/{contact_id}", json={**payload, "addresses": replacement})

    assert response.status_code == 200
    assert [(item["type"], item["street"]) for item in response.json()["addresses"]] == [
        ("Work", "100 Main St"),
        ("Other", "PO Box 7"),
    ]


def test_delete_contact_cascades_to_addresses(client, payload):
    from sqlalchemy import text

    from app.database import SessionLocal

    contact_id = client.post(BASE, json=payload).json()["id"]
    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    with SessionLocal() as db:
        count = db.execute(
            text("SELECT COUNT(*) FROM addresses WHERE contact_id = :contact_id"),
            {"contact_id": contact_id},
        ).scalar_one()
    assert count == 0


def test_put_missing_contact_returns_404(client):
    response = client.put(
        f"{BASE}/9999",
        json={"first_name": "A", "last_name": "B", "email": "ab@example.com"},
    )
    assert response.status_code == 404


def test_delete_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    assert client.get(f"{BASE}/{contact_id}").status_code == 404
    assert client.delete(f"{BASE}/{contact_id}").status_code == 404


def test_root_lists_entrypoints(client):
    body = client.get("/").json()
    assert body["contacts"] == BASE
