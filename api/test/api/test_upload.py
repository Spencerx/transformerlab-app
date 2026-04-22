import os


def test_init_upload(client):
    resp = client.post("/upload/init", json={"filename": "model.zip", "total_size": 1024})
    assert resp.status_code == 200
    body = resp.json()
    assert "upload_id" in body
    assert body["chunk_size"] == 64 * 1024 * 1024


def test_chunk_upload_and_status(client):
    init = client.post("/upload/init", json={"filename": "data.bin", "total_size": 6}).json()
    uid = init["upload_id"]

    resp = client.put(
        f"/upload/{uid}/chunk?chunk_index=0",
        content=b"ABC",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert resp.status_code == 200
    assert resp.json()["received"] == [0]

    status = client.get(f"/upload/{uid}/status").json()
    assert status["received"] == [0]
    assert status["complete"] is False


def test_complete_upload(client):
    init = client.post("/upload/init", json={"filename": "data.bin", "total_size": 6}).json()
    uid = init["upload_id"]

    client.put(
        f"/upload/{uid}/chunk?chunk_index=0",
        content=b"ABC",
        headers={"Content-Type": "application/octet-stream"},
    )
    client.put(
        f"/upload/{uid}/chunk?chunk_index=1",
        content=b"DEF",
        headers={"Content-Type": "application/octet-stream"},
    )

    resp = client.post(f"/upload/{uid}/complete", json={"total_chunks": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert "temp_path" in body

    assert os.path.isfile(body["temp_path"])
    with open(body["temp_path"], "rb") as f:
        assert f.read() == b"ABCDEF"


def test_complete_fails_with_missing_chunks(client):
    init = client.post("/upload/init", json={"filename": "data.bin", "total_size": 6}).json()
    uid = init["upload_id"]
    client.put(
        f"/upload/{uid}/chunk?chunk_index=0",
        content=b"ABC",
        headers={"Content-Type": "application/octet-stream"},
    )

    resp = client.post(f"/upload/{uid}/complete", json={"total_chunks": 2})
    assert resp.status_code == 400
    assert "Missing chunks" in resp.json()["detail"]


def test_delete_upload(client):
    init = client.post("/upload/init", json={"filename": "data.bin", "total_size": 1}).json()
    uid = init["upload_id"]

    resp = client.delete(f"/upload/{uid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    status = client.get(f"/upload/{uid}/status")
    assert status.status_code == 404
