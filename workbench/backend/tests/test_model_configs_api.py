from unittest.mock import patch


ACTION_HEADERS = {"X-Workbench-Request": "1"}


@patch("app.api.model_configs.get_secret", return_value=None)
def test_create_model_config_never_returns_api_key(get_secret, client):
    with patch("app.api.model_configs.set_secret") as set_secret:
        response = client.post(
            "/api/model-configs",
            headers=ACTION_HEADERS,
            json={
                "name": "AIHubMix",
                "provider": "AIHubMix",
                "base_url": "https://aihubmix.com/v1",
                "model_name": "gpt-6-sol",
                "api_key": "secret-value",
                "is_default": True,
            },
        )

    assert response.status_code == 201
    assert "api_key" not in response.json()
    set_secret.assert_called_once()
    assert get_secret.called


@patch("app.api.model_configs.get_secret", return_value="configured")
def test_update_model_config_keeps_key_write_only(get_secret, client):
    with patch("app.api.model_configs.set_secret"):
        created = client.post(
            "/api/model-configs",
            headers=ACTION_HEADERS,
            json={
                "name": "First",
                "provider": "Compatible",
                "base_url": "https://example.com/v1",
                "model_name": "model-a",
                "api_key": "secret-value",
                "is_default": True,
            },
        ).json()

    response = client.put(
        f"/api/model-configs/{created['id']}",
        headers=ACTION_HEADERS,
        json={
            "name": "Updated",
            "provider": "Compatible",
            "base_url": "https://example.com/v1",
            "model_name": "model-b",
            "is_default": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["model_name"] == "model-b"
    assert response.json()["has_api_key"] is True
    assert "configured" not in response.text
    assert get_secret.called
