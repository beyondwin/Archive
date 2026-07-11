_draft = {}


def save_draft(session_id: str, text: str) -> None:
    _draft["text"] = text


def load_draft(session_id: str) -> str | None:
    return _draft.get("text")
