from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


SLEEP_STATES = {"Core", "Deep", "REM", "Awake", "Asleep"}
ASLEEP_STATES = {"Core", "Deep", "REM", "Asleep"}
STAGED_STATES = {"Core", "Deep", "REM"}


@dataclass(frozen=True)
class SleepSample:
    state: str
    start: datetime
    end: datetime
    line_number: int
    raw_line: str
    source_file: str
    source: str | None = None

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)

    def to_json(self) -> dict:
        return {
            "line_number": self.line_number,
            "source_file": self.source_file,
            "source": self.source,
            "state": self.state,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "duration_minutes": self.duration_minutes,
            "raw_line": self.raw_line,
        }


@dataclass(frozen=True)
class SleepSession:
    index: int
    kind: str
    samples: tuple[SleepSample, ...]

    @property
    def start(self) -> datetime:
        return min(sample.start for sample in self.samples)

    @property
    def end(self) -> datetime:
        return max(sample.end for sample in self.samples)

    @property
    def elapsed_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)

    @property
    def asleep_minutes(self) -> int:
        return sum(s.duration_minutes for s in self.samples if s.state in ASLEEP_STATES)

    @property
    def awake_minutes(self) -> int:
        return sum(s.duration_minutes for s in self.samples if s.state == "Awake")

    def stage_minutes(self, state: str) -> int | None:
        if not any(sample.state in STAGED_STATES for sample in self.samples):
            return None
        return sum(s.duration_minutes for s in self.samples if s.state == state)

    @property
    def asleep_unspecified_minutes(self) -> int:
        return sum(s.duration_minutes for s in self.samples if s.state == "Asleep")

    def to_json(self, daily_date: str) -> dict:
        suffix = "main" if self.kind == "main" else f"nap_{self.index}"
        return {
            "id": f"sleep_{daily_date}_{suffix}",
            "kind": self.kind,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "duration_minutes": {
                "elapsed": self.elapsed_minutes,
                "asleep_total": self.asleep_minutes,
                "awake": self.awake_minutes,
                "core": self.stage_minutes("Core"),
                "deep": self.stage_minutes("Deep"),
                "rem": self.stage_minutes("REM"),
                "asleep_unspecified": self.asleep_unspecified_minutes,
            },
            "samples": [sample.to_json() for sample in self.samples],
        }
