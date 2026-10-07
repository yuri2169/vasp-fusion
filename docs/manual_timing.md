# Timing the task by hand

The tool's own time is measured (`make intake-timing`, `make freeze-readiness`, the live
seconds per trace on the Model page). The time the same work takes a person with a block
explorer has **not** been measured, so the tool claims no time saved. This sheet is how to
measure it. **It must be done by a person, with a clock, and written down as it happened.**
Until a filled sheet is in `artifacts/manual_timing/`, the coverage row "reduce
investigation time" stays partly built and says the timing is pending.

## Who

A team member who did **not** build the tracing and has **not** looked at the recorded
cases (`demo/cases.json`, the demo's `/cases` screen, the case files). Knowing the answer
makes the timing worthless. Write on the sheet who you are and how much tracing you have
done before.

## The task (the same for each of the five wallets)

> Using only a public block explorer in a browser, find the nearest exchange that
> received deposits from this wallet: the exchange's name, the address at the exchange
> that the money arrived at, and one transaction hash on the route. "Nearest" means the
> fewest transfers away.

Allowed: the explorer named on the sheet for that chain, its own name tags, and following
transfers by clicking. Not allowed: this tool, any paid tracing product, an AI assistant,
asking someone who knows.

## How

1. Open `artifacts/manual_timing/sheet.csv` in a spreadsheet. One row per wallet, in order.
2. For each row: write the clock time in `started_at` (HH:MM:SS), paste the wallet into
   the explorer, and work. Do not pause the clock for anything.
3. Stop when you have an answer you would put in a report, or when **30 minutes** have
   passed. Write `stopped_at`, the whole `minutes` spent (to one decimal place), and:
   - `answer_exchange`, `answer_deposit_address`, `answer_tx_hash`: what you found, or blank;
   - `how_sure_1_to_5`: 1 = a guess, 5 = you would sign it;
   - `gave_up`: `yes` if you stopped without an answer or hit 30 minutes;
   - `notes`: what slowed you down (pagination, no name tag, too many transfers, …).
4. Do all five in one sitting if you can; note any break in `notes`.
5. Do not look up the recorded answers until all five rows are filled. Do not go back and
   change a row afterwards.

## What happens with it

Send the filled sheet back unedited. It is kept as it is in `artifacts/manual_timing/`
with who timed it, on what date, and the sample size (five wallets, one person), and the
tool's page then shows the tool's time beside the manual time for the same five wallets:
the median minutes by hand, how many of the five were answered, and how many answers match
the recorded case. Five wallets timed by one person is a first measurement. It will be
described as exactly that.
