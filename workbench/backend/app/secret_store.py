import keyring


SERVICE_NAME = "research-workbench-model-providers"


def get_secret(secret_ref: str) -> str | None:
    return keyring.get_password(SERVICE_NAME, secret_ref)


def set_secret(secret_ref: str, value: str) -> None:
    keyring.set_password(SERVICE_NAME, secret_ref, value)
