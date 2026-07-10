"""On-disk TTL cache for anything fetched from the network.

Everything nf-chain knows about a pipeline is fetched live (schemas, release
tags). The cache is what keeps "on the fly" from meaning "on every keystroke".
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_TTL = 60 * 60 * 6  # 6 hours
USER_AGENT = "nf-chain/0.1 (+https://github.com/nextflow-io/nextflow)"


class FetchError(RuntimeError):
    pass


def cache_dir(root: Path) -> Path:
    d = root / ".nfchain" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


def fetch_text(url: str, root: Path, ttl: int = DEFAULT_TTL, refresh: bool = False) -> str:
    """GET `url`, memoised on disk under `root/.nfchain/cache`."""
    path = cache_dir(root) / f"{_key(url)}.txt"
    if not refresh and path.exists() and (time.time() - path.stat().st_mtime) < ttl:
        return path.read_text()

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise FetchError(f"not found: {url}") from e
        raise FetchError(f"HTTP {e.code} fetching {url}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        # Offline? Fall back to a stale cache entry rather than hard-failing:
        # a dev on a plane should still get completions.
        if path.exists():
            return path.read_text()
        raise FetchError(f"cannot reach {url}: {e}") from e

    path.write_text(body)
    return body


def fetch_json(url: str, root: Path, ttl: int = DEFAULT_TTL, refresh: bool = False) -> dict:
    raw = fetch_text(url, root, ttl=ttl, refresh=refresh)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise FetchError(f"malformed JSON from {url}: {e}") from e
