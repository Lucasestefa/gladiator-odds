"""
Cache en memoria con TTL — evita requests redundantes a The Odds API.
Con 10min TTL: 1.000 usuarios simultáneos = 1 request cada 10 min.
"""
import time
from typing import Any, Optional, Dict

class MemoryCache:
    def __init__(self):
        self._store: Dict[str, dict] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if not entry:
            return None
        if time.time() > entry["expires_at"]:
            del self._store[key]
            return None
        return entry["value"]

    def set(self, key: str, value: Any, ttl_seconds: int = 600):
        self._store[key] = {
            "value": value,
            "expires_at": time.time() + ttl_seconds,
            "cached_at": time.time(),
        }

    def delete(self, key: str):
        self._store.pop(key, None)

    def stats(self):
        now = time.time()
        active = {k: v for k, v in self._store.items() if now <= v["expires_at"]}
        return {
            "total_keys": len(self._store),
            "active_keys": len(active),
            "keys": list(active.keys()),
        }

# Singleton global
cache = MemoryCache()
