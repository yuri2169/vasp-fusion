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
| `HopRail` | The path of the funds, ending in the stamp |
| `DataTable` | Any list of records: sortable, sticky header, rows open with a click or Enter |
| `PageHeader` | The top of a screen |
| `EmptyState`, `ErrorState`, `Skeleton` | Nothing yet, something failed, on its way |
| `ToastProvider`, `useToast` | Confirm an action; errors stay until dismissed |
| `Dialog` | A decision that should not be made in passing |
| `Tip`, `useTip` | A small card on hover and focus, drawn in `<body>` so nothing clips it |

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
- `npm run screenshots` (with the dev server running; `BASE_URL=` if it is not on 5173) writes `docs/screenshots/kit-*.png` in both themes, using a Chromium-family browser already installed (`BROWSER=` to choose).
