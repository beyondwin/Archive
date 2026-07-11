from packages.store.repository import repository_kind


def describe() -> dict[str, str]:
    return {"owner": "core", "store": repository_kind()}
