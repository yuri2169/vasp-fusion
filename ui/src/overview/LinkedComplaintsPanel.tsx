import { useLinkedComplaints } from '../api/queries'
import { Panel } from './parts'
import { SharedWallets } from './LinkedComplaints'

/** The dashboard's view of complaints that may be one operation, from the stored traces. */
export function LinkedComplaintsPanel() {
  const q = useLinkedComplaints()
  if (!q.data) return null
  const { links, cases_read, limit } = q.data
  return (
    <Panel title="Linked complaints" className="lg:col-span-12" note={limit}>
      {links.length === 0 ? (
        <p className="text-base text-muted">
          None of the {cases_read} finished cases shares a wallet with another, outside exchanges, bridges, mixers and other labelled services.
        </p>
      ) : (
        <>
          <p className="text-base text-ink">
            {links.length} wallet{links.length === 1 ? '' : 's'} reached by the traces of more than one suspect wallet, across {cases_read} finished cases.
          </p>
          <SharedWallets links={links} />
        </>
      )}
    </Panel>
  )
}
