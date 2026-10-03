# VASP-FUSION design system

Every UI phase follows this file. It describes the interface as built in U1; when a rule here and the code disagree, fix one of them in the same change. Every component in every state is on the `/kit` page.

## Who it is for, and the one job

- **User:** an I4C or state cyber-cell investigator, and the SIH judges watching them.
- **The job:** paste an unknown wallet → learn which exchange to write to, with proof → send that exchange a request.
- Every screen serves that path. The primary action on a case is always **Draft request to ‹exchange›**.

## The concept

**A case file that ends in a routing slip.** The world this comes from is legal notices, evidence tags, chain-of-custody seals and docket stamps. It is not a neon crypto dashboard.

What that means in practice:
- Flat surfaces, hairline rules, 4px corners. No gradients. Shadows only on things that float (tooltip, toast, dialog, the search bar's hint).
- One bold element, the **Hop Rail** with its ticket stubs and docket stamp. Everything else stays quiet.
- Saffron is rare, so it means something: the attributed exchange, or the one primary action.

## Colour

Tokens live in `src/styles/tokens.css`. Two layers.

**Brand: six colours, the same in both themes.**

| Token | Hex | Use |
|---|---|---|
| `--ink` | `#2B1622` | Deep plum. Nav rail, headings |
| `--paper` | `#F5F4F8` | Cool lavender-grey page (deliberately not cream) |
| `--saffron` | `#E8772E` | The attributed exchange and the primary action. Nothing else |
| `--verified` | `#1F7A74` | Evidence published by an exchange, or tagged by an explorer |
| `--seal` | `#B3261E` | Sanctioned, mixer, freeze, errors |
| `--slate` | `#5B5566` | Secondary text, derived-tier evidence |

**Role: what a component asks for. These switch with the theme.**

| Token (Tailwind class) | Light | Dark | Use |
|---|---|---|---|
| `--bg` (`bg-page`) | `#F5F4F8` | `#1A0F16` | Page |
| `--surface` (`bg-surface`) | `#FFFFFF` | `#24161F` | Cards, tables, chips |
| `--surface-sunk` (`bg-sunk`) | `#ECE9F1` | `#140B11` | Wells, table header, hover |
| `--rule` (`border-rule`) | `#DAD6E1` | `#3E2A37` | Hairlines |
| `--rule-strong` (`border-rule-strong`) | `#8A8296` | `#8A7584` | Control borders (3:1) |
| `--fg` (`text-fg`) | `#2B1622` | `#EDE9F0` | Text, headings |
| `--fg-muted` (`text-muted`) | `#5B5566` | `#B9AEBB` | Secondary text |
| `--focus` | `#2B1622` | `#EDE9F0` | Focus ring (paper on the rail) |
| `--rail-bg` (`bg-rail`) | `#2B1622` | `#120A0F` | Nav rail; `text-rail-fg`, `text-rail-muted`, `bg-rail-active` |
| `--saffron-text` (`text-saffron-text`) | `#A5460E` | `#E8772E` | Saffron as text |
| `--verified-text` (`text-verified-text`) | `#196A65` | `#57BDB4` | Teal as text or outline |
| `--seal-text` (`text-seal-text`) | `#B3261E` | `#F08A82` | Red as text or outline |
| `--*-wash` (`bg-saffron-wash` …) | pale tints | deep tints | Tinted backgrounds |
| `--on-saffron`, `--on-verified`, `--on-seal` | `#2B1622`, white, white | same | Text on a brand fill (`text-saffron-on` …) |

Rules:
- **Components use role tokens only**, through the Tailwind classes. Tailwind's default palette is removed, so `bg-red-500` does not exist.
- A brand fill takes its `on-` colour for text: `bg-saffron text-saffron-on`, `bg-verified text-verified-on`, `bg-seal text-seal-on`.
- An accent used as text or as an outline takes the `-text` variant, never the brand hex (the brand teal and red fail contrast on the dark surface).
- `src/styles/tokens.test.ts` pins the six brand hexes and checks every text and background pair for WCAG AA (4.5:1 text, 3:1 control borders and focus) in both themes. A new token pair gets a line there.

**Dark mode.** `data-theme="light" | "dark"` on `<html>` wins; with no attribute, `prefers-color-scheme` decides. The officer's choice is stored as `vaspfusion.theme` and applied before first paint (`index.html`). `?theme=dark` forces a theme for one page load (screenshots). The dark block is written twice in `tokens.css` (attribute and media query); a test keeps the two identical.

## Type

Self-hosted through `@fontsource` (the demo runs with no network).

| Face | Class | Use |
|---|---|---|
| Bricolage Grotesque | `display` | Page titles, exchange names on stamps and cards. Nothing else |
| IBM Plex Sans | default | Everything read |
| IBM Plex Mono | `font-mono` | **Every address, transaction hash and amount.** Non-negotiable |

- Scale: **12 / 14 / 16 / 20 / 28 / 40** (`text-xs`, `sm`, `base`, `lg`, `xl`, `2xl`). There is nothing in between; do not add sizes.
- 14 is the default. 16 is for the case narrative, the paragraph an officer reads in full.
- Amounts and any column of figures take `tabular`.
- Field labels and table headers take `eyebrow` (12px, caps, tracked, muted).
- Sentence case everywhere. Capitals come only from `eyebrow` and the stamps.

## Layout

```
┌────────┬───────────────────────────────────────────────────────────┐
│ VASP-  │ [ Paste a wallet address to open a case    TRON ]  Trace  │
│ FUSION │───────────────────────────────────────────────────────────│
│ Cases  │ Case reference                         Draft request to X │
│ Desk   │ Title (display 28)                                        │
│ Dashb. │ ┌ Hop Rail ──────────────────────────────────── [STAMP] ┐ │
│ Labels │ └───────────────────────────────────────────────────────┘ │
│ Model  │ content                                                   │
│────────│                                                           │
│ officer│                                                           │
└────────┴───────────────────────────────────────────────────────────┘
```

- Rail: 224px, icons only (64px) under 1024px. Content column: at most 1240px.
- Routes: `/cases` (list), `/cases/new` (open a case: the file's cover sheet), `/cases/:id` (the case), `/desk`, `/vasps/:name`, `/requests`, `/requests/:id` (the request desk; the rail stays on "Request desk" for all four).
- The top bar holds the search and the data-source tag, nothing else.
- A page starts with `PageHeader` (optional eyebrow, title, one line of purpose, actions on the right).
- Sections inside a page are headed by an `eyebrow` `<h2>`.
- Designed at 1280 and 1440; holds down to 768.

## The Hop Rail (the signature)

`suspect ──[ 48,500 USDT · 14 Sep 2026 ]──▶ hop ──[ 41,200 USDT · 7 min later ]──▶ deposit ── [ OKX ]`

- At the top of every case. Component: `HopRail`.
- Each hop is an address chip; each arrow carries a **ticket stub** (perforated short sides) with the amount and the time taken. The stub is the link to the transaction; its tooltip has the whole hash.
- The amount on a stub is the suspect's part of the transfer (`traced_amount`) when the transfer carried other money too; the tooltip gives both.
- The rail ends in the **docket stamp**: double rule, exchange name in Bricolage, set 1.5° off level. Only this stamp is tilted.
- A long path scrolls sideways under the stamp. The stamp stays in view: the answer is never off-screen.
- While a case is queued or running the rail shows the suspect wallet and a line still being drawn.
- **The one orchestrated animation in the app:** when a result arrives while the officer is watching, pass `animate` and the rail extends hop by hop, the stamp landing last. Nothing else in the app animates. Under `prefers-reduced-motion` it does not animate either.

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

- **The answer panel holds the one saffron button**, under the meters it follows from. The page header has only secondary actions ("Case file", "Trace again").
- **The selected wallet and the open tab are in the address** (`?wallet=<address>&tab=<id>`), so a view can be linked to and the back button undoes a selection. A wallet can be selected from the graph, the Hop Rail, any address chip in the panel or the tabs; the panel then shows that wallet ("Back to the answer" returns), and the rail marks the path to it.
- **INSUFFICIENT EVIDENCE is the same frame with its own panel**: slate, dashed, headed "No exchange is named"; the reason verbatim at 16px, what was reached (meters hatched under the bar), what would change this, next steps, leads. Nothing on that screen is saffron.
- **SANCTIONED OR MIXER REACHED** leads with the alert in a red-bordered panel; a nearest exchange follows only if the trace kept one, and a request is offered only at or above the bar.
- **The evidence of an exchange that is not the answer is folded** ("Evidence (3)"); the answer's own is open.
- **A running trace shows what the server says it has read** (`CaseDetail.progress`): its sentence as it came, three counts (hops out, wallets read, transfers read), and on the rail a dashed place for each hop gone out so far. No percentage: a trace does not know how much is left. A labelled wallet reached is not shown as an answer; the stamp comes with the result. The server has no cancel, so the button is "Stop waiting" and says the trace goes on. When the result arrives while the officer watches, the rail extends and one line reports what the run read.
- **Under 1024px** the graph and the panel stack; the graph stops being sticky.

## The request desk (`/desk`, `/vasps/:name`, `/requests`, `/requests/:id`)

The unit of work is an exchange, not a complaint. The desk's own parts are in `src/desk/`.

- **`/desk`** starts with the **Follow up** strip (what is past its day, in a red-outlined row each; when nothing is, one quiet line says so), then one row per exchange: wallets, traced US dollars, cases, status, and the server's `next_action` sentence as it came. A row offers "Draft request" only while a wallet of that exchange is in no request, and "Open request" once one exists. No button in a row is saffron.
- **Drafting** is a dialog (`DraftDialog`): the cases to include, what to ask for, the officer's line. `/desk?vasp=&case=` (the case page's link) opens it with that case ticked; `/vasps/:name?draft=1` opens it from the exchange's page. The server writes the letter; the page then opens it as a draft.
- **`/vasps/:name`** shows only cited facts (`DirectoryFacts`), each with its source and the kind of source under it. **A blank is "No source found", never "No"**; a registration always carries its date; one known only from the exchange's own statement says so. Wallets that no request can be drafted on are marked "Context only".
- **`/requests/:id`** is the letter on an A4 sheet with, beside it: the next step (the one saffron button), what to check, the routing slip, the gateway's receipt, and print. Each step is a dialog that says what it does; the buttons are the ones `allowed_next` allows, nothing else. Under 1024px the side column comes first.
- **`/requests`** is the register: every request, with filters kept in the address (`?status=&vasp=&q=`).

**The routing slip** (`RoutingSlip`) is this part's one drawn element: the slip on a file. Five boxes in order (Drafted, Approved, Sent, Acknowledged, Reply), each stamped with its day once it happened. A box not reached is dashed and empty; the one awaited is shaded; a step passed over has a dash; a refusal or a withdrawal ends the slip in a red-washed box with a cross. `layout="row"` fits a table row (the whole sentence is on hover and in the box's name); `layout="column"` beside the letter adds who and the note of each step, as recorded. It is never tilted and never saffron.

