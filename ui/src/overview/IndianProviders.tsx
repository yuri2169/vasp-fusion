import { Link } from 'react-router'
import type { IndianCoverage, IndianProvider, Tier } from '../api/models'
import { TierTag } from '../components/TierTag'
import { formatDate } from '../lib/format'
import { Panel } from './parts'
import { chainName, count, plural } from './words'

const CHAINS_SHOWN = 4

function Chains({ p }: { p: IndianProvider }) {
  const chains = Object.entries(p.by_chain ?? {})
  if (chains.length === 0) return <span className="text-muted">None</span>
  const rest = chains.slice(CHAINS_SHOWN)
  return (
    <>
      {chains
        .slice(0, CHAINS_SHOWN)
        .map(([c, n]) => `${chainName(c)} ${count(n)}`)
        .join(', ')}
      {rest.length > 0 && <span className="text-muted">, and {plural(rest.length, 'more chain')}</span>}
    </>
  )
}

/** Why a provider that holds labels still cannot be named, in the row's own figures. */
function verdict(p: IndianProvider): string {
  if (p.can_name) return 'Yes'
  if (p.labels > 0) return 'No: its labels are on chains the tool does not trace'
  if ((p.other_labels ?? 0) > 0) return 'No: the address held is not filed as an exchange wallet'
  return 'No: no labelled address'
}

/** Providers registered with FIU-IND against the label store. A trace names an exchange only by
 *  reaching one of its labelled wallets, so the providers with none are listed as plainly as the rest. */
export function IndianProviders({ india }: { india: IndianCoverage }) {
  const held = india.providers.filter((p) => p.labels > 0 || (p.other_labels ?? 0) > 0)
  const none = india.providers.filter((p) => !held.includes(p))
  return (
    <Panel
      title="Indian exchanges the tool can name"
      className="lg:col-span-12"
      note={`The ${india.listed} virtual-asset service providers registered with FIU-IND as of ${formatDate(india.source.published)}, from the one official list. A trace names an exchange only when it reaches a labelled wallet of that exchange.`}
    >
      <p className="px-1.5 text-base text-fg">
        <strong className="font-semibold">
          {india.can_name} of {india.listed}
        </strong>{' '}
        can be named today. {plural(india.in_recorded_cases, 'provider')} on the list {india.in_recorded_cases === 1 ? 'is' : 'are'} named by a recorded case.
      </p>
      <div className="overflow-auto rounded border border-rule">
        <table className="w-full border-collapse text-base">
          <caption className="sr-only">Registered providers with a labelled address</caption>
          <thead>
            <tr className="bg-sunk">
              {['Registered entity', 'Exchange labels', 'Chains', 'Best tier', 'Recorded cases', 'Can it be named?'].map((h, i) => (
                <th key={h} scope="col" className={`eyebrow px-3 py-2 ${i === 1 ? 'text-right' : 'text-left'}`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {held.map((p) => {
              const tier = Object.keys(p.by_tier ?? {})[0] as Tier | undefined
              return (
                <tr key={p.n} className="border-t border-rule align-top">
                  <th scope="row" className="px-3 py-2 text-left font-normal">
                    <span className="text-fg">{p.trade_name ?? p.legal_name}</span>
                    {p.trade_name && <span className="block text-sm text-muted">{p.legal_name}</span>}
                  </th>
                  <td className="tabular px-3 py-2 text-right font-mono text-fg">{count(p.labels)}</td>
                  <td className="px-3 py-2 text-fg">
                    <Chains p={p} />
                  </td>
                  <td className="px-3 py-2">{tier ? <TierTag tier={tier} size="sm" /> : <span className="text-muted">None</span>}</td>
                  <td className="px-3 py-2 text-fg">
                    {(p.recorded_cases ?? []).length > 0 ? plural((p.recorded_cases ?? []).length, 'case') : <span className="text-muted">None</span>}
                  </td>
                  <td className={`px-3 py-2 ${p.can_name ? 'text-fg' : 'text-muted'}`}>{verdict(p)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {none.length > 0 && (
        <p className="px-1.5 text-base text-fg" aria-label="Registered providers with no labelled address">
          <strong className="font-semibold">No labelled address is held for the other {none.length}</strong>, so a trace can pass through their wallets
          and not know it: <span className="text-muted">{none.map((p) => p.trade_name ?? p.legal_name).join(', ')}.</span>
        </p>
      )}
      <p className="px-1.5 text-sm text-muted">
        Source:{' '}
        <a href={india.source.url} target="_blank" rel="noopener noreferrer" className="underline decoration-rule-strong underline-offset-2 hover:decoration-current">
          {india.source.title}
        </a>{' '}
        ({india.source.publisher}; read {formatDate(india.source.accessed)}). FIU-IND publishes no register of its own, so a registration is a claim
        about that date only. The list does not say which providers are exchanges.{' '}
        <Link to="/labels?category=exchange" className="underline decoration-rule-strong underline-offset-2 hover:decoration-current">
          See every exchange label
        </Link>
        .
      </p>
    </Panel>
  )
}
