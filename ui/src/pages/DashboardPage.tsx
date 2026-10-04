import { OctagonAlert, Radar, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router'
import { ApiError } from '../api/client'
import type { Alert, Dashboard } from '../api/models'
import { useDashboard } from '../api/queries'
import { BarList } from '../charts/BarList'
import { ShareBar } from '../charts/ShareBar'
import { AddressChip } from '../components/AddressChip'
import { ChainBadge } from '../components/ChainBadge'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/Skeleton'
import { TierTag } from '../components/TierTag'
import { CHAINS } from '../lib/chains'
import { cx } from '../lib/cx'
import { useRupees } from '../components/Rupees'
import { formatDate, formatDuration, formatUsd } from '../lib/format'
import { Ledger, Panel, type LedgerEntry } from '../overview/parts'
import { chainName, count, plural } from '../overview/words'
import type { Tier } from '../api/models'

const TIER_ORDER: Tier[] = ['published_por', 'curated', 'explorer_tag', 'derived']
const CHAINS_SHOWN = 6

function ledger(d: Dashboard): LedgerEntry[] {
  const c = d.counts
  return [
    {
      key: 'cases',
      name: 'Cases',
      value: count(c.cases_total),
      note: c.tracing ? `${count(c.tracing)} being traced now` : 'one per wallet',
      to: '/cases',
    },
    {
      key: 'open',
      name: 'Open cases',
      value: count(c.open_cases),
      note: 'being traced, or an exchange has not replied',
      to: '/cases?open=1',
    },
    {
      key: 'named',
      name: 'Exchange named',
      value: count(c.wallets_attributed),
      note: 'cases that name an exchange',
      to: '/cases?outcome=ATTRIBUTED',
    },
    {
      key: 'towrite',
      name: 'Exchanges to write to',
      value: count(c.awaiting_request ?? 0),
      note: 'a wallet is in no request yet',
      to: '/desk',
    },
    {
      key: 'awaiting',
      name: 'Awaiting a reply',
      value: count(c.requests_awaiting_reply),
      note: 'requests sent, not answered',
      to: '/requests?status=awaiting',
    },
    {
      key: 'watched',
      name: 'Watched wallets',
      value: count(c.watched ?? 0),
      note: 'checked on request',
      to: '/watchlist',
    },
  ]
}

const ALERT_LOOK: Record<Alert['severity'], { Icon: typeof OctagonAlert; word: string; row: string; icon: string }> = {
  high: {
    Icon: OctagonAlert,
    word: 'Alert',
    row: 'border-seal-text',
    icon: 'text-seal-text',
  },
  warn: {
    Icon: TriangleAlert,
    word: 'Change',
    row: 'border-rule-strong',
    icon: 'text-fg',
  },
  info: {
    Icon: Radar,
    word: 'Activity',
    row: 'border-rule',
    icon: 'text-muted',
  },
}

function AlertRow({ alert }: { alert: Alert }) {
  const look = ALERT_LOOK[alert.severity]
  return (
    <li className={cx('flex flex-col gap-1.5 rounded border px-3 py-2.5', look.row)}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className={cx('inline-flex items-center gap-1.5 text-sm font-semibold', look.icon)}>
          <look.Icon size={14} aria-hidden />
          {look.word}
        </span>
        <span className="tabular text-sm text-muted">{formatDate(alert.at)}</span>
      </div>
      <p className="text-base text-fg [overflow-wrap:anywhere]">{alert.text}</p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <AddressChip address={alert.wallet} chain={alert.chain} to={`/wallets/${alert.chain}/${encodeURIComponent(alert.wallet)}`} actions="copy" />
        {alert.case_id && (
          <Link to={`/cases/${encodeURIComponent(alert.case_id)}`} className="text-sm underline decoration-rule-strong underline-offset-2 hover:decoration-current">
            Open the case
          </Link>
        )}
      </div>
    </li>
  )
}

function Coverage({ d }: { d: Dashboard }) {
  const cov = d.label_coverage
  const chains = Object.entries(cov.by_chain).sort((a, b) => b[1] - a[1])
  const rest = chains.slice(CHAINS_SHOWN)
  return (
    <Panel
      title="Label coverage"
      more={{ to: '/labels', text: 'Open the labels explorer' }}
      note={`${count(cov.total)} labelled addresses. A trace can only name an exchange whose address is among them.`}
    >
      <BarList
        caption="Labels by tier"
                layer="network"
        labelWidth="12.5rem"
        rows={TIER_ORDER.filter((t) => cov.by_tier[t]).map((t) => ({
          key: t,
          label: <TierTag tier={t} size="sm" />,
          value: cov.by_tier[t],
          valueText: count(cov.by_tier[t]),
          to: `/labels?tier=${t}`,
        }))}
      />
      <div className="border-t border-rule pt-3">
        <BarList
          caption="Labels by chain"
                layer="network"
          labelWidth="12.5rem"
          rows={chains.slice(0, CHAINS_SHOWN).map(([chain, n]) => ({
            key: chain,
            label: chainName(chain),
            value: n,
            valueText: count(n),
            to: `/labels?chain=${encodeURIComponent(chain)}`,
          }))}
        />
        {rest.length > 0 && (
          <p className="px-1.5 pt-1 text-sm text-muted">
            and {plural(rest.length, 'more chain')} with {count(rest.reduce((s, [, n]) => s + n, 0))} labels between them
          </p>
        )}
      </div>
    </Panel>
  )
}

/** What is on file today. Every figure is a count of stored cases, requests and labels, and leads to the list behind it. */
export function DashboardPage() {
  const dash = useDashboard()
  const rupees = useRupees()

  if (dash.isError)
    return (
      <>
        <PageHeader title="Dashboard" />
        <ErrorState title="The dashboard could not be loaded" detail={dash.error instanceof ApiError ? dash.error.detail : 'Try again.'} onRetry={() => void dash.refetch()} />
      </>
    )

  const d = dash.data
  return (
    <>
      <PageHeader title="Dashboard">What is on file: counted from the stored cases and requests. Every figure opens the list behind it.</PageHeader>
      {!d ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton width="100%" height={84} />
          <Skeleton width="60%" />
          <Skeleton width="40%" />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <Ledger label="Counts" entries={ledger(d)} />
          <div className="grid items-start gap-4 lg:grid-cols-12">
            <div className="flex flex-col gap-4 lg:col-span-7">
              <Panel
                title="How the cases ended"
                more={{ to: '/cases', text: 'All cases' }}
                note={d.counts.failed ? `${plural(d.counts.failed, 'trace')} failed and ${d.counts.failed === 1 ? 'has' : 'have'} no outcome.` : undefined}
              >
                <ShareBar
                  caption="Finished cases by outcome"
                  unit={(n) => plural(n, 'case')}
                  parts={[
                    {
                      key: 'a',
                      name: 'An exchange is named',
                      value: d.outcomes.ATTRIBUTED ?? 0,
                      fill: 'named',
                      to: '/cases?outcome=ATTRIBUTED',
                    },
                    {
                      key: 'i',
                      name: 'Insufficient evidence: no exchange named',
                      value: d.outcomes.INSUFFICIENT_EVIDENCE ?? 0,
                      fill: 'open',
                      to: '/cases?outcome=INSUFFICIENT_EVIDENCE',
                    },
                    {
                      key: 's',
                      name: 'Sanctioned address or mixer reached',
                      value: d.outcomes.SANCTIONED_OR_MIXER_REACHED ?? 0,
                      fill: 'seal',
                      to: '/cases?outcome=SANCTIONED_OR_MIXER_REACHED',
                    },
                  ]}
                />
              </Panel>

              <Panel
                title="Exchanges the funds reached"
                more={{ to: '/desk', text: 'Request desk' }}
                note="Traced funds that reached each exchange at or above the naming bar, in US-dollar stablecoins. Other assets are not converted and add nothing here."
              >
                <BarList
                  caption="Exchanges by traced US dollars"
                layer="fusion"
                  rows={d.top_vasps.map((v) => ({
                    key: v.vasp,
                    label: <span className="font-medium">{v.vasp}</span>,
                    value: v.total_usd,
                    valueText: [formatUsd(v.total_usd), rupees(v.total_usd)].filter(Boolean).join(' · '),
                    note: plural(v.cases, 'case'),
                    to: `/vasps/${encodeURIComponent(v.vasp)}`,
                  }))}
                  empty="No finished case names an exchange yet."
                />
              </Panel>

              <div className="grid gap-4 sm:grid-cols-2">
                <Panel title="Cases by chain">
                  <BarList
                    caption="Cases by chain"
                layer="chain"
                    labelWidth="6.5rem"
                    rows={d.chain_mix.map((c) => ({
                      key: c.chain,
                      label: (
                        <span className="flex items-center gap-2">
                          <ChainBadge chain={c.chain} size="sm" />
                          <span className="sr-only">{CHAINS[c.chain].name}</span>
                        </span>
                      ),
                      value: c.cases,
                      valueText: count(c.cases),
                      to: `/cases?chain=${c.chain}`,
                    }))}
                  />
                </Panel>
                <Panel title="Time for the funds to reach the exchange">
                  {d.median_time_to_attribution_s != null ? (
                    <>
                      <p className="tabular font-mono text-2xl text-fg">{formatDuration(d.median_time_to_attribution_s)}</p>
                      <p className="text-sm text-muted">
                        Median over the {plural(d.attribution_times_n ?? 0, 'case')} that name an exchange: from the wallet's payment to its arrival at the exchange's address.
                        Chain time, not the time the trace took.
                        {d.median_time_to_attribution_s === 0 && ' "Same block" means the wallet paid the exchange\'s address directly.'}
                      </p>
                    </>
                  ) : (
                    <p className="text-base text-muted">Not yet measured: no finished case names an exchange.</p>
                  )}
                </Panel>
              </div>
            </div>

            <div className="flex flex-col gap-4 lg:col-span-5">
              <Panel title="Alerts" more={{ to: '/watchlist', text: 'Watchlist' }}>
                {d.recent_alerts.length > 0 ? (
                  <ul className="flex flex-col gap-2">
                    {d.recent_alerts.map((a, i) => (
                      <AlertRow key={`${a.wallet}:${a.at}:${i}`} alert={a} />
                    ))}
                  </ul>
                ) : (
                  <p className="text-base text-muted">
                    Nothing to act on. A case that reaches a sanctioned address or a mixer appears here, and so does a watched wallet that has moved since it was last checked.
                  </p>
                )}
              </Panel>
              <Coverage d={d} />
            </div>
          </div>
        </div>
      )}
    </>
  )
}
