import type { Chain, LetterWallet, RequestLetter } from '../api/models'
import { TIERS } from '../components/TierTag'
import { CHAINS } from '../lib/chains'
import { addressUrl, txUrl } from '../lib/explorers'
import { RupeeBasis, Rupees, usdOf } from '../components/Rupees'
import { formatAmount, formatConfidence, formatDate, formatUsd } from '../lib/format'
import { pageRule } from './pageRule'
import { ASK_ORDER, ASK_WORDS } from './status'
import './letter.css'

const isChain = (chain: string): chain is Chain => chain in CHAINS
const chainName = (chain: string) => (isChain(chain) ? CHAINS[chain].name : chain)

const amountOf = (w: LetterWallet) =>
  w.amount != null && w.asset ? formatAmount(w.amount, w.asset) : w.amount_usd != null ? formatUsd(w.amount_usd) : '-'

function Address({ address, chain }: { address: string; chain: string }) {
  return (
    <span className="sheet-mono">
      {isChain(chain) ? (
        <a href={addressUrl(chain, address)} target="_blank" rel="noreferrer">
          {address}
        </a>
      ) : (
        address
      )}
    </span>
  )
}

/** The request letter as it will be read: an A4 sheet drawn from the letter the server wrote
 *  (the same JSON its own PDF is drawn from). Nothing is reworded here. Addresses and hashes are whole.
 *  Until the request is approved the sheet carries the draft watermark, on screen and on every printed page. */
export function LetterSheet({ letter }: { letter: RequestLetter }) {
  const draft = letter.watermark
  const cases = letter.cases ?? []
  const citations = letter.legal_citations ?? []
  const notes = letter.review_notes ?? []

  return (
    <article className="sheet" aria-label={`Request ${letter.reference}`} data-draft={draft ? 'true' : 'false'}>
      <style>{pageRule(letter)}</style>
      {draft && (
        <>
          <div className="sheet-watermark" aria-hidden>
            {/* Drawn by CSS from the attribute: it is decoration, the banner says it in readable ink. */}
            <span data-text={draft} />
            <span data-text={draft} />
          </div>
          <div className="sheet-watermark-print" aria-hidden>
            {draft}
          </div>
          <p className="sheet-banner" data-testid="draft-banner">
            {draft}. Not sent.
          </p>
        </>
      )}

      <header className="sheet-head">
        <div>
          <p className="sheet-office">Office of the investigating officer</p>
          <p className="sheet-officer">{letter.officer}</p>
        </div>
        <p className="sheet-ref">
          Ref: <b>{letter.reference}</b>
          <br />
          Date: {formatDate(letter.date)}
        </p>
      </header>

      <p className="sheet-small">To</p>
      <p className="sheet-to">{letter.to}</p>
      {letter.channel && <p className="sheet-small">Through: {letter.channel}</p>}

      <p className="sheet-subject">Subject: {letter.subject}</p>

      <ol className="sheet-paragraphs">
        {letter.paragraphs.map((p, i) => (
          <li key={i}>
            <span>{p}</span>
          </li>
        ))}
      </ol>

      <p className="sheet-section">Requested</p>
      <ul className="sheet-asks">
        {ASK_ORDER.map((ask) => {
          const asked = letter.asks.includes(ask)
          return (
            <li key={ask} data-asked={asked}>
              <span className="sheet-box" aria-hidden>
                {asked ? '✕' : ''}
              </span>
              <span>
                {ASK_WORDS[ask]}
                <span className="sr-only">{asked ? ': requested' : ': not requested'}</span>
              </span>
            </li>
          )
        })}
      </ul>

      <p className="sheet-section">Wallets</p>
      <table className="sheet-table sheet-wallets">
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Wallet</th>
            <th scope="col">Amount traced</th>
            <th scope="col">Evidence tier</th>
            <th scope="col">Confidence</th>
            <th scope="col">Funds first arrived</th>
          </tr>
        </thead>
        <tbody>
          {letter.wallets.map((w, i) => (
            <tr key={`${w.case_id}:${w.address}`}>
              <td>{i + 1}</td>
              <td>
                <Address address={w.address} chain={w.chain} />
                <span className="sheet-small block">
                  {chainName(w.chain)}
                  {(w.case_ref ?? w.case_id) && ` · ${w.case_ref ?? w.case_id}`}
                </span>
                {w.paid_into && (
                  <>
                    <span className="sheet-small block">unlabelled; passed everything on to</span>
                    <Address address={w.paid_into} chain={w.chain} />
                  </>
                )}
                {w.label && <span className="sheet-small block">label: {w.label}</span>}
              </td>
              <td className="sheet-mono whitespace-nowrap">
                {amountOf(w)}
                <Rupees usd={w.amount_usd ?? (w.amount != null && w.asset ? usdOf(w.amount, w.asset) : null)} className="block" />
              </td>
              <td>{TIERS[w.tier].name}</td>
              <td className="sheet-mono">{w.confidence != null ? formatConfidence(w.confidence) : '-'}</td>
              <td className="whitespace-nowrap">
                {w.first_seen ? (
                  <>
                    {formatDate(w.first_seen)}
                    <br />
                    <span className="sheet-mono">{w.first_seen.slice(11, 19)} UTC</span>
                  </>
                ) : (
                  '-'
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="sheet-section">Transactions</p>
      {letter.wallets.map((w, i) => {
        const hashes = w.tx_hashes ?? []
        return (
          <div key={`${w.case_id}:${w.address}`}>
            <p className="sheet-small">
              Wallet {i + 1}: {hashes.length === 0 && 'none listed'}
            </p>
            <ul className="sheet-hashes">
              {hashes.map((hash) => (
                <li key={hash} className="sheet-mono">
                  {isChain(w.chain) ? (
                    <a href={txUrl(w.chain, hash)} target="_blank" rel="noreferrer">
                      {hash}
                    </a>
                  ) : (
                    hash
                  )}
                </li>
              ))}
            </ul>
          </div>
        )
      })}

      {cases.length > 0 && (
        <>
          <p className="sheet-section">Matters referred to</p>
          <table className="sheet-table">
            <thead>
              <tr>
                <th scope="col">Case reference</th>
                <th scope="col">Complaint no.</th>
                <th scope="col">Wallet under investigation</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.case_id}>
                  <td>{c.case_ref ?? c.case_id}</td>
                  <td className="sheet-mono">{c.complaint_no ?? '-'}</td>
                  <td>
                    <Address address={c.wallet} chain={c.chain} />
                    <span className="sheet-small block">{chainName(c.chain)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <div className="sheet-keep">
        <p className="sheet-section">Legal basis</p>
        <p>{letter.legal_basis}</p>
        {citations.length > 0 && (
          <ul className="sheet-citations">
            {citations.map((c) => (
              <li key={c.section + c.act} className="sheet-small">
                Section {c.section}, {c.act}: {c.heading}. <span className="[overflow-wrap:anywhere]">{c.url}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="sheet-sign">
        <div className="sheet-seal">Seal of office</div>
        <div className="sheet-signature">
          <div className="sheet-signature-line" />
          <p className="sheet-to">{letter.officer}</p>
          <p className="sheet-small">{draft ? 'Investigating officer (unsigned draft)' : 'Investigating officer'}</p>
        </div>
      </div>

      <p className="sheet-foot">
        {letter.reference} | generated by VASP-FUSION from public blockchain records
        <RupeeBasis className="block" />
      </p>

      {draft && notes.length > 0 && (
        <section className="sheet-review">
          <p className="sheet-section">For the reviewing officer. Not part of the request.</p>
          <ul>
            {notes.map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
        </section>
      )}
    </article>
  )
}
