from unittest.mock import patch


ACTION_HEADERS = {"X-Workbench-Request": "1"}


@patch("app.api.embedding_configs.get_secret", return_value=None)
def test_create_embedding_config_keeps_key_write_only(get_secret, client):
    with patch("app.api.embedding_configs.set_secret") as set_secret:
        response = client.post(
            "/api/embedding-configs",
            headers=ACTION_HEADERS,
            json={
                "name": "Embedding API",
                "provider": "OpenAI Compatible",
                "base_url": "https://example.com/v1",
                "model_name": "embedding-model",
                "dimension": 1024,
                "api_key": "secret-value",
                "is_default": True,
            },
        )

    assert response.status_code == 201
    assert response.json()["dimension"] == 1024
    assert "api_key" not in response.json()
    set_secret.assert_called_once()
    assert get_secret.called


def test_vector_index_requires_embedding_config(client):
    response = client.post(
        "/api/infrastructure/index/start",
        headers=ACTION_HEADERS,
        json={"max_chunks": 100, "batch_size": 16},
    )

    assert response.status_code == 409
    assert "Embedding" in response.json()["detail"]
