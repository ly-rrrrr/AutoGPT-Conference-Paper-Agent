import re
from urllib.parse import ParseResult, unquote, urljoin, urlparse

CVF_HOSTS = frozenset({"openaccess.thecvf.com"})
ARXIV_HOSTS = frozenset({"arxiv.org", "export.arxiv.org"})
ARXIV_ID_PATTERN = re.compile(
    r"^(?:\d{4}\.\d{4,5}|[A-Za-z][A-Za-z0-9.-]*/\d{7})(?:v\d+)?$"
)


def require_https_host(
    url: str,
    hosts: frozenset[str],
    error_code: str,
) -> ParseResult:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError(error_code) from error
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise ValueError(error_code)
    return parsed


def resolve_cvf_url(base_url: str, href: str) -> str:
    require_https_host(base_url, CVF_HOSTS, "INVALID_CVF_URL")
    resolved = urljoin(base_url, href)
    parsed = require_https_host(resolved, CVF_HOSTS, "INVALID_CVF_URL")
    return parsed._replace(fragment="").geturl()


def parse_arxiv_id(url: str) -> str:
    parsed = require_https_host(url, ARXIV_HOSTS, "INVALID_ARXIV_URL")
    if parsed.query or parsed.fragment:
        raise ValueError("INVALID_ARXIV_URL")
    encoded_parts = [part for part in parsed.path.split("/") if part]
    parts = [unquote(part) for part in encoded_parts]
    if any("/" in part or "\\" in part or part in {".", ".."} for part in parts):
        raise ValueError("INVALID_ARXIV_URL")
    if len(parts) not in {2, 3} or parts[0] not in {"abs", "pdf"}:
        raise ValueError("INVALID_ARXIV_URL")
    candidate = "/".join(parts[1:])
    if parts[0] == "pdf":
        candidate = candidate.removesuffix(".pdf")
    if ARXIV_ID_PATTERN.fullmatch(candidate) is None:
        raise ValueError("INVALID_ARXIV_URL")
    return re.sub(r"v\d+$", "", candidate)
