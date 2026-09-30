/** Typed client for the FastAPI surface. One file, no data-fetching library:
 *  every screen loads once and the only polling is the run-progress job. */

export type Alert = {
  run_id: string; rank: number; entity: string; level: string;
  score: number; confidence: number; interval: number;
  // Calibrated probability range (Venn-Abers); null for artefacts trained before it existed.
  confidence_low?: number | null; confidence_high?: number | null;
  // Before the prior-shift correction; the gate compares this, the screen shows `confidence`.
  confidence_unadjusted?: number | null;
  novelty: number; supervised: number; evidence_strength: number;
  typologies: string; narrative: string;
  n_addresses: number; n_tx: number; total_out: number; total_in: number;
  n_ips: number; top_asn: number; top_asn_type: string; top_country: string;
  attribution_confidence: number; attribution_status: string;
  verdict: string | null; verdict_reason: string | null;
  // Campaign links. Already stored and already served; the queue simply never
  // read them, so a lead that belongs to a 35-entity operation looked identical
  // to one acting alone.
  n_linked_entities?: number; linked_entities?: string;
  raised_by?: string;
  // 'CASE-007': one queue row is one operation (its linked actors ride along).
  case_id?: string;
};

export type Evidence = {
  entity: string; typology: string; strength: number; summary: string;
  txids: string[]; detail: Record<string, unknown>[];
};

export type Counterfactual = { direction: 'up' | 'down'; value: number; text: string };

export type Attribution = {
  entity: string; rank: number; ip: string; asn: number; asn_org: string;
  asn_type: string; country: string; n_observations: number;
  n_entities_on_ip: number; p_value: number; ppmi: number;
  root_hits: number; root_fraction: number; infra_penalty: number;
  timezone_agreement: number; confidence: number; interval: number;
  summary: string; counterfactuals: Counterfactual[]; status: string;
};

export type ShapRow = {
  entity: string; feature: string; contribution: number;
  value: number; direction: string; meaning: string | null;
};

export type Behaviour = {
  entity: string; hour_histogram: number[]; inferred_offset_min: number;
  offset_fit: number; diurnality: number;
};

export type TxRow = {
  entity: string; txid: string; ts: string; value_out: number; fee: number;
  n_inputs: number; n_outputs: number; output_entropy: number;
  peel_ratio: number | null; tx_score: number;
};

export type CaseFile = {
  run_id: string; alert: Alert; evidence: Evidence[]; attribution: Attribution[];
  shap: ShapRow[]; behaviour: Behaviour | null; transactions: TxRow[];
  case?: {
    case_id: string; n_linked: number; full_graph: boolean;
    members: { entity: string; n_tx: number; value_in: number; value_out: number }[];
  };
};

export const CASE_TIP = 'Actors connected by payments among the flagged set. One case is one operation.';

export type Receipt = {
  file: string; format: string; rows_read: number; rows_clean: number;
  rows_quarantined: number; duplicates_removed: number;
  quarantine_breakdown: Record<string, number>;
  unmapped_input_columns: string[]; chain_only_mode: boolean;
  n_entities_resolved: number; n_entities_active: number;
  n_transactions: number; n_graph_edges: number;
  duration_s: number; rows_per_second: number; n_alerts: number;
  threshold: number; n_below_threshold: number; degraded_no_model: boolean;
  enrichment: Record<string, unknown>; attribution: Record<string, unknown>;
  embeddings: Record<string, unknown>; timings: Record<string, number>;
  resolve_n_entities?: number; resolve_change_edges?: number;
  resolve_cospend_edges?: number;
};

export type Run = {
  run_id: string; created_at: string; source_file: string;
  n_rows: number; n_entities: number; n_alerts: number; duration_s: number;
  receipt: Receipt; timings: Record<string, number>;
  provenance: Record<string, unknown>; metrics: Record<string, unknown>;
};

export type WatchlistHit = {
  entity: string; seed: string; direction: 'seed' | 'downstream' | 'upstream';
  parent: string | null; hops: number; risk: number; is_hub: boolean;
  seed_label: string | null; path: string[]; in_queue: boolean;
  rank: number | null; confidence: number | null;
};
export type WatchlistHits = {
  run_id: string; available: boolean; note?: string;
  seeds: { address: string; label: string; entity: string | null }[];
  hits: WatchlistHit[]; n_seeds_in_capture: number; n_reached?: number;
};

