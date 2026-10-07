/** The words and the order of a request's life, as the backend defines them
 *  (vaspfusion/desk/service.py): drafted → approved → sent → acknowledged →
 *  answered | freeze_confirmed | refused, or withdrawn before it is sent. */
import type { Ask, FollowUp, RequestDetail, RequestStatus, RequestSummary, StatusEvent, VaspDirectoryEntry } from '../api/models'
import { formatDate } from '../lib/format'

export type DeskStatus = RequestStatus | 'not_requested'

export const STATUS_WORDS: Record<DeskStatus, string> = {
  not_requested: 'Not requested',
  drafted: 'Draft',
  approved: 'Approved',
  sent: 'Sent',
  acknowledged: 'Acknowledged',
  answered: 'Answered',
  freeze_confirmed: 'Freeze confirmed',
  refused: 'Refused',
  withdrawn: 'Withdrawn',
}

/** In the register's filter, and wherever statuses are listed in order. */
export const STATUS_ORDER: RequestStatus[] = ['drafted', 'approved', 'sent', 'acknowledged', 'answered', 'freeze_confirmed', 'refused', 'withdrawn']

/** Still on the officer's desk: something is left to do or to wait for. */
export const isOpen = (status: RequestStatus) => ['drafted', 'approved', 'sent', 'acknowledged', 'answered'].includes(status)

export const ASK_ORDER: Ask[] = ['kyc', 'transactions', 'freeze', 'preservation']
export const ASK_WORDS: Record<Ask, string> = {
  kyc: 'KYC records',
  transactions: 'Transaction records',
  freeze: 'Freeze',
  preservation: 'Preservation of records',
}

export const FOLLOW_UP_WORDS: Record<FollowUp['kind'], string> = {
  reply_overdue: 'Reply overdue',
  reply_due: 'Reply awaited',
  freeze_lapsing: 'Freeze about to lapse',
  preservation_closing: 'Preservation window closing',
}

/** What the officer records when the exchange answers, in the order the buttons offer it. */
export const REPLY_WORDS: Partial<Record<RequestStatus, { name: string; means: string }>> = {
  acknowledged: { name: 'Acknowledged', means: 'It confirmed it received the request. The records are still awaited.' },
  answered: { name: 'Answered', means: 'It furnished the records asked for.' },
  freeze_confirmed: { name: 'Freeze confirmed', means: 'It confirmed the accounts are frozen.' },
  refused: { name: 'Refused', means: 'It declined the request. The wallets can be put in a new request.' },
}
export const isReply = (status: RequestStatus) => status in REPLY_WORDS

/** A reply is awaited and its day has passed (the desk's own rule: from the day after `due`, UTC). */
export function isOverdue(r: Pick<RequestSummary, 'status' | 'due'>, today: Date = new Date()): boolean {
  if (!r.due || (r.status !== 'sent' && r.status !== 'acknowledged')) return false
  return today.toISOString().slice(0, 10) > r.due
}

/** Whole days from today (UTC, as the server counts) to the day a reply is due; negative once it has passed. */
export function daysLeft(due: string, today: Date = new Date()): number {
  const day = (iso: string) => Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)))
  return Math.round((day(due) - day(today.toISOString())) / 86_400_000)
}

/** "5 days left", "due today", "3 days overdue". */
export function daysLeftWords(left: number): string {
  const n = Math.abs(left)
  const days = `${n} ${n === 1 ? 'day' : 'days'}`
  return left < 0 ? `${days} overdue` : left === 0 ? 'due today' : `${days} left`
}

export type SlipKey = 'drafted' | 'approved' | 'sent' | 'acknowledged' | 'reply' | 'withdrawn'

export interface SlipStep {
  key: SlipKey
  /** What the box says: the step, or for the last box what the exchange did. */
  label: string
  /** done: it happened. next: the one that is awaited now. todo: not reached. skipped: passed over. void: ended here. */
  state: 'done' | 'next' | 'todo' | 'skipped' | 'void'
  event?: StatusEvent
}

const OUTCOMES: RequestStatus[] = ['answered', 'freeze_confirmed', 'refused']

/** The routing slip of a request: five boxes in order, each with the event that stamped it.
 *  A request sent back to draft loses its approval stamp. A reply that came without an
 *  acknowledgement leaves that box passed over. A withdrawn request ends in one box that says so. */
