import pytest

from backend.blocks.conference_paper.urls import parse_arxiv_id


@pytest.fixture(scope="session", autouse=True)
def graph_cleanup() -> None:
    return None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://arxiv.org/abs/2503.21761", "2503.21761"),
        ("https://arxiv.org/pdf/2503.21761v2.pdf", "2503.21761"),
        ("https://export.arxiv.org/abs/cs/9901001v1", "cs/9901001"),
        ("https://arxiv.org/pdf/math.GT/0309136", "math.GT/0309136"),
    ],
)
def test_parse_arxiv_id_accepts_supported_urls(url: str, expected: str):
    assert parse_arxiv_id(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://arxiv.org/abs/2503.21761",
        "https://user@arxiv.org/abs/2503.21761",
        "https://evil.example/abs/2503.21761",
        "https://arxiv.org.evil.example/abs/2503.21761",
        "https://arxiv.org/abs/not-an-id",
        "https://arxiv.org/search/2503.21761",
        "https://arxiv.org/abs/2503.21761/extra",
        "https://arxiv.org/abs/%2e%2e/2503.21761",
    ],
)
def test_parse_arxiv_id_rejects_unsafe_or_invalid_urls(url: str):
    with pytest.raises(ValueError, match="^INVALID_ARXIV_URL$"):
        parse_arxiv_id(url)
