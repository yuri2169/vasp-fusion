# Large-volume tracing: what was measured, what limits it, and the path to more

The problem statement asks for a "scalable architecture capable of handling large-volume blockchain transaction analysis". This page says what the tool does about that today, with figures, and where the figures stop.

**Read this first.** Everything under "Measured" comes from a run on one laptop with chain responses replayed from a cache. Everything under "Design" has not been built or measured. The two are never mixed.

## What was built

| Part | What it does | Where |
|---|---|---|
| Durable queue | Every trace (an officer's case, a SAHYOG complaint, a batch) is a row in a table before it runs. A restart loses nothing queued; a claim is exclusive across threads and processes; a job whose process died is queued again, and fails after three tries. | `vaspfusion/store/queue.py` |
| Worker pool | Several processes trace at once. The server process claims jobs and stores results; workers only trace. Off by default: `make serve WORKERS=4` or `VASPFUSION_WORKERS=4`. | `vaspfusion/workers.py` |
| Shared rate limit | One pace per chain-data provider, shared by every worker, so more workers never means more refusals. A refusal (HTTP 429) holds every worker back. | `vaspfusion/chains/ratelimit.py` |
| Shared response cache | A page one case fetched is a cache hit for every later case, in any worker. A replay opens the cache read-only, once. | `vaspfusion/chains/cache.py` |
| Batch intake | `POST /api/cases/batch`: up to 2,000 wallets as CSV or JSON. Bad rows are reported with reasons; the others are queued. Result table on screen and as CSV. | `/batch`, `vaspfusion/batch.py` |
| Trace budget | The officer can raise how many wallets a trace reads (40 by default, up to 2,000), how deep, and for how long. The largest shares of the money are read first. The case says when the budget, not the evidence, ended the trace. | `vaspfusion/trace.py` |

## Measured

Regenerate with `make bench-scale` (about three minutes, no network). It writes `artifacts/scale/metrics.json`; the Model page and the table below read that file.

**Set-up of the run in the repository.** 5 Oct 2026, Darwin arm64, 10 cores, Python 3.12.14. The 12 recorded wallets (six chains), each replayed 25 times under different case ids: 300 cases per run, 53,675 transfers read, 4,475 chain responses. Chain responses replayed from the demo cache. The real label database.

| Worker processes | Cases per minute | Median s per case | 95th percentile s | Transfers per second | Peak memory | Against one worker |
|---|---|---|---|---|---|---|
| 1 | 409.5 | 0.14 | 0.19 | 1,221 | 385 MB | ×1.00 |
| 2 | 658.9 | 0.17 | 0.32 | 1,965 | 811 MB | ×1.61 |
| 4 | 900.9 | 0.25 | 0.33 | 2,687 | 1,602 MB | ×2.20 |
| 8 | 878.5 | 0.40 | 0.92 | 2,620 | 3,040 MB | ×2.15 |

- **Correct at every worker count:** 300 of 300 cases in each run have the findings fingerprint the repository records for their wallet (`tests/golden/fingerprints.json`).
- **Batch upload:** 500 real labelled addresses were checked, screened, given a case and queued in 3.13 s (160 rows per second).
- A case's time runs from the moment a worker is given it to its stored result. Cases per minute is counted with the workers already started; start-up (imports, loading the model) took 2.6 to 3.7 s. Peak memory is the sum over the worker processes, about 400 MB each.

**Before this work** (`artifacts/scale/baseline_before.json`, measured on commit `619b06e` with the same wallets, 10 rounds): one process, one case after another, 156.8 cases per minute, median 0.29 s per case. 45% of that time was spent re-opening the cache file for every page.

**Where one case's time goes now** (one process, 60 cases, 367 cases per minute in that pass): label lookups 34%, the deposit-address model 22%, storing the case 13%, reading chain responses from the cache 11%, the walk and allocation itself 5%, parsing 4%, the counterfactual re-traces 2%.

## What limits it

1. **More than four workers did not help on this machine.** From 4 to 8 workers throughput stayed level (901 against 879 cases per minute) while each trace's own time rose from 0.19 s to 0.28 s. The workers get in each other's way, and one process stores every result. This was measured, not explained further: which resource they compete for was not isolated.
2. **One store file, one writer.** The case store and the queue are one DuckDB file. A DuckDB file has one writing process at a time; opening it costs about 7 ms and a write about 23 ms (measured). A first version, in which each worker opened the store itself, was slower at 8 workers than at 4, which is why the server process now owns it. While the pool has work, command-line tools that write cases wait.
3. **Live, the providers are the bound.** These figures replay cached responses. A live trace waits on public chain APIs whose free keys are rate-limited; the limiter shares that limit between workers, so beyond the limit more workers do not make live traces faster. **Live throughput was not measured.**
4. **The recorded wallets are small.** None reads more than 9 wallets. A trace with a raised budget reads more and takes longer per case; that was tested for correctness, not timed at volume.
5. **One machine.** Nothing here ran on more than one host.

## The path to more (design, not built, not measured)

| Step | What it removes | What it costs |
|---|---|---|
| More keys, or a paid data plan | The live rate limit, which is the first bound in real use | Money; the limiter already takes a pace per provider |
| A server database (PostgreSQL) for cases and the queue | The one-writer file; lets workers on other machines claim jobs | A service to run; the queue's claim becomes `SELECT ... FOR UPDATE SKIP LOCKED` |
| A shared cache service | Cache lookups through one file | A service to run |
| Keep the label store open in each worker, and index it | The largest share of a case's time today (34%) | Small; not done for lack of time |
| An own node or an indexer as the data source | Dependence on public APIs and their limits | Storage and upkeep per chain |

None of these changes what a case is: a trace reads responses and labels and returns a case, wherever it runs. That separation (`api.trace_only`) is what was built to make the steps above possible.
