import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import cloudpickle  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

_MODEL_DIR_ENV_OVERRIDE = None


def _get_model_dir() -> Path:
    if _MODEL_DIR_ENV_OVERRIDE:
        return Path(_MODEL_DIR_ENV_OVERRIDE)
    return Path(__file__).resolve().parents[2] / "data" / "models"


MODEL_DIR = _get_model_dir()
MODEL_DIR.mkdir(parents=True, exist_ok=True)

REGISTRY_FILE = MODEL_DIR / "registry.json"


def set_model_dir(path: str | Path) -> None:
    global MODEL_DIR, REGISTRY_FILE, _MODEL_DIR_ENV_OVERRIDE  # noqa: PLW0603
    _MODEL_DIR_ENV_OVERRIDE = str(path)
    MODEL_DIR = Path(path)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE = MODEL_DIR / "registry.json"


def _load_registry() -> dict[str, Any]:
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load registry: %s", e)
            return {}
    return {}


def _save_registry(registry: dict[str, Any]) -> None:
    REGISTRY_FILE.write_text(json.dumps(registry, indent=2, ensure_ascii=False))


def save_model(
    model: Any, name: str,
    metrics: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
) -> str:
    version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    model_path = MODEL_DIR / f"{name}__{version}.pkl"
    meta = {
        "name": name,
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics or {},
        "params": params or {},
        "path": str(model_path),
    }

    with open(model_path, "wb") as f:
        cloudpickle.dump(model, f)

    model_hash = hashlib.md5(model_path.read_bytes()).hexdigest()
    meta["hash"] = model_hash

    registry = _load_registry()
    if name not in registry:
        registry[name] = {"versions": [], "latest": None}
    registry[name]["versions"].append(meta)
    registry[name]["latest"] = version
    _save_registry(registry)

    logger.info("Model %s version %s saved (hash=%s)", name, version, model_hash[:8])
    return version


async def save_model_async(
    model: Any, name: str,
    metrics: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, save_model, model, name, metrics, params)


def load_model(name: str, version: Optional[str] = None) -> Any:
    registry = _load_registry()
    if name not in registry:
        raise ValueError(f"Model '{name}' not found in registry")

    versions = registry[name]["versions"]
    if version is None:
        version = registry[name]["latest"]

    meta = next((v for v in versions if v["version"] == version), None)
    if not meta:
        raise ValueError(f"Version '{version}' not found for model '{name}'")

    path = Path(meta["path"])
    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {path}")

    if "hash" in meta:
        actual_hash = hashlib.md5(path.read_bytes()).hexdigest()
        if actual_hash != meta["hash"]:
            raise ValueError(
                f"Model hash mismatch for '{name}' version {version}: expected {meta['hash']}, got {actual_hash}"
            )

    with open(path, "rb") as f:
        model = cloudpickle.load(f)

    logger.info("Model %s version %s loaded (hash verified)", name, version)
    return model


async def load_model_async(name: str, version: Optional[str] = None) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, load_model, name, version)


def list_models() -> list[dict[str, Any]]:
    registry = _load_registry()
    result = []
    for name, data in registry.items():
        latest = data["latest"]
        meta = next((v for v in data["versions"] if v["version"] == latest), None)
        result.append(
            {
                "name": name,
                "latest_version": latest,
                "versions_count": len(data["versions"]),
                "created_at": meta["created_at"] if meta else None,
                "metrics": meta["metrics"] if meta else {},
            }
        )
    return result


def get_model_metrics(name: str, version: Optional[str] = None) -> dict[str, Any]:
    registry = _load_registry()
    if name not in registry:
        return {}
    versions = registry[name]["versions"]
    if version is None:
        version = registry[name]["latest"]
    meta = next((v for v in versions if v["version"] == version), None)
    return meta["metrics"] if meta else {}


def delete_model(name: str, version: Optional[str] = None) -> None:
    registry = _load_registry()
    if name not in registry:
        return

    if version is None:
        for v in registry[name]["versions"]:
            p = Path(v["path"])
            if p.exists():
                p.unlink()
        del registry[name]
    else:
        versions = registry[name]["versions"]
        meta = next((v for v in versions if v["version"] == version), None)
        if meta:
            p = Path(meta["path"])
            if p.exists():
                p.unlink()
            registry[name]["versions"] = [v for v in versions if v["version"] != version]
            if registry[name]["latest"] == version:
                remaining = registry[name]["versions"]
                registry[name]["latest"] = remaining[-1]["version"] if remaining else None
            if not registry[name]["versions"]:
                del registry[name]

    _save_registry(registry)
    logger.info("Model %s version %s deleted", name, version or "all")


def cleanup_old_versions(name: str, keep: int = 3) -> None:
    registry = _load_registry()
    if name not in registry:
        return
    versions = sorted(registry[name]["versions"], key=lambda v: v["version"], reverse=True)
    if len(versions) <= keep:
        return
    for v in versions[keep:]:
        p = Path(v["path"])
        if p.exists():
            p.unlink()
    registry[name]["versions"] = versions[:keep]
    registry[name]["latest"] = versions[0]["version"]
    _save_registry(registry)
    logger.info("Cleaned up %s old versions of %s, keeping %s", len(versions) - keep, name, keep)