**Status** (`StatusTag`) is an icon and a word: Not requested and Draft are dashed, Approved solid, Sent and Acknowledged shaded, Answered and Freeze confirmed teal, Refused red, Withdrawn struck through.

**The letter sheet** (`LetterSheet`, `letter.css`):
- Paper is paper: white with ink text in both themes. The sheet sets the role tokens back to their light values, so the rule "role tokens only" still holds on it.
- It draws `RequestDetail.letter` and rewords nothing: letterhead (the officer's line, reference, date), To, Through, Subject, numbered paragraphs, the four asks as ticked boxes, the wallets table, the transactions, the matters referred to, the legal basis with its citations, the seal circle and the signature line. Addresses and hashes are whole.
- **Until the request is approved** the sheet carries the server's watermark text across it and a banner at its head.
- **Print** (`@media print`): the shell, the page header and the side column are hidden (`print:hidden`); the sheet loses its border and padding. An `@page` rule written by the component (it carries the reference) sets A4, the margins, and margin boxes: the reference and "Page n of N" at the foot of every page, and on a draft the banner at the head. The watermark is a fixed element, so it repeats on every page. A draft ends in a sheet of the review notes, headed "Not part of the request". Chromium-family browsers print margin boxes; the browser's own headers and footers should be switched off in the print dialog.

## The fund-flow graph

Drawn by Cytoscape (`src/case/FlowGraph.tsx`) from a view computed in `src/lib/caseGraph.ts`. The layout is ours: a column per hop, **the Hop Rail's path on the first line**, side branches under it, funders to the left of the suspect wallet. Same case, same picture.

| What | Encodes | How |
|---|---|---|
| Shape | The wallet's role | Suspect: filled ink circle. On the trail: circle. Not followed further: small circle. Busy wallet: hexagon. Deposit address: tag. Exchange wallet: rounded rectangle. Custodial: barrel. Swap service: rhomboid. Bridge: diamond with two opposed arrows. Mixer: concave hexagon, red, crossing arrows. Sanctioned: octagon, red, a bar |
| Border | The tier of its label | The `TierTag` vocabulary: published by exchange = double teal; curated = solid teal on a tint; explorer tag = dotted teal; derived = solid slate; unlabelled = dashed slate |
| Saffron fill | A wallet of the exchange the case names | Nothing else on the canvas is saffron |
| Line width | The amount (square-root scale, 1.5 to 8px) | Several transfers between two wallets are one line; the hover card lists them |
| Line colour and dash | Ink = the path on the Hop Rail; slate = other transfers; dashed = money coming in | |

- The legend under the canvas names, in words, every shape, border and line **this case** uses.
- The owner's name is written over a labelled wallet, the short address under every wallet (14px on the canvas; the picture is never drawn above life size, so type stays at or under the page's).
- Hover: a wallet's whole address, role and label; a transfer's amount, time and whole hash. Click: selects. With a selection, everything off the path to it steps back to 20%; the suspect wallet dims nothing (every transfer is its own).
- The mouse wheel scrolls the page; zoom is on the buttons. Nodes are not draggable.
- **Nothing is reachable by mouse only.** The canvas is `role="img"` with a sentence; the Wallets tab lists every wallet and selects it the same way a click does, the Transfers tab every transfer.
- Straight lines, not square ("taxi") routing: square routing runs different transfers along one trunk, and the picture then no longer says which wallet paid which.

