from pathlib import Path

from picomind.session.manager import SessionManager


def test_session_round_trip_and_clear(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("cli:default")
    session.add_message({"role": "user", "content": "hello"})
    session.add_message({"role": "assistant", "content": "world"})
    manager.save(session)

    loaded = SessionManager(tmp_path).get_or_create("cli:default")
    assert loaded.get_history() == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]

    loaded.clear()
    manager.save(loaded)
    assert loaded.get_history() == []


def test_session_list_uses_metadata(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("cli:project")
    manager.save(session)

    rows = manager.list_sessions()

    assert rows[0]["key"] == "cli:project"
