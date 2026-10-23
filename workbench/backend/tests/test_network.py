from types import SimpleNamespace
from unittest.mock import patch

from app.network import normalize_proxy, outbound_proxy


def test_normalize_proxy_supports_windows_protocol_map():
    assert normalize_proxy("http=127.0.0.1:7890;https=127.0.0.1:7891") == (
        "http://127.0.0.1:7891"
    )
    assert normalize_proxy("127.0.0.1:7890") == "http://127.0.0.1:7890"


def test_explicit_proxy_overrides_system_detection():
    with (
        patch(
            "app.network.get_settings",
            return_value=SimpleNamespace(outbound_proxy_url="http://proxy.example:8080"),
        ),
        patch("app.network.windows_system_proxy") as system_proxy,
    ):
        assert outbound_proxy() == "http://proxy.example:8080"

    system_proxy.assert_not_called()
