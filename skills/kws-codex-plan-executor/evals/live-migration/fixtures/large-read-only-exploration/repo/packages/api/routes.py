from packages.core.service import describe


def get_summary() -> dict[str, str]:
    return describe()
