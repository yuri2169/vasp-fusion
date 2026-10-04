import { useId, useState, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import type { RequestDetail, RequestStatus } from '../api/models'
import { useMoveRequest } from '../api/queries'
import { Button } from '../components/Button'
import { Dialog } from '../components/Dialog'
import { useToast } from '../components/Toast'
import { isReply, REPLY_WORDS } from './status'

type Intent = 'approve' | 'send' | 'reply' | 'back' | 'withdraw'

const TOAST: Record<Intent, string> = {
  approve: 'Request approved',
  send: 'Marked as sent',
  reply: 'Reply recorded',
  back: 'Sent back to draft',
  withdraw: 'Request withdrawn',
}

/** The steps the server allows from here (`allowed_next`), each as a button that names it and a
 *  dialog that says what it does. The one saffron button is the step that moves the request forward. */
export function RequestActions({ request }: { request: RequestDetail }) {
  const move = useMoveRequest(request.id)
  const toast = useToast()
  const noteId = useId()
  const [intent, setIntent] = useState<Intent | null>(null)
  const [note, setNote] = useState('')
  const [reply, setReply] = useState<RequestStatus | null>(null)

  const next = request.allowed_next ?? []
  const replies = next.filter(isReply)
  const awaiting = request.status === 'sent' || request.status === 'acknowledged'
  const notes = request.letter.review_notes ?? []

  const open = (to: Intent) => {
    move.reset()
    setNote('')
    setReply(replies[0] ?? null)
    setIntent(to)
  }
  const close = () => setIntent(null)

  const status: RequestStatus | null =
    intent === 'approve' ? 'approved' : intent === 'send' ? 'sent' : intent === 'back' ? 'drafted' : intent === 'withdraw' ? 'withdrawn' : reply

  const confirm = () => {
    if (!intent || !status) return
    move.mutate(
      { status, note: note.trim() || null },
      {
        onSuccess: () => {
          toast.show({ kind: 'success', title: TOAST[intent], detail: `${request.reference} to ${request.vasp}` })
          close()
        },
      },
    )
  }

  const DIALOG: Record<Intent, { title: string; body: ReactNode; confirm: string; noteLabel: string; danger?: boolean }> = {
    approve: {
      title: `Approve the request to ${request.vasp}?`,
      body: (
        <p>
          Approving removes the draft watermark and makes the letter ready to send. It is not sent yet.
          {notes.length > 0 && ` ${notes.length} ${notes.length === 1 ? 'point is' : 'points are'} listed beside the letter to check first.`}
        </p>
      ),
      confirm: 'Approve request',
      noteLabel: 'Note for the record (optional)',
    },
    send: {
      title: `Mark the request to ${request.vasp} as sent?`,
      body: (
        <p>
          The letter and its data are handed to the SAHYOG gateway set up for this installation, and the day a reply is expected is set. A sent request
          cannot be withdrawn or edited.
        </p>
      ),
      confirm: 'Mark as sent',
      noteLabel: 'Note for the record (optional)',
    },
    reply: {
      title: `Record the reply from ${request.vasp}`,
      body: (
        <fieldset className="flex flex-col gap-2.5">
          <legend className="eyebrow mb-2">What did it reply?</legend>
          {replies.map((option) => (
            <label key={option} className="flex cursor-pointer items-start gap-2.5">
              <input
                type="radio"
                name="reply"
                className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--fg)]"
                checked={reply === option}
                onChange={() => setReply(option)}
              />
              <span>
                <span className="font-medium">{REPLY_WORDS[option]!.name}</span>
                <span className="block text-xs text-muted">{REPLY_WORDS[option]!.means}</span>
              </span>
            </label>
          ))}
        </fieldset>
      ),
      confirm: 'Record reply',
      noteLabel: 'What it said, and how the reply arrived',
    },
    back: {
      title: 'Send this request back to draft?',
      body: <p>The approval is removed and the draft watermark returns. It has to be approved again before it can be sent.</p>,
      confirm: 'Send back to draft',
      noteLabel: 'Why (optional)',
    },
    withdraw: {
      title: `Withdraw the request to ${request.vasp}?`,
      body: <p>The request stays in the register as withdrawn and is never sent. Its wallets can then be put in a new request.</p>,
      confirm: 'Withdraw request',
      noteLabel: 'Why (optional)',
      danger: true,
    },
  }
  const dialog = intent ? DIALOG[intent] : null

  return (
    <div className="flex flex-col gap-2">
      {next.includes('approved') && (
        <Button variant="primary" onClick={() => open('approve')}>
          Approve request
        </Button>
      )}
      {next.includes('sent') && (
        <Button variant="primary" onClick={() => open('send')}>
          Mark as sent (via SAHYOG)
        </Button>
      )}
      {replies.length > 0 && (
        <Button variant={awaiting ? 'primary' : 'secondary'} onClick={() => open('reply')}>
          Record reply from {request.vasp}
        </Button>
      )}
      {next.includes('drafted') && <Button onClick={() => open('back')}>Send back to draft</Button>}
      {next.includes('withdrawn') && (
        <Button variant="ghost" onClick={() => open('withdraw')}>
          Withdraw request
        </Button>
      )}

      {dialog && (
        <Dialog
          open
          onClose={close}
          title={dialog.title}
          footer={
            <>
              <Button onClick={close}>Cancel</Button>
              <Button variant={dialog.danger ? 'danger' : 'primary'} disabled={move.isPending || !status} onClick={confirm}>
                {dialog.confirm}
              </Button>
            </>
          }
        >
          <div className="flex flex-col gap-4">
            {dialog.body}
            <div className="flex flex-col gap-1.5">
              <label htmlFor={noteId} className="eyebrow">
                {dialog.noteLabel}
              </label>
              <textarea
                id={noteId}
                rows={2}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="rounded border border-rule-strong bg-surface px-2.5 py-1.5 text-sm text-fg"
              />
            </div>
            {move.isError && (
              <p role="alert" className="rounded border border-seal-text bg-seal-wash px-3 py-2 text-seal-text [overflow-wrap:anywhere]">
                {move.error instanceof ApiError ? move.error.detail : 'The request could not be changed. Try again.'}
              </p>
            )}
          </div>
        </Dialog>
      )}
    </div>
  )
}
