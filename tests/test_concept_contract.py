from tests.conftest import login


def test_concept_name_requires_non_whitespace_and_preserves_valid_name(client, sms):
    headers = {"X-CSRF-Token": login(client, sms, "09120000021")}
    url = "/api/v1/fragrance-concepts"
    note_id = client.get("/api/v1/fragrance-notes").json()[0]["id"]
    selection = [{"note_id": note_id, "layer": "top", "position": 0}]
    valid_name = "  باغ من  "
    created = client.post(url, json={"name": valid_name, "notes": selection}, headers=headers)
    assert created.status_code == 201, created.text
    saved = created.json()
    assert saved["name"] == valid_name

    for invalid_name in ("   ", "\t\n\u2003"):
        invalid = {"name": invalid_name, "notes": []}
        assert client.post(url, json=invalid, headers=headers).status_code == 422
        assert client.put(f"{url}/{saved['id']}", json=invalid, headers=headers).status_code == 422
        assert client.get(f"{url}/{saved['id']}").json() == saved
        assert client.get(url).json() == [saved]


def test_concept_positions_are_contiguous_within_each_layer(client, sms):
    headers = {"X-CSRF-Token": login(client, sms, "09120000022")}
    url = "/api/v1/fragrance-concepts"
    ids = [note["id"] for note in client.get("/api/v1/fragrance-notes").json()[:6]]
    selections = [
        {"note_id": note_id, "layer": layer, "position": position}
        for (layer, position), note_id in zip(
            (("top", 0), ("top", 1), ("heart", 0), ("heart", 1), ("base", 0), ("base", 1)),
            ids,
            strict=True,
        )
    ]
    created = client.post(url, json={"name": "لایه‌ها", "notes": selections}, headers=headers)
    assert created.status_code == 201, created.text
    saved = created.json()
    assert {(note["layer"], note["position"]) for note in saved["notes"]} == {
        ("top", 0), ("top", 1), ("heart", 0), ("heart", 1), ("base", 0), ("base", 1)
    }
    updated = client.put(
        f"{url}/{saved['id']}",
        json={"name": "لایه‌های تازه", "notes": selections[:4]},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    saved = updated.json()
    assert saved["name"] == "لایه‌های تازه"
    assert {(note["layer"], note["position"]) for note in saved["notes"]} == {
        ("top", 0), ("top", 1), ("heart", 0), ("heart", 1)
    }

    for invalid_positions in ((0, 2), (1, 2)):
        invalid_notes = [dict(note) for note in selections]
        invalid_notes[0]["position"], invalid_notes[1]["position"] = invalid_positions
        invalid = {"name": "نام جدید", "notes": invalid_notes}
        assert client.post(url, json=invalid, headers=headers).status_code == 422
        assert client.put(f"{url}/{saved['id']}", json=invalid, headers=headers).status_code == 422
        assert client.get(f"{url}/{saved['id']}").json() == saved
        assert client.get(url).json() == [saved]
