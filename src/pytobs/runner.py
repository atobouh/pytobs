"""Run the user's script in its own process and stream its output."""

from __future__ import annotations

import asyncio
import codecs
import os
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from .paths import IS_WINDOWS

OutputCallback = Callable[[str, str], None]  # (text, "stdout" | "stderr")
ExitCallback = Callable[[int, float], None]  # (exit code, seconds)


class Run:
    """One execution of a script. Create, then `await start()`."""

    def __init__(
        self,
        python: str,
        script: Path,
        on_output: OutputCallback,
        on_exit: ExitCallback,
    ) -> None:
        self.python = python
        self.script = script
        self.on_output = on_output
        self.on_exit = on_exit
        self.process: asyncio.subprocess.Process | None = None
        self.started_at = 0.0
        self.finished = False
        self._pumps: list[asyncio.Task[None]] = []
        self._waiter: asyncio.Task[None] | None = None

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at if self.started_at else 0.0

    async def start(self) -> None:
        env = dict(os.environ)
        env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        kwargs: dict[str, object] = {}
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self.started_at = time.perf_counter()
        try:
            self.process = await asyncio.create_subprocess_exec(
                self.python,
                "-u",
                str(self.script),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.script.parent),
                env=env,
                **kwargs,  # type: ignore[arg-type]
            )
        except OSError as exc:
            self.finished = True
            self.on_output(f"Could not start {self.python}: {exc}\n", "stderr")
            self.on_exit(-1, self.elapsed)
            return
        assert self.process.stdout and self.process.stderr
        self._pumps = [
            asyncio.create_task(self._pump(self.process.stdout, "stdout")),
            asyncio.create_task(self._pump(self.process.stderr, "stderr")),
        ]
        self._waiter = asyncio.create_task(self._wait())

    async def _pump(self, stream: asyncio.StreamReader, name: str) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while True:
            chunk = await stream.read(8192)
            if not chunk:
                tail = decoder.decode(b"", final=True)
                if tail:
                    self.on_output(tail, name)
                return
            text = decoder.decode(chunk)
            if text:
                self.on_output(text.replace("\r\n", "\n"), name)

    async def _wait(self) -> None:
        assert self.process
        code = await self.process.wait()
        await asyncio.gather(*self._pumps, return_exceptions=True)
        self.finished = True
        self.on_exit(code, self.elapsed)

    def send_input(self, text: str) -> None:
        if self.process and self.process.stdin and not self.finished:
            try:
                self.process.stdin.write(text.encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError, RuntimeError):
                pass

    def close_input(self) -> None:
        if self.process and self.process.stdin and not self.finished:
            try:
                self.process.stdin.close()
            except (BrokenPipeError, ConnectionResetError, RuntimeError):
                pass

    async def stop(self, grace: float = 1.0) -> None:
        """Interrupt politely, then end the whole process tree."""
        proc = self.process
        if not proc or self.finished:
            return
        try:
            if IS_WINDOWS:
                proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                os.killpg(proc.pid, signal.SIGINT)
        except (ProcessLookupError, OSError):
            pass
        try:
            await asyncio.wait_for(proc.wait(), grace)
            return
        except asyncio.TimeoutError:
            pass
        try:
            if IS_WINDOWS:
                await asyncio.to_thread(
                    subprocess.run,
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
