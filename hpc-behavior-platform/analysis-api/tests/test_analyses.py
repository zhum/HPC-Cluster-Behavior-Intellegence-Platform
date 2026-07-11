from __future__ import annotations


def test_save_and_list_analysis(app_client):
    resp = app_client.post(
        "/analyses",
        json={
            "user_id": "alice",
            "name": "downtime investigation",
            "state": {"k": 4, "band": "2h", "lassoNodeIds": ["node-000", "node-001"]},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "alice"
    assert body["name"] == "downtime investigation"
    analysis_id = body["id"]

    listed = app_client.get("/analyses", params={"user_id": "alice"}).json()
    assert len(listed["analyses"]) == 1
    assert listed["analyses"][0]["id"] == analysis_id


def test_get_analysis_returns_full_state(app_client):
    resp = app_client.post(
        "/analyses",
        json={"user_id": "alice", "name": "n1", "state": {"band": "24h", "baselines": {"cpu": [0, 10]}}},
    )
    analysis_id = resp.json()["id"]

    detail = app_client.get(f"/analyses/{analysis_id}", params={"user_id": "alice"})
    assert detail.status_code == 200
    body = detail.json()
    assert body["state"] == {"band": "24h", "baselines": {"cpu": [0, 10]}}


def test_analyses_are_scoped_per_user(app_client):
    resp = app_client.post("/analyses", json={"user_id": "alice", "name": "alice's analysis", "state": {}})
    analysis_id = resp.json()["id"]

    # bob cannot see alice's analysis in his list
    bob_list = app_client.get("/analyses", params={"user_id": "bob"}).json()
    assert bob_list["analyses"] == []

    # bob cannot fetch it directly either, even knowing the id
    bob_get = app_client.get(f"/analyses/{analysis_id}", params={"user_id": "bob"})
    assert bob_get.status_code == 404

    # bob cannot delete it
    bob_delete = app_client.delete(f"/analyses/{analysis_id}", params={"user_id": "bob"})
    assert bob_delete.status_code == 404

    # alice still can
    alice_get = app_client.get(f"/analyses/{analysis_id}", params={"user_id": "alice"})
    assert alice_get.status_code == 200


def test_save_with_analysis_id_updates_in_place(app_client):
    resp = app_client.post("/analyses", json={"user_id": "alice", "name": "v1", "state": {"k": 4}})
    analysis_id = resp.json()["id"]

    update = app_client.post(
        "/analyses",
        json={"user_id": "alice", "name": "v2", "state": {"k": 5}, "analysis_id": analysis_id},
    )
    assert update.status_code == 200
    assert update.json()["id"] == analysis_id

    listed = app_client.get("/analyses", params={"user_id": "alice"}).json()
    assert len(listed["analyses"]) == 1  # updated in place, not duplicated
    assert listed["analyses"][0]["name"] == "v2"

    detail = app_client.get(f"/analyses/{analysis_id}", params={"user_id": "alice"}).json()
    assert detail["state"] == {"k": 5}


def test_save_with_unowned_analysis_id_is_rejected(app_client):
    resp = app_client.post("/analyses", json={"user_id": "alice", "name": "n1", "state": {}})
    analysis_id = resp.json()["id"]

    forged_update = app_client.post(
        "/analyses",
        json={"user_id": "bob", "name": "hijacked", "state": {}, "analysis_id": analysis_id},
    )
    assert forged_update.status_code == 404


def test_delete_analysis(app_client):
    resp = app_client.post("/analyses", json={"user_id": "alice", "name": "to-delete", "state": {}})
    analysis_id = resp.json()["id"]

    delete_resp = app_client.delete(f"/analyses/{analysis_id}", params={"user_id": "alice"})
    assert delete_resp.status_code == 200
    assert delete_resp.json() == {"deleted": True}

    listed = app_client.get("/analyses", params={"user_id": "alice"}).json()
    assert listed["analyses"] == []


def test_delete_nonexistent_analysis_404s(app_client):
    resp = app_client.delete("/analyses/does-not-exist", params={"user_id": "alice"})
    assert resp.status_code == 404