## Encoding rules

- **Proximity and confidence are two meters, never one score** (`DualMeter`). Proximity is a short rail of hops with the rank, hops, share of the funds and time. Confidence is a bar with the 0.60 naming bar marked and the model's range as a lighter band. They are drawn in different forms on purpose.
- **Confidence wording.** With a range (`confidence_interval`): "confidence 0.85" and the range. Without one: "rule confidence 0.71". Under the bar the fill is hatched and the text says so.
- **A probability is never printed as 1.00**: `formatConfidence` writes "over 0.99".
- **Label tier is icon + words + colour, never colour alone** (`TierTag`):

  | Tier | Words | Icon | Look |
  |---|---|---|---|
  | `published_por` | Published by exchange | seal (badge-check) | solid teal |
  | `curated` | Curated list | list-checks | teal tint |
  | `explorer_tag` | Explorer tag | tag | teal outline |
  | `derived` | Derived by VASP-FUSION | flask | slate |
  | none | Unlabelled | dashed circle | dashed slate |

- **Outcome stamps** (`OutcomeStamp`):
  - ATTRIBUTED: solid saffron, the exchange's name.
  - INSUFFICIENT EVIDENCE: slate, dashed border, "No exchange named", and a line saying what would change it.
  - SANCTIONED OR MIXER REACHED: seal red; it still names the nearest exchange if the rules kept one.
  - No result yet: "Tracing…" (dashed), "Trace failed" (red outline).
