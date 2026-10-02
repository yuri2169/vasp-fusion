/** The officer's words for what the contract names with codes. One place, so the graph's
 *  legend, the wallet panel and the tables say the same thing. */
import type { VerifyCheck } from '../api/models'
import type { Role } from '../lib/caseGraph'

export const ROLE_NAMES: Record<Role, string> = {
  suspect: 'Suspect wallet',
  intermediary: 'Wallet on the trail',
  unknown: 'Wallet not followed further',
  hub: 'Busy wallet, where the trail stops',
  exchange: 'Exchange wallet',
  exchange_hot: 'Exchange hot wallet',
  exchange_deposit: 'Deposit address',
  custodial_wallet: 'Custodial wallet',
  swap_service: 'Swap service',
  bridge: 'Bridge',
  mixer: 'Mixer',
  sanctioned: 'Sanctioned address',
}

/** The roles in the order a legend lists them: the wallet, the trail, then where it can end. */
export const ROLE_ORDER: Role[] = [
  'suspect',
  'intermediary',
  'unknown',
  'hub',
  'exchange_deposit',
  'exchange',
  'exchange_hot',
  'custodial_wallet',
  'swap_service',
  'bridge',
  'mixer',
  'sanctioned',
]

export const CHECK_NAMES: Record<VerifyCheck['name'], string> = {
  stored_case: 'Stored case',
  replay: 'Replay',
  responses: 'Chain responses',
  findings: 'Findings',
  content: 'Wording',
  labels: 'Label database',
  model: 'Model',
  code: 'Code',
}

export const CHECK_RESULTS: Record<VerifyCheck['result'], string> = {
  same: 'Same',
  different: 'Different',
  not_checked: 'Not checked',
}

/** case.view → "Opened the case". Unknown actions are shown as the log has them. */
export const AUDIT_ACTIONS: Record<string, string> = {
  'case.open': 'Opened a case for the wallet',
  'case.view': 'Read the case',
  'case.export': 'Exported the case file',
  'case.receipt': 'Read the receipt',
  'case.verify': 'Verified the case',
}
