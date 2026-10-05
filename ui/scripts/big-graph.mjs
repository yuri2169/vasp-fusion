// A case of n wallets, for measuring the interface on a large graph (U5: "a 2,000-node graph
// stays smooth"). It is a SHAPE, not data: the ids are `w0001`…, nothing is labelled, no exchange
// is named, the outcome is "insufficient evidence". It is never written to mocks/ or shipped;
// only the bench test (src/lib/bigGraph.test.ts) and scripts/perf.mjs build one.
export function bigCase(n = 2000, hops = 5) {
  const id = (i) => `w${String(i).padStart(4, '0')}`
  let seed = 26182
  const rand = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff)
  const suspect = id(0)
  const nodes = [{ id: suspect, chain: 'tron', role: 'suspect', hop: 0, label: null, cluster: null, is_hub: false }]
  const edges = []
  const byHop = [[suspect]]
  const t0 = Date.UTC(2026, 8, 1)
  let k = 0
  const pay = (source, target, direction = 'outbound') => {
    k += 1
    const amount = Math.round((10 + rand() * 990) * 100) / 100
    edges.push({
      id: `e${k}`, source, target, direction, asset: 'USDT', amount, traced_amount: amount, amount_usd: amount,
      tx_hash: k.toString(16).padStart(64, '0'), block_time: new Date(t0 + k * 60_000).toISOString(),
    })
  }
  const funders = Math.min(40, Math.floor(n / 50))
  const outward = n - 1 - funders
  for (let i = 1; i <= outward; i++) {
    // Each hop is about twice as crowded as the one before it.
    const hop = Math.min(hops, 1 + Math.floor(Math.log2(1 + (i * (2 ** hops - 1)) / outward)))
    const address = id(i)
    const hub = rand() < 0.03
    nodes.push({ id: address, chain: 'tron', role: hub ? 'hub' : 'intermediary', hop, label: null, cluster: null, is_hub: hub })
    ;(byHop[hop] ??= []).push(address)
    const before = byHop[hop - 1] ?? byHop[0]
    pay(before[Math.floor(rand() * before.length)], address)
    if (rand() < 0.5) pay(before[Math.floor(rand() * before.length)], address) // about 1.5 transfers a wallet
  }
  for (let i = 0; i < funders; i++) {
    const address = id(outward + 1 + i)
    nodes.push({ id: address, chain: 'tron', role: 'unknown', hop: 1, label: null, cluster: null, is_hub: false })
    pay(address, suspect, 'inbound')
  }
  const first = edges.find((e) => e.source === suspect && e.direction === 'outbound')
  const total = edges.filter((e) => e.source === suspect && e.direction === 'outbound').reduce((sum, e) => sum + e.amount, 0)
  return {
    id: `perf-${n}`, address: suspect, chain: 'tron', status: 'done', outcome: 'INSUFFICIENT_EVIDENCE',
    top_vasp: null, confidence: null, case_ref: `Synthetic shape, ${n} wallets`, complaint_no: null,
    amount_lost_inr: null, created_at: new Date(t0).toISOString(), demo: true, error: null,
    asset: 'USDT', total_sent: total, total_received: 0,
    where_funds_went: [{ kind: 'not_followed', name: null, share: 1, amount: total }],
    hop_rail: [{ index: 1, from_address: first.source, to_address: first.target, tx_hash: first.tx_hash, asset: 'USDT',
                 amount: first.amount, amount_usd: first.amount, traced_amount: first.amount, block_time: first.block_time, elapsed_s: null }],
    graph: { nodes, edges }, candidates: [], typology_flags: [],
    narrative: 'A synthetic graph for measuring the interface. It is not a case.',
    abstain_reason: 'A synthetic graph for measuring the interface. It is not a case.',
    what_would_change: [], next_steps: [],
    provenance: {
      seed: 26182, code_version: 'synthetic', label_db_sha256: null, fetched_at: null, offline_replay: true, data_sources: [], notes: [],
      input: { address: suspect, chain: 'tron', max_hops: hops, since: null }, input_sha256: null, responses: [], responses_sha256: null,
      pages: 0, findings_sha256: null, content_sha256: null, model_version: null, model_sha256: null, git_commit: null, git_dirty: false,
    },
  }
}

// A fan: `payers` wallets that each paid the suspect wallet once, and `payees` it paid. Like
// bigCase it is a SHAPE for checking the layout ("a synthetic fan of 50 payers"), not data.
export function fanCase(payers = 50, payees = 3) {
  const c = bigCase(1 + payees, 1)
  const suspect = c.address
  const paid = new Set(c.graph.edges.filter((e) => e.direction === 'outbound').map((e) => e.target))
  const nodes = c.graph.nodes.filter((n) => n.id === suspect || paid.has(n.id))
  const edges = c.graph.edges.filter((e) => e.direction === 'outbound')
  const t0 = Date.UTC(2026, 7, 1)
  for (let i = 1; i <= payers; i++) {
    const id = `p${String(i).padStart(4, '0')}`
    const amount = 1000 - i * 7
    nodes.push({ id, chain: 'tron', role: 'unknown', hop: 1, label: null, cluster: null, is_hub: false })
    edges.push({
      id: `in${i}`, source: id, target: suspect, direction: 'inbound', asset: 'USDT', amount, traced_amount: amount, amount_usd: amount,
      tx_hash: (0xf000 + i).toString(16).padStart(64, '0'), block_time: new Date(t0 + i * 60_000).toISOString(),
    })
  }
  const received = edges.filter((e) => e.direction === 'inbound').reduce((sum, e) => sum + e.amount, 0)
  return { ...c, id: `fan-${payers}`, case_ref: `Synthetic shape, ${payers} payers`, total_received: received, graph: { nodes, edges } }
}
