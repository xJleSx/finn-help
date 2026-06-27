from __future__ import annotations

import pytest

from src.model_registry import (
    MODEL_DIR,
    REGISTRY_FILE,
    cleanup_old_versions,
    delete_model,
    get_model_metrics,
    list_models,
    load_model,
    save_model,
)


@pytest.fixture(autouse=True)
def temp_model_dir(tmp_path):
    original_model_dir = MODEL_DIR
    original_registry = REGISTRY_FILE
    import src.model_registry as mr

    new_dir = tmp_path / "models"
    new_dir.mkdir(parents=True, exist_ok=True)
    mr.MODEL_DIR = new_dir
    mr.REGISTRY_FILE = new_dir / "registry.json"
    yield
    mr.MODEL_DIR = original_model_dir
    mr.REGISTRY_FILE = original_registry


class TestModelRegistry:
    def test_save_and_load(self):
        model = {"coef": [1.0, 2.0, 3.0], "intercept": 0.5}
        version = save_model(model, "test_model", metrics={"accuracy": 0.95})
        assert version is not None
        assert len(version) > 0

        loaded = load_model("test_model")
        assert loaded["coef"] == [1.0, 2.0, 3.0]
        assert loaded["intercept"] == 0.5

    def test_load_specific_version(self):
        v1 = save_model({"v": 1}, "ver_model", metrics={"acc": 0.8})
        save_model({"v": 2}, "ver_model", metrics={"acc": 0.9})

        loaded_v1 = load_model("ver_model", version=v1)
        assert loaded_v1["v"] == 1

        loaded_latest = load_model("ver_model")
        assert loaded_latest["v"] == 2

    def test_load_nonexistent_model(self):
        with pytest.raises(ValueError, match="not found"):
            load_model("no_such_model")

    def test_load_nonexistent_version(self):
        save_model({"x": 1}, "ver_model")
        with pytest.raises(ValueError, match="not found"):
            load_model("ver_model", version="bad_version")

    def test_list_models(self):
        save_model({"a": 1}, "model_a", metrics={"acc": 0.9})
        save_model({"b": 2}, "model_b", metrics={"acc": 0.8})
        models = list_models()
        names = [m["name"] for m in models]
        assert "model_a" in names
        assert "model_b" in names

    def test_get_model_metrics(self):
        save_model({"x": 1}, "metrics_model", metrics={"f1": 0.87, "precision": 0.9})
        metrics = get_model_metrics("metrics_model")
        assert metrics["f1"] == 0.87
        assert metrics["precision"] == 0.9

    def test_get_model_metrics_nonexistent(self):
        metrics = get_model_metrics("no_model")
        assert metrics == {}

    def test_delete_model(self):
        save_model({"x": 1}, "del_model")
        assert len(list_models()) == 1
        delete_model("del_model")
        assert len(list_models()) == 0

    def test_cleanup_old_versions(self):
        for i in range(5):
            save_model({"i": i}, "clean_model", metrics={"epoch": i})
        cleanup_old_versions("clean_model", keep=2)
        models = list_models()
        m = next(m for m in models if m["name"] == "clean_model")
        assert m["versions_count"] == 2

    def test_hash_verification(self):
        model = {"secret": 42}
        save_model(model, "hash_model")
        loaded = load_model("hash_model")
        assert loaded["secret"] == 42
