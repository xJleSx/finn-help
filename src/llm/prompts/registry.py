from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

_YAML_DIR = Path(__file__).resolve().parent / "yaml"

_REGISTRY: dict[str, dict[str, Any]] = {}
_ACTIVE_VERSIONS: dict[str, int] = {}


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_all() -> None:
    if not _YAML_DIR.exists():
        logger.warning("Prompt YAML directory not found: %s", _YAML_DIR)
        return
    for yaml_path in _YAML_DIR.glob("*.yaml"):
        try:
            data = _load_yaml(yaml_path)
            prompt_id = data.get("id")
            version = data.get("version", 1)
            if prompt_id and (prompt_id not in _REGISTRY or version > _ACTIVE_VERSIONS.get(prompt_id, 0)):
                    _REGISTRY[prompt_id] = data
                    _ACTIVE_VERSIONS[prompt_id] = version
                    logger.debug("Loaded prompt %s v%d", prompt_id, version)
        except Exception as e:
            logger.warning("Failed to load %s: %s", yaml_path, e)


def get_prompt(prompt_id: str, version: Optional[int] = None) -> Optional[dict[str, Any]]:
    if not _REGISTRY:
        _load_all()
    if version is not None:
        for data in _REGISTRY.values():
            if data.get("id") == prompt_id and data.get("version") == version:
                return data
        return None
    return _REGISTRY.get(prompt_id)


def get_system_prompt(prompt_id: str, **kwargs: Any) -> str:
    data = get_prompt(prompt_id)
    if data is None:
        logger.warning("Prompt %s not found in registry", prompt_id)
        return ""
    prompt = data.get("system_prompt", "")
    if kwargs:
        try:
            return prompt.format(**kwargs)
        except KeyError as e:
            logger.warning("Prompt %s missing key: %s", prompt_id, e)
            return prompt
    return prompt


def get_few_shot(prompt_id: str) -> list[dict[str, Any]]:
    data = get_prompt(prompt_id)
    if data is None:
        return []
    return data.get("few_shot", [])


def list_prompts() -> list[dict[str, Any]]:
    if not _REGISTRY:
        _load_all()
    return [
        {
            "id": data.get("id"),
            "version": data.get("version"),
            "description": data.get("description"),
        }
        for data in _REGISTRY.values()
    ]


def reload() -> None:
    _REGISTRY.clear()
    _ACTIVE_VERSIONS.clear()
    _load_all()