- **Patterns** (`TypologyFlag`): severity is a word and an icon as well as a colour: Alert (high), Pattern (warn), Note (info). A `deposit_like` flag is a **Lead**: dashed teal, kept apart from the answer.
- **Addresses** (`AddressChip`): shortened in the middle as the backend writes them (`TVZpWt…KjUtzR`, six and six; four and four on the rail). The whole address is one hover, one Tab or one click (copy) away. **Copy always copies the whole address.** Letters and tables of record print it whole (`full`).
- **Numbers** follow `vaspfusion/explain/fmt.py` (`src/lib/format.ts`), so a figure in a meter reads the same as in the backend's sentence: `48,500 USDT`, `252,163.80 USDT`, `0.002428 ETH`, `85%`, `under 1%`, `₹40,50,000`. Times are UTC and say so.
- **Where the funds went** (`FundsBar`) is one stacked bar of the whole of what the wallet sent. Kind is **not** told by hue: the six brand colours are not a categorical palette (checked with the dataviz validator: slate and teal are too close for a protan reader, saffron is under 3:1 on white). Three fills, each a status: saffron = the exchange named, ink = another named party, seal = sanctioned or mixer; everything unresolved is one hatch. Every slice is named under the bar with its share and amount, slices are 2px apart, and each has a hover card.
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

