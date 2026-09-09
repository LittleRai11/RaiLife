# RaiLife

Personal life-data normalization pipelines.

## Apple Health Sleep

The sleep pipeline reads Apple Health sleep sample text files exported by an iPhone Shortcut, copies them into immutable raw snapshots, and writes normalized JSON for later Notion and LaTeX use.

Source files are never modified.

Canonical daily sleep files follow the local calendar date of each sleep session's wake time. Rolling-window exports may contain sessions from multiple dates; the normalizer partitions sessions by that end date, deduplicates samples already present in canonical daily JSON, and writes one `data/normalized/sleep/YYYY-MM-DD.json` file per affected date.

Supported input formats:

```text
Value | Start | End
Source | Value | Start | End
```

Example:

```text
Core | 30 Aug 2026 at 05:58 | 30 Aug 2026 at 06:13
Apple Watch | Core | 30 Aug 2026 at 05:58 | 30 Aug 2026 at 06:13
```

Run from this directory:

```sh
python -m railife.pipelines.normalize_sleep \
  --source-dir "$HOME/Library/Mobile Documents/com~apple~CloudDocs/RaiHealth/sleep" \
  --timezone Asia/Shanghai \
  --session-gap-minutes 90
```

Outputs:

- `data/raw/apple_health/sleep/`: copied raw snapshots named with a SHA-256 prefix
- `data/manifests/raw_files.json`: import manifest with hashes and source metadata
- `data/normalized/sleep/YYYY-MM-DD.json`: normalized daily sleep JSON

Generate a Sunday-to-Saturday weekly aggregate from daily normalized JSON:

```sh
PYTHONPATH=src python3 -m railife.pipelines.aggregate_sleep_week \
  --week-label "Week 01" \
  --start-date 2026-08-30 \
  --end-date 2026-09-05
```

Weekly output is written to `data/aggregates/sleep/` and keeps missing dates explicit.

## Health Auto Export Activity

The activity pipeline reads step and workout JSON files manually exported from Health Auto Export. Source files are copied into immutable raw snapshots before parsing.

Step and workout exports stay separate in the raw layer:

```text
data/raw/health_auto_export/step/
data/raw/health_auto_export/workout/
```

Canonical daily activity files are written to:

```text
data/normalized/activity/YYYY-MM-DD.json
```

Schema version: `activity.daily.v1`

Daily activity records contain nullable daily steps and zero or more workouts. Daily steps come from the Health Auto Export `step_count` daily aggregate; the pipeline does not recompute the daily total from workout or minute-level samples.

Workout detail time series are normalized separately to keep daily files compact:

```text
data/normalized/activity/workout_details/YYYY-MM-DD/{workout_id}.json
```

Supported detail series include:

- `heartRateData`
- `heartRateRecovery`
- `activeEnergy`
- `basalEnergy`
- `stepCount`
- `walkingAndRunningDistance`

Energy values preserve the original source value and unit. When Health Auto Export reports `kJ`, normalized kcal is computed deterministically with `kcal = kJ / 4.184`. Unknown energy units are preserved as source values and are not silently converted.

The v1 merge policy is strict:

- identical re-exports are idempotent
- identical daily step values from multiple exports are accepted
- conflicting daily step values for the same date raise an error
- duplicate workouts with the same stable workout ID and identical raw workout content are deduplicated
- conflicting versions of the same workout ID raise an error

Run from this directory:

```sh
PYTHONPATH=src python3 -m railife.pipelines.normalize_activity \
  --step-source-dir "$HOME/Library/Mobile Documents/com~apple~CloudDocs/RaiHealth/step" \
  --workout-source-dir "$HOME/Library/Mobile Documents/com~apple~CloudDocs/RaiHealth/workout"
```

Outputs:

- `data/raw/health_auto_export/step/`: copied raw step snapshots named with a SHA-256 prefix
- `data/raw/health_auto_export/workout/`: copied raw workout snapshots named with a SHA-256 prefix
- `data/manifests/raw_files.json`: import manifest with hashes, exporter, provider, and source metadata
- `data/normalized/activity/YYYY-MM-DD.json`: compact normalized daily activity JSON
- `data/normalized/activity/workout_details/YYYY-MM-DD/{workout_id}.json`: normalized workout detail series

## ChatGPT Excerpts

RaiLife can keep small ChatGPT conversation excerpts that you explicitly choose to save. This is not a full ChatGPT history archive.

Raw excerpts live in:

```text
data/raw/chatgpt/excerpts/
```

Each excerpt is one JSON file named `YYYY-MM-DD_NNN.json`, for example `2026-09-02_001.json`.

Schema version: `chatgpt.excerpt.v1`

```json
{
  "schema_version": "chatgpt.excerpt.v1",
  "date": "2026-09-02",
  "time": "09:30",
  "title": "RaiLife 睡眠数据更新",
  "topic": "RaiLife",
  "status": "private",
  "user_text": "Your original message, unchanged.",
  "assistant_text": "The assistant reply, unchanged.",
  "notes": ""
}
```

Only two statuses are allowed:

- `private`: private storage only
- `weekly_candidate`: allowed to enter a future weekly-report candidate pool

Default status is always `private`. Use `weekly_candidate` only when explicitly marking an excerpt as a weekly-report candidate.

Manual save example:

```sh
PYTHONPATH=src python3 - <<'PY'
from pathlib import Path
from railife.models.chatgpt_excerpt import build_excerpt, save_excerpt

payload = build_excerpt(
    excerpt_date="2026-09-02",
    title="RaiLife sleep update",
    topic="RaiLife",
    user_text="Paste the original user message here.",
    assistant_text="Paste the original assistant reply here.",
)

path = save_excerpt(payload, excerpts_dir=Path("data/raw/chatgpt/excerpts"))
print(path)
PY
```

Run tests:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```
