from app.core.history import record_operation, load_history, clear_history


def test_history_roundtrip(app, tmp_path, monkeypatch):
    from app.core.settings import AppSettings
    import app.core.history as hist

    # Point history file into tmp_path via QSettings override.
    settings = AppSettings()
    monkeypatch.setattr(hist, "_history_path", lambda s: str(tmp_path / "hist.json"))

    clear_history(settings)
    rec = record_operation(settings, "copy", "C:\\src", "複製 3 個檔案", 3, 0, 1024)
    assert rec["id"] == 1
    history = load_history(settings)
    assert len(history) == 1
    assert history[0]["module"] == "copy"

    record_operation(settings, "remove", "C:\\x", "刪除", 1, 0, 0)
    assert len(load_history(settings)) == 2

    clear_history(settings)
    assert load_history(settings) == []