export function slipSteps(history: StatusEvent[], status: RequestStatus): SlipStep[] {
  const stamped: Partial<Record<SlipKey, StatusEvent>> = {}
  let outcome: RequestStatus | null = null
  for (const event of history) {
    if (event.status === 'drafted') {
      stamped.drafted ??= event
      delete stamped.approved // sent back: it has to be approved again
    } else if (OUTCOMES.includes(event.status)) {
      stamped.reply = event
      outcome = event.status
    } else stamped[event.status as SlipKey] = event
  }

  const order: SlipKey[] = ['drafted', 'approved', 'sent', 'acknowledged', 'reply']
  const label = (key: SlipKey) => (key === 'reply' ? (outcome ? STATUS_WORDS[outcome] : 'Reply') : key === 'drafted' ? 'Drafted' : STATUS_WORDS[key as RequestStatus])

  if (status === 'withdrawn') {
    const kept = order.filter((key) => stamped[key]).map<SlipStep>((key) => ({ key, label: label(key), state: 'done', event: stamped[key] }))
    return [...kept, { key: 'withdrawn', label: 'Withdrawn', state: 'void', event: stamped.withdrawn }]
  }

  const last = order.reduce((at, key, i) => (stamped[key] ? i : at), 0)
  return order.map((key, i) => {
    const event = stamped[key]
    if (event) return { key, label: label(key), state: key === 'reply' && outcome === 'refused' ? 'void' : 'done', event }
    if (i < last) return { key, label: label(key), state: 'skipped' }
    return { key, label: label(key), state: i === last + 1 ? 'next' : 'todo' }
  })
}

const dueBasis = (r: RequestDetail) =>
  r.due_basis === 'officer' ? ', the day the officer set' : r.due_basis === 'office_setting' ? ", by this office's reminder setting" : ''

/** One line under the status: what the request is waiting for. */
export function standing(r: RequestDetail): string {
  switch (r.status) {
    case 'drafted':
      return 'A draft. Read the letter against the points to check, then approve it. Nothing has been sent.'
    case 'approved':
      return 'Approved, not sent yet. Mark it as sent to hand it to the SAHYOG gateway.'
    case 'sent':
      return r.due ? `Sent. A reply is expected by ${formatDate(r.due)}${dueBasis(r)}.` : 'Sent. A reply is awaited.'
    case 'acknowledged':
      return r.due ? `${r.vasp} confirmed receipt. Its answer is expected by ${formatDate(r.due)}.` : `${r.vasp} confirmed receipt. Its answer is awaited.`
    case 'answered':
      return `${r.vasp} has answered. If a freeze was asked for, record it once it is confirmed.`
    case 'freeze_confirmed':
      return `${r.vasp} confirmed the freeze. Nothing is left to do on this request.`
    case 'refused':
      return `${r.vasp} refused. Its wallets can be put in a new request.`
    case 'withdrawn':
      return 'Withdrawn before it was sent. Its wallets can be put in a new request.'
  }
}

/** FIU-IND registration in words, always with the date its source speaks for. null is "no source", never "no". */
export function registrationWords(d: Pick<VaspDirectoryEntry, 'fiu_ind_registered' | 'fiu_ind_as_of'>): string {
  const asOf = d.fiu_ind_as_of ? `, as of ${formatDate(d.fiu_ind_as_of)}` : ''
  if (d.fiu_ind_registered === true) return `Registered${asOf}`
  if (d.fiu_ind_registered === false) return `Named by FIU-IND as operating unregistered${asOf}`
  return 'No source found'
}

/** 14 s; 2 min 30 s; 3 h 2 min; 2 d 1 h. The server's own wording (desk/timeline.py). */
export function elapsedWords(seconds: number): string {
  if (seconds < 1) return 'under 1 s'
  const s = Math.round(seconds)
  if (s < 60) return `${s} s`
  if (s < 3600) return `${Math.floor(s / 60)} min${s % 60 ? ` ${s % 60} s` : ''}`
  if (s < 86400) return `${Math.floor(s / 3600)} h${Math.floor((s % 3600) / 60) ? ` ${Math.floor((s % 3600) / 60)} min` : ''}`
  return `${Math.floor(s / 86400)} d${Math.floor((s % 86400) / 3600) ? ` ${Math.floor((s % 86400) / 3600)} h` : ''}`
}

export const letterOfRequestLink = (vasp: string, caseId?: string) =>
  `/vasps/${encodeURIComponent(vasp)}/letter-of-request${caseId ? `?case=${encodeURIComponent(caseId)}` : ''}`
