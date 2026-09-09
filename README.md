# RaiLife

RaiLife is a small personal project I started to make sense of the bits of data I collect in everyday life.

It began with a fairly simple problem: I had sleep data from Apple Health, activity data from Health Auto Export, daily notes in Notion, and weekly reports that I was putting together separately. I wanted one place where I could clean up that data and turn it into something I could actually use.

So this repository is slowly becoming that place.

I’m also using RaiLife as a way to learn Python, Git, and automation through something I genuinely need, rather than through isolated exercises. I build it with the help of Codex, and I’m still figuring things out as the project grows.

## What it does

At the moment, RaiLife can process sleep and activity data, keep selected ChatGPT excerpts, generate weekly aggregates and figures, and sync some of the results to Notion.

The general flow looks like this:

```text
raw data
   ↓
normalization
   ↓
daily JSON
   ↓
weekly aggregation
   ↓
Notion / figures / weekly reports
```

The real personal data is kept locally and is not included in this repository.

## Sleep

Sleep data comes from Apple Health exports created with an iPhone Shortcut.

The normalizer keeps a copy of the raw export, parses individual sleep samples, groups them into sessions, and writes one normalized JSON file for each day. A sleep session belongs to the calendar date on which it ends.

It also handles overlapping exports, so importing the same sleep samples again does not create duplicates.

Normalized files follow this structure:

```text
data/normalized/sleep/YYYY-MM-DD.json
```

Weekly sleep data can then be generated from the daily files:

```sh
PYTHONPATH=src python3 -m railife.pipelines.aggregate_sleep_week \
  --week-label "Week 01" \
  --start-date YYYY-MM-DD \
  --end-date YYYY-MM-DD
```

Missing days are kept explicit rather than silently disappearing from the week.

## Activity

Activity data currently comes from Health Auto Export.

Steps and workouts are imported separately and normalized into daily activity files:

```text
data/normalized/activity/YYYY-MM-DD.json
```

Workout time series are stored separately so the daily files stay reasonably small:

```text
data/normalized/activity/workout_details/YYYY-MM-DD/{workout_id}.json
```

The activity pipeline currently handles daily steps, workouts, heart-rate data, energy, distance, and some other workout details.

Repeated imports are deduplicated when they contain the same data. If two imports disagree about something that should have a single value, the pipeline raises an error instead of quietly choosing one.

## ChatGPT excerpts

I sometimes want to keep a small part of a ChatGPT conversation together with the rest of my daily records.

RaiLife has a simple format for saving excerpts that I explicitly choose. It is not intended to archive my full ChatGPT history.

Excerpt files live locally under:

```text
data/raw/chatgpt/excerpts/
```

An excerpt can stay private or be marked as a possible source for a future weekly report.

The actual excerpts are private and are not included in this repository.

## Weekly reports

RaiLife can combine normalized daily data into weekly aggregates and generate data and figures for my weekly reports.

This part of the project is still evolving. Eventually I want the path from daily records to the finished report to require as little repetitive work as possible, while still leaving the writing itself under my control.

## Notion

Some pipelines can write processed information back into my Notion daily records.

For example, activity data can be inserted into the appropriate daily page without replacing the parts I wrote myself. The sync logic is designed so that running it again updates the generated section rather than creating duplicate sections.

Credentials and personal Notion data are never stored in this public repository.

## Project structure

```text
src/railife/
├── models/
├── parsers/
└── pipelines/

tests/
data/
```

`models` contains the data structures, `parsers` deal with source formats, and `pipelines` handle the steps that turn source data into useful outputs.

The `data` directory in this repository only contains placeholders. My actual health data, reports, notes, and generated files stay local.

## Tests

The test suite can be run with:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Status

RaiLife is very much a work in progress.

I’m building it around my own routine, so its structure changes whenever I find a better way to record or use something. For now, that is part of the point.
