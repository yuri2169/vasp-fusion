/** The nine stages of a case, and what each one does.
 *
 *  One file, read by the landing's "how it works" and by the wait screen of a trace, so the
 *  two cannot drift apart. Three registers of the same nine stages:
 *    STAGES  the name and one line
 *    PLAIN   the first thirty seconds, for someone who has not yet agreed to care
 *    DETAIL  the mechanism, for someone who will check it
 *
 *  NO FIGURE IS TYPED HERE. A number on the landing comes from the tool's own measurements
 *  (the same answers the Model page and the dashboard read), or it is not shown. */
import type { Layer } from './components/Panel'

export const STAGES: [string, string][] = [
  ['intake', 'check the address, name its chain, open the case'],
  ['fetch', 'read the wallet’s transfers from the chain'],
  ['label', 'look every wallet met up in the label store'],
  ['trace', 'follow the money, hop by hop, to the first labelled wallet'],
  ['discover', 'find deposit addresses no list has labelled yet'],
  ['attribute', 'rank the exchanges reached: proximity and confidence, kept apart'],
  ['decide', 'name an exchange, or say the evidence is insufficient'],
  ['explain', 'the reasons, each with the transactions that prove it'],
  ['deliver', 'the request letter, the case file, the receipt'],
]

/** The layer each stage belongs to: the footer's colour key, applied to the pipeline. */
export const STAGE_LAYER: Layer[] = ['data', 'chain', 'network', 'chain', 'network', 'fusion', 'fusion', 'fusion', 'confirm']

export const PLAIN: string[] = [
  'Paste a wallet address. The tool reads which chain it belongs to from its shape and its checksum, so a typing mistake is caught before anything is traced.',

  'Read every transfer the wallet made and received. On the demonstration wallets this is replayed from recorded chain responses, so it runs with the network closed.',

  'A blockchain has addresses, not names. Each wallet the money touches is looked up in a store of labelled addresses, and every label carries how strong it is: published by the exchange itself, on a curated list, tagged by an explorer, or derived by this tool.',

  'Follow the money out of the wallet, one hop at a time. A branch stops at the first labelled wallet, at a busy wallet where many senders’ funds mix, or at the hop limit.',

  'An exchange gives each customer their own deposit address, and most of those are on no list. They give themselves away by what they do: they forward what they receive to the exchange’s main wallet.',

  'Each exchange reached gets two separate answers: how near it is to the wallet, and how sure the tool is that the address really is that exchange’s. They are never merged into one score.',

  'Name the nearest exchange only when its confidence clears a fixed bar. Under the bar, the answer is “insufficient evidence”, with what would change it. A wrong name sends a notice to the wrong company.',

  'Every reason is a sentence with the transactions behind it, and the named exchange is traced again with its strongest label removed, to see whether the answer holds.',

  'Draft the request to the exchange with its legal basis, print the case file, and keep a receipt that lets anyone trace the case again and compare.',
]

export const DETAIL: [string, string][] = [
  ['Opening the case',
    'The address is checked in the browser with the chain’s own rules (Base58Check for Tron and legacy Bitcoin, Bech32 for SegWit, EIP-55 for EVM chains), then again by the tool. One case per wallet: a wallet that already has a case opens it as it was last traced.'],
  ['Reading the wallet',
    'Transfers come through one adapter per chain family (Tron, EVM, Bitcoin) and are stored as they came. A stored response is replayed byte for byte, which is what makes a trace repeatable: the same wallet gives the same fingerprint.'],
  ['Who is this address?',
    'Labels come from public, licensed sources and keep their source and their tier. The tier decides how much a label can carry: a derived label is never passed off as a published one, and it is drawn differently everywhere it appears.'],
  ['Following the money',
    'Hop by hop from the wallet, in the asset it moved most, with the share of the funds carried along each branch. The funders of the wallet are read too, for the inbound view. Stopping at the first labelled wallet is what keeps the answer the nearest exchange, not the largest.'],
  ['Deposit addresses that are on no list',
    'On Tron, a customer’s deposit address is swept to the exchange’s hot wallet, often with the fee paid by a wallet the exchange funds. The sweep and the fee payer are evidence in themselves; a gradient-boosted model, calibrated so that its probability means what it says, scores wallets that behave the same way.'],
  ['Nearest, and how sure',
    'Proximity is hops, then the share of the funds, then the time taken. Confidence is the label’s own strength, or the model’s calibrated probability with its range. The two are shown as two different meters so that neither can be read as the other.'],
  ['Naming, or declining to',
    'The bar was measured, not chosen: real exchange customers were traced with the derived labels hidden, and the share named wrongly at each bar was counted. A sanctioned address or a mixer on the path is reported as its own outcome.'],
  ['Why this exchange',
    'The model’s reasons are exact SHAP values for the wallet in question, in words. The counterfactual removes the strongest label and traces again; an answer that survives is said to, and one that does not is said not to.'],
  ['What the officer leaves with',
    'A request letter addressed to the exchange’s own contact, moved by the officer from draft to approved to sent; a case file with every transaction; and a provenance receipt (the inputs, the seed, the versions) that Verify replays to the same fingerprint.'],
]

/** Which stage a running trace is in, from what the trace reports (`CaseProgress.phase`).
 *  A trace reports four phases, not nine: the track lights the stage each belongs to, and the
 *  stages after the last one finish together when the result arrives. */
export function stageOf(status: string, phase?: string | null): number {
  if (status === 'queued' || !phase) return status === 'running' ? 1 : 0
  return { reading: 1, outbound: 3, inbound: 3, checking: 4 }[phase] ?? 1
}
