/** Plain-English names for the model's 77 features.
 *
 * The SHAP lists showed code names (`max_n_outputs`), which reads as a debug
 * dump to anyone who did not write the feature extractor. Wording follows
 * btcfusion/explain/narrative.py where a phrase exists there. The raw name stays
 * available as a tooltip. tests/test_feature_labels.py fails if a feature in
 * artifacts/v1/feature_names.json has no entry here.
 */

// btc = satoshis shown as BTC · s = seconds · d = days · pct = a 0-1 share
type Unit = 'btc' | 's' | 'd' | 'pct' | 'n';

export const FEATURE_LABELS: Record<string, [string, Unit]> = {
  announcements_per_tx: ['announcements per transaction', 'n'],
  betweenness_est: ['bridging position in the graph', 'n'],
  burstiness: ['burstiness of activity', 'n'],
  chain_linearity: ['chain-like payment path', 'n'],
  change_script_match_rate: ['change matches wallet script type', 'pct'],
  clustering_coef: ['counterparties pay each other', 'n'],
  core_number: ['depth in the graph core', 'n'],
  counterparty_hhi: ['value concentrated on few counterparties', 'n'],
  degree_in: ['distinct sources paying in', 'n'],
  degree_out: ['distinct destinations paid', 'n'],
  dormancy_ratio: ['longest dormancy vs typical gap', 'n'],
  ephemeral_linux_frac: ['Linux ephemeral source ports', 'pct'],
  ephemeral_windows_frac: ['Windows ephemeral source ports', 'pct'],
  fee_ratio_mean: ['fee as a share of value', 'n'],
  gap_max: ['longest gap between spends', 's'],
  gap_mean: ['mean gap between spends', 's'],
  gap_median: ['median gap between spends', 's'],
  gap_std: ['spread of gaps between spends', 's'],
  hosting_frac: ['announced from hosting providers', 'pct'],
  hour_entropy: ['activity spread across the day', 'n'],
  hourly_value_gini: ['value concentrated in few hours', 'n'],
  in_out_ratio: ['moves out vs takes in', 'n'],
  ip_churn_rate: ['announcing address changes', 'n'],
  lifespan_days: ['active lifespan', 'd'],
  listening_node_ratio: ['announced from a listening node', 'pct'],
  max_n_inputs: ['most inputs in one spend', 'n'],
  max_n_outputs: ['most outputs in one spend', 'n'],
  mean_fee_sat: ['mean fee (sat)', 'n'],
  mean_feerate_sat_vb: ['mean fee rate (sat/vB)', 'n'],
  mean_n_inputs: ['inputs per spend', 'n'],
  mean_n_outputs: ['outputs per spend', 'n'],
  mean_value_out: ['mean value sent', 'btc'],
  mobile_frac: ['announced from mobile networks', 'pct'],
  n_addresses: ['addresses in the cluster', 'n'],
  n_announcements: ['announcements observed', 'n'],
  n_asns: ['networks announced from', 'n'],
  n_counterparties_in: ['counterparties paying in', 'n'],
  n_counterparties_out: ['counterparties paid', 'n'],
  n_countries: ['countries announced from', 'n'],
  n_ips: ['announcing IP addresses', 'n'],
  n_peers_reached: ['peers reached by announcements', 'n'],
  n_src_ports: ['distinct source ports', 'n'],
  n_tx_observed: ['transactions seen on the network', 'n'],
  n_tx_sent: ['transactions sent', 'n'],
  nonstandard_dst_port_frac: ['non-standard Bitcoin ports', 'pct'],
  output_entropy_mean: ['evenness of output values', 'n'],
  output_entropy_min: ['least even output split', 'n'],
  output_uniformity_max: ['most repeated output value', 'n'],
  output_uniformity_mean: ['repeated output values', 'n'],
  pagerank: ['centrality in the payment graph', 'n'],
  peak_hour_tx: ['transactions in the busiest hour', 'n'],
  peak_hour_value_frac: ['value moved in the busiest hour', 'pct'],
  peel_ratio_mean: ['share peeled off per spend', 'n'],
  reach_1: ['actors reached in one hop', 'n'],
  reach_3: ['actors reached within three hops', 'n'],
  residential_frac: ['announced from residential networks', 'pct'],
  right_censored: ['still active at capture end', 'n'],
  round_number_frac: ['round-number amounts', 'pct'],
  script_diversity: ['output script types used', 'n'],
  script_uniformity: ['one output script type', 'n'],
  segwit_frac: ['SegWit outputs', 'pct'],
  shared_infra_frac: ['announced from shared infrastructure', 'pct'],
  span_fraction_of_capture: ['share of the capture active', 'pct'],
  std_value_out: ['spread of values sent', 'btc'],
  structuring_proximity: ['amounts just below round thresholds', 'n'],
  taproot_frac: ['Taproot outputs', 'pct'],
  tor_frac: ['announced from Tor exits', 'pct'],
  total_in: ['total received', 'btc'],
  total_out: ['total sent', 'btc'],
  two_output_frac: ['spends with exactly two outputs', 'pct'],
  tx_per_available_day: ['transactions per active day', 'n'],
  value_per_available_day: ['value sent per active day', 'btc'],
  vpn_frac: ['announced from commercial VPNs', 'pct'],
  wdegree_in: ['value-weighted inflow', 'btc'],
  wdegree_out: ['value-weighted outflow', 'btc'],
  weekend_ratio: ['weekend activity', 'n'],
  window_coverage: ['share of its window active', 'pct'],
};

function num(v: number): string {
  if (!Number.isFinite(v)) return '—';
  if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString('en-US');
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

function duration(s: number): string {
  if (s < 90) return `${num(s)} s`;
  if (s < 5400) return `${(s / 60).toFixed(1)} min`;
  if (s < 172800) return `${(s / 3600).toFixed(1)} h`;
  return `${(s / 86400).toFixed(1)} d`;
}

export function featureLabel(name: string): string {
  return FEATURE_LABELS[name]?.[0] ?? name.replace(/_/g, ' ');
}

export function featureValue(name: string, v: number | null | undefined): string {
  if (v == null) return '—';
  switch (FEATURE_LABELS[name]?.[1]) {
    case 'btc': return `${(v / 1e8).toFixed(4)} BTC`;
    case 's': return duration(v);
    case 'd': return `${v.toFixed(1)} d`;
    case 'pct': return `${Math.round(v * 100)}%`;
    default: return num(v);
  }
}
