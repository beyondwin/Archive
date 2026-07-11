from packages.api.routes import get_summary


def render() -> str:
    return str(get_summary())
