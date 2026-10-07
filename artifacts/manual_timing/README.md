# Manual timing: how long the same task takes by hand

**Status: pending. No figure exists yet.** `sheet.csv` is the empty sheet. Nothing in
the tool, the README or the coverage page cites a manual time or a time saved until a
person has filled it in.

When a filled sheet comes back, keep it here as `filled-<date>-<initials>.csv`, unedited,
and add one entry to `results.json` (create it then):

```json
{"timed_by": "<name or initials>", "role": "<e.g. team member, no prior tracing experience>",
 "date": "<YYYY-MM-DD>", "tasks": 5, "completed": 0, "gave_up": 0,
 "minutes": [0, 0, 0, 0, 0], "median_minutes": 0, "correct_exchange": 0,
 "sheet": "filled-<date>-<initials>.csv"}
```

`minutes` are the sheet's own, one per task, in task order; a task the person gave up on
keeps the minutes spent and counts under `gave_up`. `correct_exchange` is how many answers
name the exchange the recorded case names (`demo/cases.json`, `expect.top_vasp`), checked
after the timing, never before. The sample is five wallets and one person: say so beside
any figure, and call it what it is, a first measurement, not a study.

Instructions for the person timing: `docs/manual_timing.md`.
