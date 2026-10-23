import os

from app.config import get_settings


def normalize_proxy(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if ";" in value or "=" in value:
        entries = {}
        for item in value.split(";"):
            if "=" in item:
                protocol, address = item.split("=", 1)
                entries[protocol.casefold().strip()] = address.strip()
        value = entries.get("https") or entries.get("http") or ""
    if not value:
        return None
    return value if "://" in value else f"http://{value}"


def windows_system_proxy() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
            if not enabled:
                return None
            raw = winreg.QueryValueEx(key, "ProxyServer")[0]
    except (OSError, ValueError):
        return None
    return normalize_proxy(str(raw))


def outbound_proxy() -> str | None:
    configured = get_settings().outbound_proxy_url
    return normalize_proxy(configured) if configured else windows_system_proxy()
