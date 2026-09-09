from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from railife.models.sleep import SLEEP_STATES, SleepSample


DATE_FORMAT = "%d %b %Y at %H:%M"


class SleepParseError(ValueError):
    """Raised when a sleep export line cannot be parsed."""


class ZeroDurationSleepSample(ValueError):
    """Raised for zero-minute Apple Health samples that do not affect totals."""


def parse_sleep_line(
    line: str,
    *,
    line_number: int,
    source_file: str,
    timezone: ZoneInfo,
) -> SleepSample:
    raw_line = line.rstrip("\n")
    parse_line = raw_line.replace("｜", "|")
    parts = [part.strip() for part in parse_line.split("|")]

    if len(parts) == 3:
        source = None
        state, start_text, end_text = parts
    elif len(parts) == 4:
        source, state, start_text, end_text = parts
        source = source or None
    else:
        raise SleepParseError(
            f"{source_file}:{line_number}: expected 3 or 4 fields, found {len(parts)}"
        )

    if state not in SLEEP_STATES:
        raise SleepParseError(f"{source_file}:{line_number}: unknown sleep state {state!r}")

    try:
        start = datetime.strptime(start_text, DATE_FORMAT).replace(tzinfo=timezone)
        end = datetime.strptime(end_text, DATE_FORMAT).replace(tzinfo=timezone)
    except ValueError as exc:
        raise SleepParseError(f"{source_file}:{line_number}: invalid datetime") from exc

    if end == start:
        raise ZeroDurationSleepSample(f"{source_file}:{line_number}: zero-duration sample")

    if end < start:
        raise SleepParseError(f"{source_file}:{line_number}: end must be after start")

    return SleepSample(
        state=state,
        start=start,
        end=end,
        line_number=line_number,
        raw_line=raw_line,
        source_file=source_file,
        source=source,
    )


def parse_sleep_file(path: Path, *, timezone_name: str) -> list[SleepSample]:
    timezone = ZoneInfo(timezone_name)
    samples: list[SleepSample] = []
    errors: list[str] = []

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                samples.append(
                    parse_sleep_line(
                        line,
                        line_number=line_number,
                        source_file=path.name,
                        timezone=timezone,
                    )
                )
            except SleepParseError as exc:
                errors.append(str(exc))
            except ZeroDurationSleepSample:
                continue

    if errors:
        raise SleepParseError("\n".join(errors))

    return sorted(samples, key=lambda sample: (sample.start, sample.end, sample.line_number))