/** Where leads announce from (GET /api/geo). A lead's `country` is the country of
 *  its top-ranked announcing IP (ranked by attribution confidence, not by count);
 *  `countries` adds every other country its candidate IPs sit in. For VPN and Tor
 *  exits the country is the exit's. */
export type GeoLead = {
  entity: string; rank: number; country: string; asn_type: string; status: string;
  confidence: number; first_ts: number | null; countries: string[];
};
export type GeoCountry = {
  country: string; n_leads: number; n_via_exit: number; n_via_hosting: number;
  n_via_own_line: number; n_named: number;
};
export type GeoData = {
  run_id: string | null; n_leads: number; n_located: number;
  countries: GeoCountry[]; leads: GeoLead[];
};

export type Job = {
  job_id: string; state: 'running' | 'done' | 'error'; stage?: string;
  file: string; run_id?: string; receipt?: Receipt; error?: string;
};

export type GraphData = {
  nodes: { id: string; subject: boolean; alerted: boolean; score: number }[];
  edges: { src: string; dst: string; value: number; n_tx: number;
           first_ts?: number | null; last_ts?: number | null }[];
  meta: { nodes_shown: number; hops: number; capped?: boolean;
          score_lo: number; score_hi: number };
};

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${url}`);
  return r.json() as Promise<T>;
}

/** The analyst's name, stored per browser and sent with every write so each
 *  verdict records who made it. URL-encoded: a header must be Latin-1. */
export const ANALYST_KEY = 'btcfusion.analyst';
export function analystName(): string {
  try { return localStorage.getItem(ANALYST_KEY) || ''; } catch { return ''; }
}
function writeHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const a = analystName();
  return a ? { ...extra, 'X-Analyst': encodeURIComponent(a) } : extra;
}

async function post<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method: 'POST',
    headers: writeHeaders({ 'Content-Type': 'application/json' }),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${url}`);
  return r.json() as Promise<T>;
}

export const api = {
  health: () => get<{ status: string; model_artifacts: boolean; backend: string | null; threshold: number }>('/api/health'),
  latestRun: () => get<{ run: Run | null }>('/api/runs/latest'),
  runs: () => get<{ runs: Run[] }>('/api/runs'),
  samples: () => get<{ samples: { name: string; path: string; mb: number }[] }>('/api/samples'),
  startRun: (path?: string) => post<{ job_id: string }>('/api/runs', { path }),
  job: (id: string) => get<Job>(`/api/jobs/${id}`),

  alerts: (q: Record<string, string | number | boolean | undefined>) => {
    const p = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => {
      if (v !== undefined && v !== '' && v !== false) p.set(k, String(v));
    });
    return get<{ run_id: string; alerts: Alert[]; sweep: { bucket: number; n: number }[] }>(
      `/api/alerts?${p}`);
  },
  caseFile: (entity: string) => get<CaseFile>(`/api/alerts/${encodeURIComponent(entity)}`),
  graph: (entity: string, hops = 2) =>
    get<GraphData>(`/api/graph/${encodeURIComponent(entity)}?hops=${hops}`),
  verdict: (entity: string, verdict: string, reason = '') =>
    post<{ ok: boolean }>(`/api/alerts/${encodeURIComponent(entity)}/verdict`,
      { verdict, reason }),
  transactions: (minScore = 0, limit = 200) =>
    get<{ run_id: string; transactions: TxRow[] }>(
      `/api/transactions?min_score=${minScore}&limit=${limit}`),
  expand: (entity: string) => get<{
    entity: string; addresses: { address: string }[];
    transactions: { txid: string; ts: string; value: number }[];
    truncated: boolean; n_addresses_total: number;
  }>(`/api/graph/${encodeURIComponent(entity)}/expand`),
  model: () => get<{ available: boolean; manifest?: any; leak_test?: any;
                     sensitivity?: any; external?: any; elliptic_pp?: any;
                     note?: string }>('/api/model'),
  provenance: () => get<any>('/api/provenance'),

  upload: async (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch('/api/upload', { method: 'POST', body: fd, headers: writeHeaders() });
    if (!r.ok) throw new Error(`upload failed: ${r.status}`);
    return r.json() as Promise<{ job_id: string; file: string; bytes: number }>;
  },
  exportUrl: (entity: string) => `/api/alerts/${encodeURIComponent(entity)}/export`,
  graphExportUrl: (entity: string, format: 'graphml' | 'csv', hops = 2) =>
    `/api/graph/${encodeURIComponent(entity)}/export?format=${format}&hops=${hops}`,

  watchlist: () => get<{ watchlist: { address: string; label: string; source: string }[] }>(
    '/api/watchlist'),
  uploadWatchlist: async (file: File, label: string) => {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch(`/api/watchlist?label=${encodeURIComponent(label)}`,
                          { method: 'POST', body: fd, headers: writeHeaders() });
    if (!r.ok) throw new Error(`watchlist upload failed: ${r.status}`);
    return r.json() as Promise<{ added: number; rejected: number }>;
  },
  clearWatchlist: async () => {
    const r = await fetch('/api/watchlist', { method: 'DELETE', headers: writeHeaders() });
    if (!r.ok) throw new Error(`could not clear the watchlist: ${r.status}`);
  },
  watchlistHits: (hops = 3) => get<WatchlistHits>(`/api/watchlist/hits?hops=${hops}`),
  geo: () => get<GeoData>('/api/geo'),
};