## Components (`src/components/`)

| Component | Use it for |
|---|---|
| `Button`, `buttonClass` | Actions. `primary` (saffron) once per screen; `secondary`, `ghost`, `danger`. `buttonClass` styles a `<Link>` |
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

Shell (`src/shell/`): `AppShell` (starts at `GET /api/auth/me`; shows the sign-in page when a login is required), `NavRail`, `GlobalSearch`.

## Accessibility floor

- Everything works from the keyboard. One focus ring everywhere: 2px in the text colour, 2px clear of the control (paper on the rail). Never remove it.
- "Skip to content" is the first Tab stop. `/` puts the cursor in the search bar; Escape clears it.
- AA contrast in both themes, enforced by the token test.
- Meaning never rests on colour alone: tiers, outcomes, severities and "under the bar" all have words and a shape or icon.
- Meters are `role="meter"` with a sentence in `aria-valuetext`. Tables have a caption. Sort state is `aria-sort`.
- `prefers-reduced-motion` turns the one animation off.

## Data

- Screens never call `fetch`. They use the hooks in `src/api/queries.ts` (TanStack Query) over the typed client in `src/api/client.ts`.
- `src/api/types.ts` is generated by `make types`. Never edit it; add an alias in `src/api/models.ts`.
- **Mock or live** (`VITE_API`): `npm run dev` and the tests read the fixtures in `../mocks` (`GET /api/<path>` → `mocks/<path>.json`). `VITE_API=live npm run dev` talks to `make serve` through the dev proxy. `npm run build` is live (the bundle is served by the API); `VITE_API=mock npm run build` builds on the fixtures.
- Real data only. `/kit` shows the B1 fixtures, read through the client; never invent an address or a figure for a screen.

## Commands (in `ui/`)

- `npm ci` once, then `npm run dev` (mock) or `VITE_API=live npm run dev`.
- `npm test`, `npm run typecheck`, `npm run lint`, `npm run build`.
- `npm run screenshots` (with the dev server running; `BASE_URL=` if it is not on 5173) writes `docs/screenshots/kit-*.png`, `case-*.png` and `desk-*.png` in both themes (and `desk-live-letter-*.pdf`, the letter printed), using a Chromium-family browser already installed (`BROWSER=` to choose). `npm run screenshots -- case` takes only the names that start so. `LIVE_URL=` (the interface run with `VITE_API=live` against `make serve`, after `make demo`) adds `case-live-*`, the real demo wallets; the last of them traces the hero wallet again (with the server on `OFFLINE=1`, from the cache).
- In mock mode a demo wallet's trace appears to take 2.4 seconds (`mockSettings.traceMs` in `src/api/mock.ts`) and reports progress worked out from the fixture's own graph, so the trace screen and the rail's animation can be seen with no server. Tests set it to 0.
