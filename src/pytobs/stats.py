"""Local learning stats for the progress screen. Stored in one small JSON file; nothing leaves the machine."""

from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass, field

from .paths import atomic_write, data_dir

IDLE_LIMIT = 120.0  # seconds without activity after which time stops counting


def _today() -> str:
    return dt.date.today().isoformat()


@dataclass
class Summary:
    streak: int
    runs_week: int
    seconds_week: int
    fixed_total: int
    heat: list[list[int]]  # [weekday 0=Mon][week], oldest week first; run counts
    top_errors: list[tuple[str, int, str]]  # (type, count, concept)
    weeks: int


@dataclass
class Stats:
    days: dict[str, dict[str, int]] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)
    concepts: dict[str, str] = field(default_factory=dict)
    failing: dict[str, str] = field(default_factory=dict)  # file -> error type, until a clean run
    _last_touch: float = 0.0
    _dirty: bool = False

    @staticmethod
    def path():
        return data_dir() / "stats.json"

    @classmethod
    def load(cls) -> Stats:
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(
            days={k: dict(v) for k, v in data.get("days", {}).items()},
            errors=dict(data.get("errors", {})),
            concepts=dict(data.get("concepts", {})),
            failing=dict(data.get("failing", {})),
        )

    def save(self) -> None:
        if not self._dirty:
            return
        payload = {
            "days": self.days,
            "errors": self.errors,
            "concepts": self.concepts,
            "failing": self.failing,
        }
        try:
            atomic_write(self.path(), json.dumps(payload))
            self._dirty = False
        except OSError:
            pass

    def _day(self, date: str | None = None) -> dict[str, int]:
        day = self.days.setdefault(date or _today(), {})
        for key in ("runs", "errors", "fixed", "seconds"):
            day.setdefault(key, 0)
        return day

    def touch(self, now: float | None = None) -> None:
        """Call on every edit or run; counts active coding time."""
        now = time.monotonic() if now is None else now
        if self._last_touch and 0 < now - self._last_touch <= IDLE_LIMIT:
            self._day()["seconds"] += int(round(now - self._last_touch))
            self._dirty = True
        self._last_touch = now

    def record_run(self, file: str, error_type: str | None, concept: str | None = None) -> None:
        day = self._day()
        day["runs"] += 1
        if error_type:
            day["errors"] += 1
            self.errors[error_type] = self.errors.get(error_type, 0) + 1
            if concept:
                self.concepts[error_type] = concept
            self.failing[file] = error_type
        elif file in self.failing:
            day["fixed"] += 1
            del self.failing[file]
        self._dirty = True
        self.touch()

    def summary(self, weeks: int = 16, today: dt.date | None = None) -> Summary:
        today = today or dt.date.today()

        def runs(d: dt.date) -> int:
            return self.days.get(d.isoformat(), {}).get("runs", 0)

        streak = 0
        day = today if runs(today) else today - dt.timedelta(days=1)
        while runs(day):
            streak += 1
            day -= dt.timedelta(days=1)
        week_start = today - dt.timedelta(days=today.weekday())
        this_week = [week_start + dt.timedelta(days=i) for i in range(7)]
        runs_week = sum(runs(d) for d in this_week)
        seconds_week = sum(self.days.get(d.isoformat(), {}).get("seconds", 0) for d in this_week)
        fixed_total = sum(v.get("fixed", 0) for v in self.days.values())
        first_monday = week_start - dt.timedelta(weeks=weeks - 1)
        heat = [[runs(first_monday + dt.timedelta(weeks=w, days=d)) for w in range(weeks)] for d in range(7)]
        top = sorted(self.errors.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        top_errors = [(name, n, self.concepts.get(name, "")) for name, n in top]
        return Summary(streak, runs_week, seconds_week, fixed_total, heat, top_errors, weeks)


def level(runs: int) -> int:
    """Heat-map shade 0–4 for a day's run count."""
    if runs <= 0:
        return 0
    if runs <= 2:
        return 1
    if runs <= 5:
        return 2
    if runs <= 10:
        return 3
    return 4


def fmt_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h{m:02d}" if h else f"{m}m"
