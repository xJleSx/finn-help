import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL = 3600  # 1 hour default


class CachedCollector:
    def __init__(self, collector, name: str = "default", ttl: int = CACHE_TTL):
        self._collector = collector
        self._name = name
        self._ttl = ttl
        self._dir = CACHE_DIR / name
        self._dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, key: str) -> Path:
        safe_key = key.replace("/", "_").replace("?", "_").replace("&", "_")
        return self._dir / f"{safe_key}.json"

    def _is_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        age = time.time() - path.stat().st_mtime
        return age < self._ttl

    def _read_cache(self, path: Path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _write_cache(self, path: Path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, default=str)

    async def get(self, key: str, fetcher, ttl: Optional[int] = None) -> dict:
        path = self._cache_path(key)
        actual_ttl = ttl if ttl is not None else self._ttl

        # check cache
        if path.exists():
            age = time.time() - path.stat().st_mtime
            if age < actual_ttl:
                logger.debug("Cache HIT %s/%s (age=%.0fs)", self._name, key, age)
                return self._read_cache(path)
            logger.debug("Cache STALE %s/%s (age=%.0fs > %ds)", self._name, key, age, actual_ttl)
        else:
            logger.debug("Cache MISS %s/%s", self._name, key)

        # fetch
        try:
            data = await fetcher()
            self._write_cache(path, data)
            logger.info("Cache SET %s/%s", self._name, key)
            return data
        except Exception as e:
            # fallback to stale cache
            if path.exists():
                logger.warning("Fetch failed for %s/%s, using stale cache: %s", self._name, key, e)
                return self._read_cache(path)
            raise

    def clear(self, key: Optional[str] = None):
        if key:
            path = self._cache_path(key)
            if path.exists():
                path.unlink()
                logger.info("Cache CLEAR %s/%s", self._name, key)
        else:
            for f in self._dir.iterdir():
                f.unlink()
            logger.info("Cache CLEAR ALL %s", self._name)

    def stats(self) -> dict:
        files = list(self._dir.iterdir()) if self._dir.exists() else []
        return {
            "name": self._name,
            "files": len(files),
            "size_mb": sum(f.stat().st_size for f in files) / (1024 * 1024),
        }
