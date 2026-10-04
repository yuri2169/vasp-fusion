# VASP-FUSION design system

Every UI phase follows this file. It describes the interface as built in U6: **the BTC-FUSION look**, so that the two submissions (SIH26146 and SIH26182) read as one product family. The source of the language is BTC-FUSION's `docs/ui_architecture.md` and `ui/src/index.css`; where this file and that one disagree about the look, that one wins. When a rule here and the code disagree, fix one of them in the same change. Every component in every state is on the `/kit` page (demo fixtures only).

## Who it is for, and the one job

- **User:** an I4C or state cyber-cell investigator, and the SIH judges watching them.
- **The job:** paste an unknown wallet → learn which exchange to write to, with proof → send that exchange a request.
- Every screen serves that path. The primary action on a case is always **Draft request to ‹exchange›**.

## The concept

**Instrument software.** A dense, flat, ruled plate: hairlines, square corners, small-caps labels, and a palette in which every accent names where a fact comes from. It is not a product page and not a neon crypto dashboard.

House rules (they are also at the top of `src/styles/index.css`):
- Radius 0 to 2px. Nothing is a floating rounded card. `rounded-full` is for dots only.
- Depth comes from hairlines and background steps, **never box-shadow** (the Tailwind theme has no shadow). A tooltip, toast or dialog is told apart by an ink hairline.
- No gradients, unless one encodes a magnitude. (The landing's veil and grid are the two grounds; nothing is written on the grid.)
- **Mono is for values only**: addresses, transaction hashes, amounts, timestamps, counts. Labels, headings, chips and prose are Public Sans.
- Every figure is tabular and right-aligned so columns compare vertically.
- Density is the feature.
- **One frame between a leaf and the page.** A frame is a border on three or more sides. `Panel` enforces it: a `Panel` inside a `Panel` (or inside `Frame`) renders `panel-sub`, and a `DataTable` inside a frame is ruled, not boxed again. Single-edge accent rules, inline controls and `gap-px` grids are not frames. Never a border on top of a fill.
- **Three panel weights, no more:** `panel-primary` (ink hairline; exactly one focal panel per screen: on a case, the answer), `panel` (the default hairline), `panel-sub` (filled, borderless).
- Spacing is a scale: `2 4 8 12 16 24 32 48`.

## Colour

Tokens live in `src/styles/tokens.css`. **The palette is BTC-FUSION's, hex for hex** (a test pins it). A colour is a claim about where a fact comes from, never a mood:

| Token | Light | Dark | Means here |
|---|---|---|---|
| `--chain` | `#2D6A9F` | `#6BAEE8` | On-chain facts: addresses, transfers, amounts, hops, the suspect wallet |
| `--network` | `#7B4B94` | `#C199DA` | **Label evidence**: who an address belongs to (exchange labels and their tier) |
| `--fusion` | `#8C5B0E` | `#E0A63F` | The attribution answer: the named exchange, proximity and confidence, model output |
| `--confirm` | `#2E7D5B` | `#54C793` | Officer actions: the primary button, approve, mark as sent, a reply recorded |
| `--danger` | `#A2453B` | `#EE8279` | Sanctioned or mixer contact, failures |
| `--data` | `#5C6B78` | `#9AA8B6` | Unlabelled, insufficient evidence |
| `--active`, `--active-wash` | ink, `#DCE3EA` | ink, `#2B3641` | **Interaction only**: hover, focus, selected. Never provenance |

Surfaces and text: `--paper` (page), `--surface` (panels), `--surface-2` (filled panels, table heads), `--surface-3` (bar tracks), `--ink`, `--ink-soft`, `--ink-dim`, `--rule`, `--rule-soft`, and a wash per layer. Dark is re-picked, not inverted: surfaces step up from an almost-black ground.

- The footer carries the colour key (spelled out on the landing, five swatches with tooltips elsewhere), because nobody can infer it.
- Hover and selection are ink (`row-hover`, `bg-active-wash`), so no layer colour ever means "you are pointing at this".
- Colour is never the only signal: a label tier is icon + words + colour; an outcome is words + border + fill.
- **Contrast floors are load-bearing. Do not lighten `--ink-dim` or the layer colours.** `tokens.test.ts` checks AA for every text colour on every ground in both themes. Two things it knows: `--ink-dim` on `--surface-3` is 4.47:1 in dark, so text on that ground is `--ink-soft`; `--confirm` as text sits on a panel or its own wash, not on paper.

**The U1 role names are aliases.** Components written in U1 to U5 ask for `bg-page`, `text-fg`, `text-muted`, `bg-sunk`, `border-rule-strong`, `saffron`, `verified`, `seal`, `slate`. Those names still work; each points at a palette token (`tokens.css`, "aliases"): `page→paper`, `sunk→surface-2`, `fg→ink`, `muted→ink-soft`, `rule-strong→ink-dim`, `saffron→fusion`, `verified→network`, `seal→danger`, `slate→data`. New code uses the palette names.

## Type

Self-hosted through `@fontsource` (the demo runs with no network).

| Role | Face | Class |
|---|---|---|
| Masthead, names, headline figures | **Archivo** 700 to 800 | `.display`, `.title`, `.figure`, `font-cond` |
| UI and prose | **Public Sans** | default |
| Values and identifiers | **Spline Sans Mono** | `font-mono`, `.mono` |

Seven sizes, BTC-FUSION's names: `text-2xs` 11 (colheads, tags), `text-sm` 12 (dense values, hints), `text-base` 13 (body), `text-md` 16 (prose meant to be read), `text-lg` 18 (sub-headings), `text-2xl` 24, `text-3xl` 34.

- `.display`: the one masthead per screen (uppercase, 800, `clamp(22px, 2.9vw, 32px)`). **Never put an address or a hash in it bare**: it uppercases. The case and wallet pages add `normal-case` to the address.
- `.title`: a name at reading size in the same face, in its own case (an exchange, a panel's heading).
- `.figure`: the headline number a screen is about.
- `.eyebrow`: a section label. `.colhead`: a table column label. They are different objects on purpose.

## Layout

- **The header is the page, not a bar on it** (`shell/Header.tsx`): transparent with one hairline; it takes a `bg-surface` ground once `window.scrollY > 4`. Left to right: the wordmark **VASP·Fusion** (the way back to `/`), the six places (Cases, Request desk, Dashboard, Watchlist, Labels, Model), the wallet search, the data-source tag, the officer, the three-state theme control. There is no nav rail.
- **The footer status bar** (`shell/Footer.tsx`): the programme line (SIH 2026 · PS 26182 · MHA / I4C) and the colour key.
- The page scrolls; nothing pins itself to the viewport. **In a flex column, stretch children with `flex-1 min-h-0`, never `h-full`** (BTC-FUSION's height trap).
- Content column: `max-w-content` (1320px), `px-3 sm:px-6`. The landing is full-bleed.
- **Theme:** `system` / `light` / `dark`, applied as `<html data-theme>`, stored under `vaspfusion.theme`, applied before first paint by the inline script in `index.html`. `?theme=dark` forces it for one page load (screenshots).

## Motion

One idea: **instrumentation coming alive.** A trace draws, a bar grows, a counter settles. 150 to 900ms, `cubic-bezier(.16,1,.3,1)`, no bounce, no fade-up-on-scroll. Utilities: `.anim-rise`, `.anim-bar`, `.anim-draw` (with `drawOnMount`), and the Hop Rail's `rail-step`.

- `prefers-reduced-motion` neutralises the **initial** states too, or `both` fill strands a zero-width bar or an undrawn curve.
- **Any animated number is guaranteed to land**: `Counter` force-sets its value by a timer, because `requestAnimationFrame` stops in a hidden tab. A screen reader is read the value once, not the digits in motion.

## The landing (`/`) and the wait screen

- `pages/StartPage.tsx`: a one-viewport hero (the argument, the paste box, the recorded wallets; the trace drawn on the right), then "how it works" below the fold: the nine stages (`shell/StageTrack.tsx`, BTC-FUSION's serpentine track with square nodes) and the measured figures.
- `src/stages.ts` holds the nine stages (INTAKE, FETCH, LABEL, TRACE, DISCOVER, ATTRIBUTE, DECIDE, EXPLAIN, DELIVER) in three registers (`STAGES`, `PLAIN`, `DETAIL`), read by the landing and by `case/TraceProgress.tsx`, so the two cannot drift apart. In the tour only the chosen row is coloured.
- **No figure is typed.** The landing reads `GET /api/dashboard` (label coverage) and `GET /api/model` (calibration, coverage, the naming bar's measured error) when it opens, and writes "not yet measured" where there is no measurement.
- A running trace reports four phases, not nine; `stageOf` lights the stage each belongs to, and the screen says so. There is no percentage.

## The Hop Rail (the signature)

`suspect ──[ amount · time ]──▪ hop ──[ … ]──▪ deposit ── [ plate ]`. Hairlines and square stubs in `--chain` (hops are on-chain facts); the connector to the plate and the plate itself in `--fusion` when an exchange is named, dashed `--data` when none is, `--danger` when a sanctioned address or mixer was reached. The plate (`OutcomeStamp size="lg"`) is square and level; a long path scrolls sideways under it, so the answer is never off-screen. With `animate`, the rail extends hop by hop and the plate arrives last.

## What was deliberately not ported from BTC-FUSION

- `Propagation`, `Sonar`, `MapView`: network and IP views with no equivalent in this problem statement.
- The upload dropzone and the run flags (`entered`, `runReady`): intake here is a pasted address, and every route is reachable by URL.
- `figures.json` and its export script: the figures are read from the running tool instead.
- Mono on buttons and tags (BTC-FUSION's own primitives still do it): here the "mono is for values only" rule is applied to them too.
- The A4 request letter keeps its own print styling (it is a document, always ink on white), with the new faces.

## The case page (`/cases/:id`)

```
Case DEMO/2026/101
[TRON] TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c                    [Case file] [Trace again]
Complaint 3150… · Reported loss ₹40,50,000 · Opened 2 Oct 2026
┌ Hop Rail ─────────────────────────────────────────────────────────── [stamp] ┐
│ Where the 2,652.22 USDT went  ▇▇▇▇▇▇▇▇ CoinDCX 58%  ▨▨▨▨▨ busy wallets 42%      │
└────────────────────────────────────────────────────────────────────────────────┘
┌ Fund flow ── Fit · Focus path · + − · Group · PNG · GraphML ┐ ┌ Why CoinDCX? ─────┐
│ funders ▸ SUSPECT ━━━━▶ deposit ▸ exchange    (the rail's path is the │ │ name · tier · chip │
│               ╲                                 first line)           │ │ two meters         │
│                ╲──▶ wallet ──▶ busy wallet                            │ │ [Draft request to] │
│ legend: shape = role, border = label tier, line = transfer            │ │ counterfactual     │
└───────────────────────────────────────────────────────────────────────┘ │ evidence + hashes  │
  sticks under the top bar while the right column is read                 │ others · leads     │
                                                                          │ next steps·summary │
[ Timeline | Transfers 8 | Wallets 7 | Patterns 1 | Inbound funding 5 | Audit ]
```

- **The answer panel holds the one the fusion colour button**, under the meters it follows from. The page header has only secondary actions ("Case file", "Trace again").
- **The selected wallet and the open tab are in the address** (`?wallet=<address>&tab=<id>`), so a view can be linked to and the back button undoes a selection. A wallet can be selected from the graph, the Hop Rail, any address chip in the panel or the tabs; the panel then shows that wallet ("Back to the answer" returns), and the rail marks the path to it.
- **INSUFFICIENT EVIDENCE is the same frame with its own panel**: slate, dashed, headed "No exchange is named"; the reason verbatim at 16px, what was reached (meters hatched under the bar), what would change this, next steps, leads. Nothing on that screen is the fusion colour.
- **SANCTIONED OR MIXER REACHED** leads with the alert in a red-bordered panel; a nearest exchange follows only if the trace kept one, and a request is offered only at or above the bar.
- **The evidence of an exchange that is not the answer is folded** ("Evidence (3)"); the answer's own is open.
- **A running trace shows what the server says it has read** (`CaseDetail.progress`): its sentence as it came, three counts (hops out, wallets read, transfers read), and on the rail a dashed place for each hop gone out so far. No percentage: a trace does not know how much is left. A labelled wallet reached is not shown as an answer; the stamp comes with the result. The server has no cancel, so the button is "Stop waiting" and says the trace goes on. When the result arrives while the officer watches, the rail extends and one line reports what the run read.
- **Under 1024px** the graph and the panel stack; the graph stops being sticky.

## The request desk (`/desk`, `/vasps/:name`, `/requests`, `/requests/:id`)

The unit of work is an exchange, not a complaint. The desk's own parts are in `src/desk/`.

- **`/desk`** starts with the **Follow up** strip (what is past its day, in a red-outlined row each; when nothing is, one quiet line says so), then one row per exchange: wallets, traced US dollars, cases, status, and the server's `next_action` sentence as it came. A row offers "Draft request" only while a wallet of that exchange is in no request, and "Open request" once one exists. No button in a row is the fusion colour.
- **Drafting** is a dialog (`DraftDialog`): the cases to include, what to ask for, the officer's line. `/desk?vasp=&case=` (the case page's link) opens it with that case ticked; `/vasps/:name?draft=1` opens it from the exchange's page. The server writes the letter; the page then opens it as a draft.
- **`/vasps/:name`** shows only cited facts (`DirectoryFacts`), each with its source and the kind of source under it. **A blank is "No source found", never "No"**; a registration always carries its date; one known only from the exchange's own statement says so. Wallets that no request can be drafted on are marked "Context only".
- **`/requests/:id`** is the letter on an A4 sheet with, beside it: the next step (the one the fusion colour button), what to check, the routing slip, the gateway's receipt, and print. Each step is a dialog that says what it does; the buttons are the ones `allowed_next` allows, nothing else. Under 1024px the side column comes first.
- **`/requests`** is the register: every request, with filters kept in the address (`?status=&vasp=&q=`).

**The routing slip** (`RoutingSlip`) is this part's one drawn element: the slip on a file. Five boxes in order (Drafted, Approved, Sent, Acknowledged, Reply), each stamped with its day once it happened. A box not reached is dashed and empty; the one awaited is shaded; a step passed over has a dash; a refusal or a withdrawal ends the slip in a red-washed box with a cross. `layout="row"` fits a table row (the whole sentence is on hover and in the box's name); `layout="column"` beside the letter adds who and the note of each step, as recorded. It is never tilted and never the fusion colour.

**Status** (`StatusTag`) is an icon and a word: Not requested and Draft are dashed, Approved solid, Sent and Acknowledged shaded, Answered and Freeze confirmed the label (network) colour, Refused red, Withdrawn struck through.

**The letter sheet** (`LetterSheet`, `letter.css`):
- Paper is paper: white with ink text in both themes. The sheet sets the role tokens back to their light values, so the rule "role tokens only" still holds on it.
- It draws `RequestDetail.letter` and rewords nothing: letterhead (the officer's line, reference, date), To, Through, Subject, numbered paragraphs, the four asks as ticked boxes, the wallets table, the transactions, the matters referred to, the legal basis with its citations, the seal circle and the signature line. Addresses and hashes are whole.
- **Until the request is approved** the sheet carries the server's watermark text across it and a banner at its head.
- **Print** (`@media print`): the shell, the page header and the side column are hidden (`print:hidden`); the sheet loses its border and padding. An `@page` rule written by the component (it carries the reference) sets A4, the margins, and margin boxes: the reference and "Page n of N" at the foot of every page, and on a draft the banner at the head. The watermark is a fixed element, so it repeats on every page. A draft ends in a sheet of the review notes, headed "Not part of the request". Chromium-family browsers print margin boxes; the browser's own headers and footers should be switched off in the print dialog.

## The overview pages (`/dashboard`, `/wallets/:chain/:address`, `/labels`, `/model`, `/watchlist`)

The pages an officer goes to between cases. Their shared parts are in `src/overview/` (`Panel`, `Ledger`, `words.ts`) and `src/charts/`.

- **Every figure is a count of stored records and opens the list behind it.** The dashboard's counts link to `/cases?outcome=&status=&chain=&open=1`, `/desk`, `/requests?status=awaiting`, `/watchlist`, `/vasps/:name` and `/labels?tier=&chain=&category=`; those lists read the filter from the address and show it as a chip that can be removed.
- **The ledger** (`Ledger`) is the page's counts on one ruled line, as the totals row of a register: a figure in mono at 28px, what it counts under it. It is one sheet with hairlines, not a row of cards, and no figure on it is the fusion colour. `perRow={3}` where six cells would crowd the figures (the model's "over 0.999").
- **A figure that was not measured says so** ("Not yet measured", "Not recorded", "Not assessed") and shows no number. The model page with `status: not_measured` shows no plot and no metric.
- **`/dashboard`**: the ledger; how the cases ended; the exchanges the funds reached (US-dollar stablecoins only, and the note says so); cases by chain; the time the funds took to reach the exchange (chain time, with how many cases it is the median of); alerts, each in the case's or the watchlist's own sentence, with a word and an icon for its severity; label coverage. There is no primary action on this page, so nothing on it is the fusion colour except the "exchange named" part of the outcome bar.
- **`/wallets/:chain/:address`**: the address whole in mono (never shortened in its own title), its label with source and evidence (the case page's `LabelBlock`), **what is on record against it** as a level in words (High, Elevated, Nothing on record, Not assessed) with the sentences it rests on, and the sentence that **no risk score is computed**; the cases it is in; the transfers those cases read of it, under a note that this is not the wallet's whole history. The one the fusion colour button is "Trace this wallet", only when the wallet has no case of its own.
- **`/labels`**: search (address prefix or owner) and three filters, all in the address; a result's address leads to its wallet page, an exchange's name to its page. Under it, what the store covers by tier, category, chain and **source, with the licence on record**: a licence this project holds no record of reads "Not recorded", never a guess. A label this tool derived says "rule" before its confidence unless the model confirmed it; a sourced label reads "as its source".
- **`/model`**: Tron or Ethereum (`?chain=`); the ledger of measured figures; calibration; accuracy when answering against coverage; what the model reads; the one rule the figures are read against; each exchange held out; the check of the naming bar; and **every `notes[]` sentence as written**, under "What these numbers are, and are not". A recall under 0.5 on a held-out exchange is set in red with its figure: the page shows where the model fails.
- **`/watchlist`**: the form (the address is checked as in the search bar), then one sheet per wallet, a changed one first. State is an icon and words (Changed since last seen, No change, Checking, Not traced yet, Last check failed). What is new is the server's sentences. The actions keep their names: "Check now", "Mark as seen" → "Marked as seen", "Stop watching" → "Stopped watching". The page says that nothing is checked in the background.

## Charts (`src/charts/`)

Hand-built (HTML bars, SVG plots): no chart library, so the demo needs no network and every mark takes the tokens of both themes.

| Component | Use it for |
|---|---|
| `BarList` | Ranked bars of one measure. The value is written at the end of every row, so the chart is its own table; a row with `to` is a link |
| `ShareBar` | The parts of one whole, as statuses, every part named under the bar with its count |
| `ReliabilityPlot` | Calibration: probability given against share observed, the diagonal to read it against, and how many addresses each point stands for |
| `CoveragePlot` | Accuracy when answering against the share answered, with an optional level to read it against |
| `PlotFrame`, `PlotPoint`, `PlotLine`, `PlotReference`, `ChartTable` | The parts of an x/y plot (`Plot.tsx`); `scale.ts` holds the arithmetic |

Rules (the `dataviz` skill's, fitted to this system):
- **One hue for a measure: ink (`--fg`).** The six brand colours are not a categorical palette (see the funds bar), so no chart tells series apart by hue; each has one series, and a line to read it against is dashed, grey and named on the plot.
- **The status fills are for statuses only**: the fusion colour = an exchange was named, seal = sanctioned or mixer, hatch = unresolved. Never for "series 2".
- **One x axis and one y axis.** Two measures get two charts (the counts under the reliability plot are their own strip on the same x axis).
- **A zoomed axis says so** in a sentence under the plot ("The vertical axis starts at 90%, not at zero").
- Thin marks: 6px square-ended bars that grow to their length, in the colour of the layer the measure belongs to (`layer` on `BarList`: label counts `network`, on-chain counts `chain`, model output `fusion`), 1.5px lines that draw themselves, points of 9px with a 2px ring in the surface colour and a hit area of 28px. Grid lines are hairlines in `--rule`; axis text is 12px in `--fg-muted`. Values and labels are text tokens, never a mark's colour.
- **Every plot has "Show as table"** under it with the same figures, every point has a card on hover and on keyboard focus, and its name says the figures.
- **A share or a score is never written as perfect unless it is**: `share()` writes "over 99.9%", `score()` "over 0.999" (`src/overview/words.ts`), as `formatConfidence` writes "over 0.99".

## The fund-flow graph

Drawn by Cytoscape (`src/case/FlowGraph.tsx`) from a view computed in `src/lib/caseGraph.ts`. The layout is ours: a column per hop, **the Hop Rail's path on the first line**, side branches under it, funders to the left of the suspect wallet. Same case, same picture.

| What | Encodes | How |
|---|---|---|
| Shape | The wallet's role | Suspect: square filled in the chain colour. On the trail: square. Not followed further: small square. Busy wallet: hexagon. Deposit address: tag. Exchange wallet: rectangle with cut corners. Custodial: barrel. Swap service: rhomboid. Bridge: diamond with two opposed arrows. Mixer: concave hexagon, red, crossing arrows. Sanctioned: octagon, red, a bar |
| Border | The tier of its label | The `TierTag` vocabulary: published by exchange = double the label (network) colour; curated = solid the label (network) colour on a tint; explorer tag = dotted the label (network) colour; derived = solid slate; unlabelled = dashed slate |
| The fusion colour fill | A wallet of the exchange the case names | Nothing else on the canvas is the fusion colour |
| Line width | The amount (square-root scale, 1.5 to 8px) | Several transfers between two wallets are one line; the hover card lists them |
| Line colour and dash | Ink = the path on the Hop Rail; slate = other transfers; dashed = money coming in | |

- The legend under the canvas names, in words, every shape, border and line **this case** uses.
- The owner's name is written over a labelled wallet, the short address under every wallet (14px on the canvas; the picture is never drawn above life size, so type stays at or under the page's).
- Hover: a wallet's whole address, role and label; a transfer's amount, time and whole hash. Click: selects. With a selection, everything off the path to it steps back to 20%; the suspect wallet dims nothing (every transfer is its own).
- The mouse wheel scrolls the page; zoom is on the buttons. Nodes are not draggable.
- **Nothing is reachable by mouse only.** The canvas is `role="img"` with a sentence; the Wallets tab lists every wallet and selects it the same way a click does, the Transfers tab every transfer.
- **A large case (over 250 wallets) is drawn in part** (`foldFlow`). A hop of 400 wallets is a column 36,000px tall that tells nobody anything. Drawn: the path, then 12 wallets of each hop, chosen as the selected wallet and the way to it, the named exchange's wallets, any labelled wallet, then the largest. The rest of a hop is one quiet dashed node, "+388 wallets"; hops past the path's end wait behind "Draw hop 3". A line under the toolbar says how many are drawn and has a button for every fold, so the keyboard can do what a click on the fold does. A selection never refits the picture. Nothing is dropped: the Wallets and Transfers tabs hold every one.
- Straight lines, not square ("taxi") routing: square routing runs different transfers along one trunk, and the picture then no longer says which wallet paid which.

## Encoding rules

- **Proximity and confidence are two meters, never one score** (`DualMeter`). Proximity is a short rail of hops with the rank, hops, share of the funds and time. Confidence is a bar with the 0.60 naming bar marked and the model's range as a lighter band. They are drawn in different forms on purpose.
- **Confidence wording.** With a range (`confidence_interval`): "confidence 0.85" and the range. Without one: "rule confidence 0.71". Under the bar the fill is hatched and the text says so.
- **A probability is never printed as 1.00**: `formatConfidence` writes "over 0.99".
- **Label tier is icon + words + colour, never colour alone** (`TierTag`):

  | Tier | Words | Icon | Look |
  |---|---|---|---|
  | `published_por` | Published by exchange | seal (badge-check) | solid the label (network) colour |
  | `curated` | Curated list | list-checks | the label (network) colour tint |
  | `explorer_tag` | Explorer tag | tag | the label (network) colour outline |
  | `derived` | Derived by VASP-FUSION | flask | slate |
  | none | Unlabelled | dashed square in the chain colour | dashed slate |

- **Outcome stamps** (`OutcomeStamp`):
  - ATTRIBUTED: a solid plate in the fusion colour, the exchange's name.
  - INSUFFICIENT EVIDENCE: slate, dashed border, "No exchange named", and a line saying what would change it.
  - SANCTIONED OR MIXER REACHED: the danger colour; it still names the nearest exchange if the rules kept one.
  - No result yet: "Tracing…" (dashed), "Trace failed" (red outline).
- **Patterns** (`TypologyFlag`): severity is a word and an icon as well as a colour: Alert (high), Pattern (warn), Note (info). A `deposit_like` flag is a **Lead**: dashed the label (network) colour, kept apart from the answer.
- **Addresses** (`AddressChip`): shortened in the middle as the backend writes them (`TVZpWt…KjUtzR`, six and six; four and four on the rail). The whole address is one hover, one Tab or one click (copy) away. **Copy always copies the whole address.** Letters and tables of record print it whole (`full`).
- **Numbers** follow `vaspfusion/explain/fmt.py` (`src/lib/format.ts`), so a figure in a meter reads the same as in the backend's sentence: `48,500 USDT`, `252,163.80 USDT`, `0.002428 ETH`, `85%`, `under 1%`, `₹40,50,000`. Times are UTC and say so.
- **Where the funds went** (`FundsBar`) is one stacked bar of the whole of what the wallet sent. Kind is **not** told by hue: the six brand colours are not a categorical palette (checked with the dataviz validator: slate and the label (network) colour are too close for a protan reader, the fusion colour is under 3:1 on white). Three fills, each a status: the fusion colour = the exchange named, ink = another named party, seal = sanctioned or mixer; everything unresolved is one hatch. Every slice is named under the bar with its share and amount, slices are 2px apart, and each has a hover card.
- **Model reasons** (`EvidenceList`) are signed bars: solid = speaks for, hatched = against, with the SHAP value in mono. The model's probability is a sentence, never a bar.
- **Demo data is marked.** The top bar shows "Demo data" or "Includes demo data" whenever the API's `X-Data-Source` is not `live`.

## Copy rules

- Sentence case, plain verbs, the investigator's words, not the system's.
- Buttons say what happens: "Trace wallet", "Draft request to OKX", "Mark as sent", "Withdraw request". Never "Submit", "OK" or "Run pipeline".
- An action keeps its name through the flow: the button "Mark as sent" produces the toast "Marked as sent".
- Errors say what happened and what to do next. The API's `detail` is already such a sentence: show it as it came (`ErrorState`, toast, the search bar's hint).
- Empty screens invite the next action: "Paste a wallet address to open a case".
- Show the backend's sentences verbatim (narrative, evidence, flags, notes). Do not paraphrase a finding.
- Say "exchange" where the officer would; "VASP" only where the law or the product name does.
- Never the system's furniture: no "server", "API", "cache", "log". Say "this installation", "saved copies", "whoever runs this installation".
- A confidence is never shown without its error. Under the answer of a case: how the naming bar was checked, in the measurement's own figures (`BarChecked`, from `GET /api/model`), and that an attribution is a lead to confirm, not proof.
- Nothing claims SAHYOG. The button is "Mark as sent"; its dialog and the receipt say the gateway is a local outbox unless a connection has been set up.
- A wallet of the demonstration set is tagged "Recorded" (real, traced from recorded chain responses), never "Demo".
- One action at a time: a case being traced again offers no request from its previous answer; a case already in a request offers "Open request to ‹exchange›" with its status, not a second draft.

## Components (`src/components/`)

| Component | Use it for |
|---|---|
| `Button`, `buttonClass` | Actions. `primary` (the fusion colour) once per screen; `secondary`, `ghost`, `danger`. `buttonClass` styles a `<Link>` |
| `AddressChip` | Any address. `entity` + `tier` for a labelled one, `role="suspect"`, `full`, `to` (link to its page) |
| `TxHash` | Any transaction hash |
| `CopyButton` | Copy a whole value; announces "Copied" |
| `ChainBadge` | The chain (TRON, ETH, BSC, POLYGON, ARB, BASE, OP, AVAX, BTC, SOL); `tentative` for a guess |
| `TierTag`, `TierIcon` | Label tier |
| `OutcomeStamp` | The outcome: `size="lg"` on a case, `sm` in a table row |
| `DualMeter` | Proximity and confidence of one candidate; `layout="stack"` in a narrow column |
| `Amount` | An amount in its asset, with US dollars when that adds something |
| `TypologyFlag` | A pattern or a lead; `compact` for the name alone |
| `HopRail` | The path of the funds, ending in the stamp. `selected`, `marked`, `onSelect` tie it to the page's selection; `footer` sits inside its card |
| `FundsBar` | Where the money ended up: one bar, every part named |
| `EvidenceList` | Evidence items in the backend's words, with hashes; model reasons as signed bars |
| `Tabs` | The index tabs of a file: arrow keys, Home/End, counts |
| `DataTable` | Any list of records: sortable, sticky header, rows open with a click or Enter |
| `PageHeader` | The top of a screen |
| `EmptyState`, `ErrorState`, `Skeleton` | Nothing yet, something failed, on its way |
| `ToastProvider`, `useToast` | Confirm an action; errors stay until dismissed |
| `Dialog` | A decision that should not be made in passing |
| `Tip`, `useTip` | A small card on hover and focus, drawn in `<body>` so nothing clips it |

The case page's own parts are in `src/case/` (they are not general components): `FlowGraph` + `GraphLegend` + `flowStyle.ts`, `AnswerPanel`, `AbstainPanel`, `CandidateCard`, `WalletPanel`, `TraceProgress`, `TraceAgain` (with `HopLimit`), the six `tabs/`, `caseText.ts` (words for roles, checks, audit actions) and `rules.ts` (the naming bar, what can be routed to the desk).

The request desk's parts are in `src/desk/`: `RoutingSlip`, `StatusTag`, `DeskNav`, `DraftDialog`, `DirectoryFacts`, `LetterSheet` + `letter.css` + `pageRule.ts`, `RequestActions`, and `status.ts` (the words for statuses, asks and replies; the slip's steps; overdue).

`AddressChip` takes `onSelect` / `selected` / `marked`: the address then is a button that shows the wallet on the case page.

The overview pages' parts are in `src/overview/` (`Panel`, `Ledger`, `words.ts`: chain and category names, `count`, `plural`, `share`, `score`) and `src/charts/` (above).

Shell (`src/shell/`): `AppShell` (starts at `GET /api/auth/me`; shows the sign-in page when a login is required), `NavRail`, `GlobalSearch`.

## Accessibility floor

- Everything works from the keyboard. One focus ring everywhere: 2px in the text colour, 2px clear of the control (paper on the rail). Never remove it.
- "Skip to content" is the first Tab stop. `/` puts the cursor in the search bar; Escape clears it.
- AA contrast in both themes, enforced by the token test.
- Meaning never rests on colour alone: tiers, outcomes, severities and "under the bar" all have words and a shape or icon.
- Meters are `role="meter"` with a sentence in `aria-valuetext`. Tables have a caption. Sort state is `aria-sort`.
- `prefers-reduced-motion` turns the one animation off.
- **Audited, not assumed:** `node scripts/a11y.mjs` runs axe-core (WCAG 2.1 A and AA, and its best practices) on every screen in both themes and walks Tab through four of them. It must end "No finding". What it taught: counts that are links are a list, not a `<dl>`; an empty state's title is a level-2 heading; two landmarks of one kind need different names; decoration (the draft watermark) is drawn by CSS, not written as page text.
- A long table (`DataTable`) draws its first 200 rows and says "Showing 200 of 2,000", with "Show 200 more" and "Show all"; sorting sorts all rows. The timeline does the same in steps of 150.
- A page that fails while it is drawn is caught (`PageBoundary`): the rail and search stay, and the officer is told what to do.

## Data

- Screens never call `fetch`. They use the hooks in `src/api/queries.ts` (TanStack Query) over the typed client in `src/api/client.ts`.
- `src/api/types.ts` is generated by `make types`. Never edit it; add an alias in `src/api/models.ts`.
- **Mock or live** (`VITE_API`): `npm run dev` and the tests read the fixtures in `../mocks` (`GET /api/<path>` → `mocks/<path>.json`). `VITE_API=live npm run dev` talks to `make serve` through the dev proxy. `npm run build` is live (the bundle is served by the API); `VITE_API=mock npm run build` builds on the fixtures.
- Real data only. `/kit` shows the B1 fixtures, read through the client; never invent an address or a figure for a screen.

## Commands (in `ui/`)

- `npm ci` once, then `npm run dev` (mock) or `VITE_API=live npm run dev`.
- `npm test`, `npm run typecheck`, `npm run lint`, `npm run build`.
- `npm run screenshots` (with the dev server running; `BASE_URL=` if it is not on 5173) writes `docs/screenshots/kit-*.png`, `case-*.png`, `desk-*.png` and `overview-*.png` in both themes (and `desk-live-letter-*.pdf`, the letter printed), using a Chromium-family browser already installed (`BROWSER=` to choose). `npm run screenshots -- case` takes only the names that start so. `LIVE_URL=` (the interface run with `VITE_API=live` against `make serve`, after `make demo`) adds `case-live-*`, the real demo wallets; the last of them traces the hero wallet again (with the server on `OFFLINE=1`, from the cache).
- In mock mode a demo wallet's trace appears to take 2.4 seconds (`mockSettings.traceMs` in `src/api/mock.ts`) and reports progress worked out from the fixture's own graph, so the trace screen and the rail's animation can be seen with no server. Tests set it to 0.
