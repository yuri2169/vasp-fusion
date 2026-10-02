import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '../api/client'
import type { CaseDetail, Tier } from '../api/models'
import { useCase } from '../api/queries'
import { AddressChip } from '../components/AddressChip'
import { buttonClass } from '../components/Button'
import { ChainBadge } from '../components/ChainBadge'
import { DualMeter } from '../components/DualMeter'
import { ErrorState } from '../components/ErrorState'
import { HopRail } from '../components/HopRail'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/Skeleton'
import { TierTag } from '../components/TierTag'
import { TypologyFlag } from '../components/TypologyFlag'

/** Owners of the labelled wallets in a case, by address, for the Hop Rail's chips. */
function labelsOf(c: CaseDetail): Record<string, { entity: string; tier: Tier }> {
  const out: Record<string, { entity: string; tier: Tier }> = {}
  for (const node of c.graph.nodes) if (node.label) out[node.id] = { entity: node.label.entity, tier: node.label.tier }
  return out
}

/** A case, in outline: the Hop Rail, the summary, the exchanges reached, the patterns.
 *  U1 builds only this much, so that the search bar lands somewhere real.
 *  U2 builds the case page proper (graph, "Why this exchange?", receipt, audit). */
export function CasePage() {
  const { id = '' } = useParams()
  const query = useCase(id)
  const c = query.data

  // The rail extends hop by hop only when the result arrived while the officer was watching.
  const [watchedTrace, setWatchedTrace] = useState(false)
  const tracing = c?.status === 'queued' || c?.status === 'running'
  if (tracing && !watchedTrace) setWatchedTrace(true)

  if (query.isError)
    return (
      <ErrorState
        title="This case could not be opened"
        detail={query.error instanceof ApiError ? query.error.detail : 'Try again.'}
        onRetry={() => void query.refetch()}
      />
    )
  if (!c)
    return (
      <div aria-busy="true" className="flex flex-col gap-6">
        <Skeleton width={320} height={32} />
        <Skeleton height={96} />
        <Skeleton lines={3} />
      </div>
    )

  const top = c.candidates.find((x) => x.vasp === c.top_vasp)
  const named = c.outcome === 'ATTRIBUTED' && c.top_vasp

  return (
    <>
      <PageHeader
        eyebrow={c.case_ref ? `Case ${c.case_ref}` : `Case ${c.id}`}
        title={
          <span className="flex flex-wrap items-center gap-3">
            <ChainBadge chain={c.chain} />
            <span className="break-all font-mono text-lg font-medium">{c.address}</span>
          </span>
        }
        actions={
          named && (
            <Link
              to={`/desk?vasp=${encodeURIComponent(c.top_vasp!)}&case=${encodeURIComponent(c.id)}`}
              className={buttonClass('primary')}
            >
              Draft request to {c.top_vasp}
            </Link>
          )
        }
      />

      {c.status === 'failed' ? (
        <ErrorState title="The trace failed" detail={c.error ?? 'No reason was recorded. Trace the wallet again.'} />
      ) : (
        <HopRail
          suspect={{ address: c.address, chain: c.chain }}
          hops={c.hop_rail}
          labels={labelsOf(c)}
          state={tracing ? 'tracing' : 'done'}
          animate={watchedTrace}
          stamp={{
            outcome: c.outcome ?? null,
            status: c.status,
            vasp: c.top_vasp,
            confidence: c.confidence,
            interval: top?.confidence_interval,
            whatWouldChange: c.what_would_change[0],
          }}
        />
      )}

      {c.narrative && (
        <section aria-labelledby="summary" className="mt-8 max-w-prose">
          <h2 id="summary" className="eyebrow mb-2">
            Summary
          </h2>
          <p className="break-words text-base text-fg">{c.narrative}</p>
        </section>
      )}

      {c.candidates.length > 0 && (
        <section aria-labelledby="reached" className="mt-8">
          <h2 id="reached" className="eyebrow mb-2">
            Exchanges reached
          </h2>
          <ul className="flex flex-col gap-3">
            {c.candidates.map((x) => (
              <li key={x.vasp + x.deposit_address} className="rounded-md border border-rule bg-surface p-4">
                <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
                  <span className="display text-lg">{x.vasp}</span>
                  <TierTag tier={x.label_tier} />
                  <AddressChip address={x.deposit_address} chain={c.chain} />
                </div>
                <DualMeter
                  proximityRank={x.proximity_rank}
                  hops={x.hops}
                  shareOfFunds={x.share_of_funds}
                  timeToReachS={x.time_to_reach_s}
                  confidence={x.confidence}
                  interval={x.confidence_interval}
                  className="max-w-[640px]"
                />
              </li>
            ))}
          </ul>
        </section>
      )}

      {c.typology_flags.length > 0 && (
        <section aria-labelledby="patterns" className="mt-8">
          <h2 id="patterns" className="eyebrow mb-2">
            Patterns in the traced funds
          </h2>
          <ul className="flex max-w-prose flex-col gap-2">
            {c.typology_flags.map((flag, i) => (
              <li key={flag.code + flag.wallet + i}>
                <TypologyFlag flag={flag} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}
