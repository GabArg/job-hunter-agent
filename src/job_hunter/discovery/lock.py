from __future__ import annotations

import json
import os
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path


class DiscoveryAlreadyRunning(RuntimeError): pass


class DiscoveryLock(AbstractContextManager):
    def __init__(self, path: str | Path): self.path = Path(path); self.acquired = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and not self._stale():
            raise DiscoveryAlreadyRunning(f"Discovery already running (lock: {self.path})")
        if self.path.exists(): self.path.unlink()
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise DiscoveryAlreadyRunning(f"Discovery already running (lock: {self.path})") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "created_at": datetime.now(timezone.utc).isoformat()}, handle)
        self.acquired = True; return self

    def __exit__(self, *_):
        if self.acquired and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if int(data.get("pid", -1)) == os.getpid(): self.path.unlink()
            except (OSError, ValueError, json.JSONDecodeError): pass
        self.acquired = False

    def _stale(self) -> bool:
        try: pid = int(json.loads(self.path.read_text(encoding="utf-8"))["pid"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError): return True
        if pid == os.getpid(): return False
        try: os.kill(pid, 0)
        except (OSError, ProcessLookupError): return True
        return False
