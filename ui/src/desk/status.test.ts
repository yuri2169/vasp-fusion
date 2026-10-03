import { describe, expect, it } from 'vitest'
import type { RequestDetail, StatusEvent } from '../api/models'
import { readDesk } from '../test/files'
import { isOverdue, slipSteps } from './status'

const at = (status: StatusEvent['status'], day: number): StatusEvent => ({ status, at: `2026-10-${String(day).padStart(2, '0')}T09:00:00Z`, note: null, by: null })
const shape = (steps: ReturnType<typeof slipSteps>) => steps.map((s) => `${s.label}:${s.state}`)

describe('the routing slip of a request', () => {
  it('a real draft: stamped once, approval is next', () => {
    const draft = readDesk<RequestDetail>('request-drafted')
    expect(shape(slipSteps(draft.status_history, draft.status))).toEqual(['Drafted:done', 'Approved:next', 'Sent:todo', 'Acknowledged:todo', 'Reply:todo'])
  })

  it('a real sent request: three stamps with their events, the acknowledgement is next', () => {
    const sent = readDesk<RequestDetail>('request-sent')
    const steps = slipSteps(sent.status_history, sent.status)
    expect(shape(steps)).toEqual(['Drafted:done', 'Approved:done', 'Sent:done', 'Acknowledged:next', 'Reply:todo'])
    expect(steps[2].event?.note).toMatch(/SAHYOG outbox/)
  })

  it('sent back to draft: the approval stamp is gone and is next again', () => {
    const history = [at('drafted', 1), at('approved', 2), at('drafted', 3)]
    const steps = slipSteps(history, 'drafted')
    expect(shape(steps).slice(0, 2)).toEqual(['Drafted:done', 'Approved:next'])
    expect(steps[0].event).toBe(history[0]) // the day it was first drafted
  })

  it('a reply without an acknowledgement passes that box over, and the last box says what the exchange did', () => {
    const steps = slipSteps([at('drafted', 1), at('approved', 1), at('sent', 1), at('answered', 6)], 'answered')
    expect(shape(steps)).toEqual(['Drafted:done', 'Approved:done', 'Sent:done', 'Acknowledged:skipped', 'Answered:done'])
  })

  it('a freeze confirmed after an answer shows the freeze; a refusal ends the slip', () => {
    const frozen = slipSteps([at('drafted', 1), at('approved', 1), at('sent', 1), at('acknowledged', 2), at('answered', 6), at('freeze_confirmed', 7)], 'freeze_confirmed')
    expect(shape(frozen).at(-1)).toBe('Freeze confirmed:done')
    const refused = slipSteps([at('drafted', 1), at('approved', 1), at('sent', 1), at('refused', 4)], 'refused')
    expect(shape(refused).at(-1)).toBe('Refused:void')
  })

  it('a withdrawn request keeps what happened and ends there', () => {
    expect(shape(slipSteps([at('drafted', 1), at('approved', 2), at('withdrawn', 3)], 'withdrawn'))).toEqual(['Drafted:done', 'Approved:done', 'Withdrawn:void'])
  })
})

describe('overdue', () => {
  it('is from the day after the reply was due, and only while a reply is awaited', () => {
    const due = '2026-10-10'
    expect(isOverdue({ status: 'sent', due }, new Date('2026-10-10T23:00:00Z'))).toBe(false)
    expect(isOverdue({ status: 'sent', due }, new Date('2026-10-11T00:30:00Z'))).toBe(true)
    expect(isOverdue({ status: 'acknowledged', due }, new Date('2026-10-12T00:00:00Z'))).toBe(true)
    expect(isOverdue({ status: 'answered', due }, new Date('2026-10-12T00:00:00Z'))).toBe(false)
    expect(isOverdue({ status: 'drafted', due: null }, new Date('2026-10-12T00:00:00Z'))).toBe(false)
  })
})
