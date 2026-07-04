def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["providers"]) == {"llm", "stt", "tts", "ocr"}
    assert all(v == "mock" for v in body["providers"].values())