/** entity -> its nearest watchlist hit, for the queue and case file badges. */
export function nearWatchlist(h: WatchlistHits | null): Map<string, WatchlistHit> {
  return new Map((h?.hits ?? []).map((x) => [x.entity, x]));
}

/** "2 hops downstream of LockBit" - one phrase, used everywhere it appears. */
export function watchlistPhrase(x: WatchlistHit): string {
  const who = x.seed_label || 'a watchlisted wallet';
  if (x.hops === 0) return `on the watchlist (${who})`;
  return `${x.hops} hop${x.hops > 1 ? 's' : ''} ${x.direction} of ${who}`;
}

/** Print a server page to PDF through the browser's own dialog - offline, no
 *  PDF library. The page loads in an invisible frame, so the app stays put. */
export function printUrl(url: string) {
  const f = document.createElement('iframe');
  f.style.cssText = 'position:fixed;width:0;height:0;border:0';
  f.src = url;
  f.onload = () => {
    f.contentWindow?.focus();
    f.contentWindow?.print();
    setTimeout(() => f.remove(), 60_000);
  };
  document.body.appendChild(f);
}

// ---------------------------------------------------------------- formatting
const REGION = (() => {
  try { return new Intl.DisplayNames(['en'], { type: 'region' }); } catch { return null; }
})();

export const fmt = {
  int: (n: number | null | undefined) => (n ?? 0).toLocaleString('en-US'),
  btc: (sats: number | null | undefined) => ((sats ?? 0) / 1e8).toFixed(4),
  pct: (n: number) => `${(n * 100).toFixed(0)}%`,
  conf: (n: number | null | undefined) => (n ?? 0).toFixed(2),
  /** p ± h as a range clipped to 0-1: '0.97 ± 0.33' used to promise 1.30. */
  range: (p: number | null | undefined, h: number | null | undefined) =>
    `${Math.max(0, (p ?? 0) - (h ?? 0)).toFixed(2)}–${Math.min(1, (p ?? 0) + (h ?? 0)).toFixed(2)}`,
  /** 'NL' -> 'Netherlands', from the browser's own locale data (offline). */
  country: (code: string | null | undefined) => {
    if (!code) return '—';
    try { return REGION?.of(code) ?? code; } catch { return code; }
  },
  /** Typology slugs are snake_case in the store; analysts read prose. */
  typology: (t: string) => t.replace(/_/g, ' '),
  offset: (min: number) => {
    const s = min < 0 ? '-' : '+';
    const m = Math.abs(min);
    return `UTC${s}${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
  },
  time: (iso: string) => (iso || '').replace('T', ' ').replace(/\.\d+/, '').replace('Z', ''),
  bytes: (b: number) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${(b / 1e3).toFixed(0)} KB`),
};
