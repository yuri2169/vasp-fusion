/** The nine pipeline stages, and what each one actually does.
 *
 * Lives here rather than in Processing.tsx because the landing page's
 * "how it works" section teaches the same nine stages before a run exists.
 * One copy: the wait screen and the explainer can never drift apart.
 *
 * Figures come from figures.json, written from the pinned artefacts by
 * scripts/export_figures.py - never typed here.
 */
import F from './figures.json';

/** 836843 -> "837,000"; 1816507 -> "1.8 million". */
export const thousands = (n: number) => `${Math.round(n / 1000).toLocaleString()},000`;
export const millions = (n: number, dp = 1) => `${(n / 1e6).toFixed(dp)} million`;
export const pc = (x: number, dp = 2) => `${(x * 100).toFixed(dp)}%`;
export { F };

export const STAGES: [string, string][] = [
  ['ingest', 'parse CSV / JSONL / XML, quarantine bad rows'],
  ['enrich', 'resolve every IP to ASN and country, offline'],
  ['resolve', 'collapse addresses into actors — CoinJoins kept apart'],
  ['graph', 'actor-to-actor money flow, entity × IP matrix'],
  ['features', `${F.n_features} features per actor${F.uses_embeddings ? ', including Node2Vec' : ''}`],
  ['detect', 'score every actor, calibrate to this capture’s base rate'],
  ['attribute', 'which IP is really theirs — answered only within an error bound'],
  ['explain', 'exact SHAP, turned into English'],
  ['store', 'write the case files'],
];

/* What each stage is actually doing, at the size someone will read it.
 *
 * A hundred seconds of waiting is the longest uninterrupted attention this
 * interface ever gets. Spending it on a spinner wastes the best teaching moment
 * in the demo, so the panel below the track explains the running stage - and
 * these are the real mechanisms, not progress-bar filler. */
export const DETAIL: [string, string][] = [
  ['Reading the capture',
   'CSV, JSONL and XML all parse to one internal frame, and all three are verified to ' +
   'produce identical clean-row counts. Rows that fail validation are quarantined with a ' +
   'named reason and counted in the receipt — never silently dropped, because an analyst ' +
   'has to know what was excluded before trusting what was kept.'],
  ['Locating every peer',
   'Each IP resolves to an ASN, a country and an infrastructure class from a DB-IP Lite ' +
   'database bundled inside the image. No lookup leaves this machine. Infrastructure class ' +
   'matters later: it is what decides whether an attribution is trustworthy or suppressed.'],
  ['Addresses become actors',
   'Bitcoin has addresses, not people. But if one transaction spends from five addresses at ' +
   'once, whoever signed it held all five private keys — so those addresses are one actor. ' +
   `Chain those merges and ${millions(F.bulk_n_addresses)} addresses collapse into roughly ` +
   `${thousands(F.bulk_n_entities)} actors. The exception is a CoinJoin — many people paying ` +
   'in together on purpose, each taking back an identical amount — whose inputs are left ' +
   'apart, because merging them would fuse strangers. Verified on real Bitcoin: addresses ' +
   `this groups share a label ${pc(F.epp_label_agreement)} of the time.`],
  ['Drawing the money',
   'Actor-to-actor flow, PageRank and sampled betweenness, plus the sparse entity × IP ' +
   'co-occurrence matrix the attribution test needs. Sparse, not dense — that is what keeps ' +
   '2.4 million rows inside laptop memory.'],
  ['Describing each actor',
   `${F.n_features} numbers per actor: chain behaviour, timing rhythm, network posture and ` +
   'position in the money graph. Learned graph embeddings were measured and left out: they ' +
   'helped only on the capture they were fitted to. The most expensive stage by far, and ' +
   'fully vectorised — it is expressed as Polars expressions so the whole matrix computes in ' +
   'parallel rather than row by row.'],
  ['Scoring every actor',
   'Gradient-boosted trees score all of them, then isotonic regression calibrates the output ' +
   'so that 0.90 means roughly a 90% chance rather than merely "higher than 0.80" — then moves ' +
   'that probability to this capture’s own base rate, estimated from the scores alone. ' +
   `Measured calibration error on the bulk profile: ${F.ece_shown} (${F.ece_before_prior_shift} ` +
   'before that correction).'],
  ['Who was it?',
   'For every actor–IP pair, a hypergeometric test asks whether they co-occur more than ' +
   'chance predicts given how much traffic each generates — with Benjamini–Hochberg control ' +
   'across all pairs at α = 0.01. An IP is then named only for kinds of host where the ' +
   `error among named answers stays under ${pc(F.attribution_target_risk ?? 0.05, 0)} with ` +
   '95% confidence on held-out data; VPN, Tor and CDN exits are never named. On the bulk ' +
   `run it named ${F.attribution_answered.toLocaleString()} actors, ` +
   `${pc(F.attribution_error_among_answered ?? 0, 1)} of them wrongly, and declined ` +
   `${F.attribution_declined.toLocaleString()}.`],
  ['Why it was flagged',
   'Exact SHAP values — TreeExplainer, not an approximation — for the alerts actually shown. ' +
   `Sixty of them, not ${thousands(F.bulk_n_entities)}: there is no reason to explain alerts nobody will open. The ` +
   'top contributions become an English narrative an analyst can act on.'],
  ['Writing the case files',
   'Alerts, evidence chains with real TXIDs, attributions, SHAP rows and the run provenance ' +
   'all go to DuckDB — the input SHA-256, the seed, the feature version, the model backend ' +
   'and the git commit, so every figure traces back to an exact input and an exact model.'],
];

/* The same nine stages in plain English, for the landing page.
 *
 * DETAIL above is written for someone who already knows what a hypergeometric
 * test is; this is written for the first thirty seconds, before anyone has
 * agreed to care. Both are true and both describe the same code - the landing
 * shows the plain line first and the technical one under it, so nobody has to
 * choose which audience the page is for. */
export const PLAIN: string[] = [
  'Read the file. Anything malformed is set aside and counted — never quietly dropped, ' +
  'because you have to know what was excluded before you can trust what was kept.',

  'Work out which network each IP address belongs to, using a database that ships inside ' +
  'the image. Nothing is looked up over the internet, because there is no internet.',

  'Bitcoin has addresses, not people. If one payment spends from five addresses at once, ' +
  'one person held all five keys — so those five are one owner. Repeat until nothing merges, ' +
  'except where many people deliberately pay in together (a CoinJoin).',

  'Draw who paid whom, and separately, which owners were seen coming from which IP addresses. ' +
  'Both are needed: one is the money, the other is the machine.',

  `Describe every owner with ${F.n_features} numbers — how they spend, what hours they keep, who they ` +
  'deal with, where they sit in the flow of money.',

  'Score every owner for how unusual they look, then convert that score into an honest ' +
  'probability, so 0.90 means about a nine-in-ten chance rather than just "more than 0.80".',

  'Ask whether an owner and an IP genuinely belong together or merely appear together. ' +
  'If the answer is a shared VPN or an exchange, it says nothing rather than naming the wrong machine.',

  `For each alert, work out which of those ${F.n_features} numbers actually moved the score, and turn ` +
  'the top few into a sentence an analyst can act on.',

  'Save the alerts, the evidence and a receipt: the exact input file, the seed, the model, ' +
  'the commit. Every figure on screen can be traced back to all four.',
];
