import { CircleCheck, CircleDashed, CircleSlash, ShieldCheck, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { API_MODE, api } from '../../api/api'
import { ApiError } from '../../api/client'
import type { AuditEntry, CaseDetail, VerifyCheck, VerifyResult } from '../../api/models'
import { useAudit, useVerifyCase } from '../../api/queries'
import { Button, buttonClass } from '../../components/Button'
import { CopyButton } from '../../components/CopyButton'
import { DataTable, type Column } from '../../components/DataTable'
import { cx } from '../../lib/cx'
import { formatDateTime } from '../../lib/format'
import { AUDIT_ACTIONS, CHECK_NAMES, CHECK_RESULTS } from '../caseText'

/** A SHA-256, whole: it is there to be compared character by character, or copied. */
function Digest({ value, label }: { value: string; label: string }) {
  return (
    <span className="inline-flex max-w-full items-start gap-0.5">
      <span className="break-all font-mono text-sm text-fg">{value}</span>
      <CopyButton value={value} label={label} className="-mt-1 shrink-0" />
    </span>
  )
}

function Row({ name, children }: { name: string; children: ReactNode }) {
  return (
    <>
      <dt className="pt-0.5 text-base text-muted">{name}</dt>
      <dd className="min-w-0 text-base text-fg">{children}</dd>
    </>
  )
}

const RESULT_ICONS = { same: CircleCheck, different: CircleSlash, not_checked: CircleDashed }

const checkColumns: Column<VerifyCheck>[] = [
  { key: 'name', header: 'Check', cell: (k) => <span className="whitespace-nowrap text-base font-medium">{CHECK_NAMES[k.name]}</span> },
  {
    key: 'result',
    header: 'Result',
    cell: (k) => {
      const Icon = RESULT_ICONS[k.result]
      return (
        <span className={cx('inline-flex items-center gap-1.5 whitespace-nowrap text-base', k.result === 'different' ? 'font-semibold text-fg' : 'text-fg')}>
          <Icon size={14} aria-hidden className={k.result === 'same' ? 'text-verified-text' : 'text-muted'} />
          {CHECK_RESULTS[k.result]}
        </span>
      )
    },
  },
  { key: 'detail', header: 'What was found', cell: (k) => <span className="text-base [overflow-wrap:anywhere]">{k.detail}</span> },
]

function Verified({ result }: { result: VerifyResult }) {
  const Icon = result.matches ? ShieldCheck : TriangleAlert
  return (
    <div className="flex flex-col gap-3">
      <div
        role="status"
        className={cx('flex items-start gap-2 rounded border px-3 py-2.5', result.matches ? 'border-verified-text bg-verified-wash' : 'border-seal-text bg-seal-wash')}
      >
        <Icon size={16} aria-hidden className={cx('mt-0.5 shrink-0', result.matches ? 'text-verified-text' : 'text-seal-text')} />
        <div>
          <p className="text-base font-medium text-fg">{result.summary}</p>
          <p className="tabular mt-0.5 font-mono text-sm text-muted">Checked {formatDateTime(result.checked_at)}</p>
        </div>
      </div>
      <DataTable caption="Checks" columns={checkColumns} rows={result.checks} rowKey={(k) => k.name} />
    </div>
  )
}

const auditColumns: Column<AuditEntry>[] = [
  {
    key: 'at',
    header: 'When',
    sortValue: (r) => r.at,
    cell: (r) => <span className="tabular whitespace-nowrap font-mono text-sm">{formatDateTime(r.at)}</span>,
  },
  {
    key: 'officer',
    header: 'Officer',
    sortValue: (r) => r.officer ?? null,
    cell: (r) => (r.officer ? <span className="text-base">{r.officer}</span> : <span className="text-base text-muted">Not signed in</span>),
  },
  { key: 'action', header: 'What', cell: (r) => <span className="text-base">{AUDIT_ACTIONS[r.action] ?? r.action}</span> },
  {
    key: 'status',
    header: 'Answer',
    align: 'right',
    cell: (r) => (
      <span className={cx('tabular whitespace-nowrap font-mono text-sm', r.status >= 400 ? 'font-semibold text-seal-text' : 'text-muted')}>
        {r.status >= 400 ? `Refused (${r.status})` : `Done (${r.status})`}
      </span>
    ),
  },
]

/** What makes the case checkable: the receipt (what was asked, what was read, what was found,
 *  with which code, labels and model), a way to compute it again, and who has looked at it. */
export function AuditTab({ c }: { c: CaseDetail }) {
  const p = c.provenance
  const verify = useVerifyCase(c.id)
  const audit = useAudit(c.id)
  const hasReceipt = !!p.findings_sha256
  const sources = p.data_sources.filter((s) => s !== 'label store')

  return (
    <div className="flex flex-col gap-7">
      <section aria-label="Receipt" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="eyebrow">Receipt</h3>
          <div className="flex flex-wrap items-center gap-2">
            {API_MODE === 'live' ? (
              <a href={api.caseFileUrl(c.id)} target="_blank" rel="noopener noreferrer" className={buttonClass('secondary', 'sm')}>
                Open the case file (PDF)
              </a>
            ) : (
              <span className="text-sm text-muted">The case file (PDF) needs the live API.</span>
            )}
            <Button size="sm" onClick={() => verify.mutate()} disabled={verify.isPending || !hasReceipt} icon={<ShieldCheck size={13} aria-hidden />}>
              {verify.isPending ? 'Verifying…' : 'Verify this case'}
            </Button>
          </div>
        </div>

        {!hasReceipt ? (
          <p className="text-base text-fg">This case was stored before receipts existed, so it cannot be verified. Trace it again to give it one.</p>
        ) : (
          <>
            <p className="max-w-prose text-base text-muted">
              Verifying traces the wallet again from the chain responses the first run read, and compares. The same responses, labels and code must give the
              same findings.
            </p>
            <dl className="grid grid-cols-[minmax(120px,auto)_1fr] gap-x-5 gap-y-2">
              <Row name="Findings fingerprint">
                <Digest value={p.findings_sha256!} label="findings fingerprint" />
                <span className="block text-sm text-muted">Every figure, address, time and transaction hash of the result; none of its wording.</span>
              </Row>
              {p.content_sha256 && (
                <Row name="Content digest">
                  <Digest value={p.content_sha256} label="content digest" />
                  <span className="block text-sm text-muted">The whole result as stored, wording included.</span>
                </Row>
              )}
              {p.input && p.input_sha256 && (
                <Row name="What was asked">
                  <span className="font-mono text-sm [overflow-wrap:anywhere]">
                    {p.input.address} · {p.input.chain} · up to {p.input.max_hops} hops{p.input.since ? ` · from ${p.input.since}` : ''}
                  </span>
                  <span className="block">
                    <Digest value={p.input_sha256} label="input digest" />
                  </span>
                </Row>
              )}
              {p.responses_sha256 && (
                <Row name="What was read">
                  <span>
                    {p.pages ?? p.responses?.length ?? 0} responses{sources.length > 0 && ` from ${sources.join(', ')}`}
                    {p.offline_replay && ', replayed from saved copies'}
                  </span>
                  <span className="block">
                    <Digest value={p.responses_sha256} label="responses digest" />
                  </span>
                  {p.responses && p.responses.length > 0 && (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-sm text-muted hover:text-fg">Every response, with its digest</summary>
                      <ol className="mt-2 flex flex-col gap-2">
                        {p.responses.map((r) => (
                          <li key={r.query + r.sha256} className="flex flex-col font-mono text-sm">
                            <span className="break-all text-fg">{r.query}</span>
                            <span className="break-all text-muted">{r.sha256}</span>
                          </li>
                        ))}
                      </ol>
                    </details>
                  )}
                </Row>
              )}
              {p.label_db_sha256 && (
                <Row name="Label database">
                  <Digest value={p.label_db_sha256} label="label database digest" />
                </Row>
              )}
              {p.model_sha256 && (
                <Row name="Model">
                  <span className="font-mono text-sm">{p.model_version}</span>
                  <span className="block">
                    <Digest value={p.model_sha256} label="model digest" />
                  </span>
                </Row>
              )}
              <Row name="Code">
                <span className="font-mono text-sm">{p.code_version}</span>
                {p.git_commit && (
                  <span className="font-mono text-sm text-muted">
                    {' · commit '}
                    {p.git_commit.slice(0, 12)}
                    {p.git_dirty && ' (with uncommitted changes)'}
                  </span>
                )}
                <span className="font-mono text-sm text-muted"> · seed {p.seed}</span>
              </Row>
            </dl>
          </>
        )}

        {p.notes && p.notes.length > 0 && (
          <ul className="flex flex-col gap-1 border-l-2 border-rule pl-3">
            {p.notes.map((note, i) => (
              <li key={i} className="text-base text-fg">
                {note}
              </li>
            ))}
          </ul>
        )}

        {verify.isError && (
          <p role="alert" className="rounded border border-seal-text bg-seal-wash px-3 py-2.5 text-base text-fg">
            {verify.error instanceof ApiError ? verify.error.detail : 'The case could not be verified. Try again.'}
          </p>
        )}
        {verify.data && <Verified result={verify.data} />}
      </section>

      <section aria-label="Access log" className="flex flex-col gap-3">
        <h3 className="eyebrow">Access log</h3>
        {audit.isError ? (
          <p className="text-base text-fg">{audit.error instanceof ApiError ? audit.error.detail : 'The access log could not be loaded.'}</p>
        ) : (
          <DataTable
            caption="Access log of this case"
            columns={auditColumns}
            rows={audit.data?.items ?? []}
            rowKey={(r) => String(r.seq)}
            loading={audit.isPending}
            initialSort={{ key: 'at', dir: 'desc' }}
            empty="Nobody has opened this case yet."
            maxHeight={360}
          />
        )}
      </section>
    </div>
  )
}
