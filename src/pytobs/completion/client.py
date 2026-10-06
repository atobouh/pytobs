"""Talks to the completion worker process."""

from __future__ import annotations

import asyncio
import itertools
import json
import subprocess
import sys
from typing import Any

from ..paths import IS_WINDOWS


class CompletionClient:
    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._reader: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self.python: str | None = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self, python: str) -> None:
        async with self._lock:
            if not self.alive:
                kwargs: dict[str, Any] = {}
                if IS_WINDOWS:
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
                self._proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "pytobs.completion.worker",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=8 * 1024 * 1024,
                    **kwargs,
                )
                self._reader = asyncio.create_task(self._read())
        if python != self.python:
            self.python = python
            await self.request("env", python=python, timeout=30)

    async def _read(self) -> None:
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            fut = self._pending.pop(msg.get("id"), None)
            if fut and not fut.done():
                if "error" in msg:
                    fut.set_result(None)
                else:
                    fut.set_result(msg.get("result"))
        for fut in self._pending.values():
            if not fut.done():
                fut.set_result(None)
        self._pending.clear()

    async def request(self, op: str, timeout: float = 10, **payload: Any) -> Any:
        if not self.alive:
            return None
        assert self._proc and self._proc.stdin
        rid = next(self._ids)
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        self._proc.stdin.write((json.dumps({"id": rid, "op": op, **payload}) + "\n").encode("utf-8"))
        try:
            await self._proc.stdin.drain()
            return await asyncio.wait_for(fut, timeout)
        except (asyncio.TimeoutError, ConnectionError, BrokenPipeError):
            self._pending.pop(rid, None)
            return None

    async def close(self) -> None:
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
