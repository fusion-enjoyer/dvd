import pytest


@pytest.fixture(autouse=True)
def own_settings(tmp_path_factory, monkeypatch):
    """Every test reads and writes its own settings and queue files, never the user's."""
    home = tmp_path_factory.mktemp("settings")
    monkeypatch.setenv("DVD_SETTINGS", str(home / "settings.yaml"))
    monkeypatch.setenv("DVD_QUEUE", str(home / "queue.yaml"))
