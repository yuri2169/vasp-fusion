"""Self-contained case-file export.

The output artefact is not an alert - it is an investigative document that has to
survive being forwarded to someone who has never seen this tool: entity summary,
evidence chain with real transaction IDs, plain-English reasoning, attribution
with its confidence interval, and an explicit statement of what evidence would
raise or lower that confidence.

The provenance manifest is embedded rather than linked, so the file remains
checkable after it leaves the machine. That is the difference between an
intelligence product and a screenshot.

HTML, not PDF: WeasyPrint drags in system libraries that are a liability on an
air-gapped box, and every browser prints to PDF. Same artefact, one less
dependency to vendor.
"""
from __future__ import annotations

import html
import json
from datetime import datetime

CSS = """
:root{--ink:#0E1C27;--soft:#4A5B69;--rule:#C3CCD4;--paper:#fff;--fusion:#B8791C;
--network:#7B4B94;--chain:#2D6A9F;--ok:#2E7D5B;--wash:#F3F5F7}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
font:14px/1.6 "IBM Plex Sans",-apple-system,system-ui,sans-serif;padding:40px}
.wrap{max-width:900px;margin:0 auto}
h1{font-size:26px;letter-spacing:-.01em;margin:0 0 4px;text-transform:uppercase}
.eyebrow{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;
letter-spacing:.14em;text-transform:uppercase;color:var(--soft)}
h2{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;
letter-spacing:.14em;text-transform:uppercase;color:var(--fusion);
margin:32px 0 10px;border-bottom:1px solid var(--rule);padding-bottom:6px}
.assess{background:#FBF6ED;border:1px solid var(--fusion);padding:18px;font-size:15px}
.conf{font-size:44px;font-weight:700;line-height:1}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{text-align:left;padding:7px 10px;border-bottom:1px solid var(--rule);
vertical-align:top}
th{font-family:ui-monospace,monospace;font-size:10.5px;letter-spacing:.1em;
text-transform:uppercase;color:var(--soft)}
.cf{background:var(--wash);border:1px dashed var(--rule);padding:14px;margin-top:12px}
.cf .down{color:#A2453B}.cf .up{color:var(--ok)}
.bar{display:inline-block;height:9px;background:var(--fusion);vertical-align:middle}
.bar.neg{background:#5C6B78}
footer{margin-top:44px;border-top:1px solid var(--rule);padding-top:16px;
font-size:11px;color:var(--soft)}
pre{background:var(--wash);padding:12px;overflow-x:auto;font-size:11px;
border:1px solid var(--rule)}
@page{size:A4;margin:14mm}
.print-only{display:none}
@media print{body{padding:0}h2{break-after:avoid}tr,figure{break-inside:avoid}pre.manifest{display:none}.print-only{display:block;font-size:11px;color:var(--soft)}}
"""


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _btc(sats) -> str:
    return f"{(sats or 0) / 1e8:.4f}"


def render_case_html(data: dict, prov: dict) -> str:
    a = data["alert"]
    ev = data.get("evidence") or []
    attr = data.get("attribution") or []
    shap = (data.get("shap") or [])[:8]
    beh = data.get("behaviour")
    txs = (data.get("transactions") or [])[:15]
    conf = float(a.get("confidence") or 0)
    ivl = float(a.get("interval") or 0)

    parts: list[str] = [
        f"<!doctype html><meta charset='utf-8'><title>Case file {_e(a['entity'])}</title>",
        f"<style>{CSS}</style><div class='wrap'>",
        "<div class='eyebrow'>VASP-FUSION · Investigative case file · "
        "SIH 2026 PS 26146 · NTRO</div>",
        f"<h1>Case file — {_e(a['entity'])}</h1>",
        f"<div class='mono' style='color:var(--soft)'>run {_e(data.get('run_id'))} · "
        f"generated {datetime.utcnow().isoformat(timespec='seconds')}Z</div>",
        "<h2>Assessment</h2>",
        f"<div class='assess'>{_e(a.get('narrative'))}</div>",
        "<h2>Confidence</h2>",
        f"<div class='conf'>{conf:.2f}</div>",
        f"<div class='mono'>{max(0.0, conf - ivl):.2f}–{min(1.0, conf + ivl):.2f} · isotonic-calibrated · "
        f"supervised {float(a.get('supervised') or 0):.2f} · "
        f"novelty {float(a.get('novelty') or 0):.2f} · "
        f"evidence {float(a.get('evidence_strength') or 0):.2f}</div>",
    ]

    cfs = [c for cand in attr for c in (cand.get("counterfactuals") or [])][:4]
    if cfs:
        parts.append("<div class='cf'><strong>What would change this</strong><br>")
        for c in cfs:
            arrow = "↓" if c.get("direction") == "down" else "↑"
            parts.append(f"<span class='{_e(c.get('direction'))}'>{arrow} "
                         f"{_e(c.get('text'))}</span><br>")
        parts.append("</div>")

    parts.append("<h2>Entity summary</h2><table>")
    for k, v in (("Addresses in cluster", a.get("n_addresses")),
                 ("Transactions sent", a.get("n_tx")),
                 ("Value out", f"{_btc(a.get('total_out'))} BTC"),
                 ("Value in", f"{_btc(a.get('total_in'))} BTC"),
                 ("Distinct announcing IPs", a.get("n_ips")),
                 ("Matched typologies", (a.get("typologies") or "none").replace("|", ", ")),
                 ("Analyst verdict", a.get("verdict") or "not yet reviewed")):
        parts.append(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>")
    parts.append("</table>")

    case = data.get("case") or {}
    members = case.get("members") or []
    if len(members) > 1:
        parts.append(f"<h2>This operation: {_e(case.get('case_id'))} · "
                     f"{_e(case.get('n_linked'))} linked actor"
                     f"{'' if case.get('n_linked') == 1 else 's'}</h2>"
                     "<p>Actors connected by payments among the flagged set. One case is one "
                     "operation. Values count only money moved between members.</p>"
                     "<table><tr><th>Actor</th><th>Payments sent</th>"
                     "<th>BTC in</th><th>BTC out</th></tr>")
        for m in members:
            parts.append(f"<tr><td class='mono'>{_e(m['entity'])}</td><td>{_e(m['n_tx'])}</td>"
                         f"<td>{_btc(m['value_in'])}</td><td>{_btc(m['value_out'])}</td></tr>")
        parts.append("</table>")
        if case.get("n_linked", 0) + 1 > len(members):
            parts.append(f"<p>Showing the first {len(members)} of "
                         f"{_e(case['n_linked'] + 1)} members.</p>")

    if ev:
        parts.append("<h2>Evidence chain</h2>")
        for e in ev:
            parts.append(f"<p><strong>{_e(e['typology'].replace('_', ' '))}</strong> "
                         f"(strength {float(e['strength']):.2f})<br>{_e(e['summary'])}</p>")
            if e.get("detail"):
                parts.append("<table><tr>"
                             + "".join(f"<th>{_e(k)}</th>" for k in e["detail"][0])
                             + "</tr>")
                for d in e["detail"]:
                    parts.append("<tr>" + "".join(
                        f"<td class='mono'>{_e(v)}</td>" for v in d.values()) + "</tr>")
                parts.append("</table>")

    if attr:
        withheld = a.get("attribution_status") != "ok"
        parts.append("<h2>Network attribution</h2>"
                     + (f"<p><strong>No address is named</strong> ({_e(a.get('attribution_status'))}). "
                        "The candidates below are listed for the record only.</p>" if withheld else "")
                     + "<table>"
                     "<tr><th>IP</th><th>ASN</th><th>Type</th><th>Country</th>"
                     "<th>Obs</th><th>Roots</th><th>p</th><th>Confidence</th></tr>")
        for c in attr:
            parts.append(
                f"<tr><td class='mono'>{_e(c['ip'])}</td>"
                f"<td class='mono'>AS{_e(c['asn'])}</td><td>{_e(c['asn_type'])}</td>"
                f"<td>{_e(c['country'])}</td><td>{_e(c['n_observations'])}</td>"
                f"<td>{_e(c['root_hits'])}</td>"
                f"<td class='mono'>{float(c['p_value']):.2e}</td>"
                f"<td><strong>{float(c['confidence']):.2f}</strong> "
                f"{max(0.0, float(c['confidence']) - float(c['interval'])):.2f}–"
                f"{min(1.0, float(c['confidence']) + float(c['interval'])):.2f}</td></tr>")
        parts.append("</table>")
        parts.append("<p class='mono' style='color:var(--network)'>Diffusion-adjusted: "
                     "single observations are down-weighted and propagation-tree roots "
                     "are weighted above first-observation evidence.</p>")
    else:
        parts.append("<h2>Network attribution</h2><p>No attribution: "
                     f"{_e(a.get('attribution_status'))}.</p>")

    if beh:
        hist = beh.get("hour_histogram") or []
        mx = max(hist) if hist else 1
        parts.append("<h2>Activity by hour (UTC)</h2><div>")
        for h, v in enumerate(hist):
            w = int(24 * v / max(mx, 1))
            parts.append(f"<div class='mono'>{h:02d} "
                         f"<span class='bar' style='width:{w * 8}px'></span> {v}</div>")
        parts.append(f"</div><p class='mono'>Inferred operating offset "
                     f"UTC{int(beh['inferred_offset_min']) // 60:+03d}:"
                     f"{abs(int(beh['inferred_offset_min'])) % 60:02d} "
                     f"(fit {float(beh['offset_fit']):.2f}, "
                     f"diurnality {float(beh['diurnality']):.2f})</p>")

    if shap:
        parts.append("<h2>Model attributions (SHAP)</h2><table>"
                     "<tr><th>Feature</th><th>Effect</th><th>Meaning</th></tr>")
        for srow in shap:
            c = float(srow["contribution"])
            w = int(min(abs(c) * 400, 160))
            cls = "bar" if c > 0 else "bar neg"
            parts.append(
                f"<tr><td class='mono'>{_e(srow['feature'])}</td>"
                f"<td><span class='{cls}' style='width:{w}px'></span> "
                f"<span class='mono'>{c:+.3f}</span></td>"
                f"<td>{_e(srow.get('meaning') or '')}</td></tr>")
        parts.append("</table>")

    if txs:
        parts.append("<h2>Constituent transactions (top by contribution)</h2><table>"
                     "<tr><th>TXID</th><th>Time</th><th>Value</th><th>In/Out</th>"
                     "<th>Entropy</th><th>Score</th></tr>")
        for tx in txs:
            parts.append(
                f"<tr><td class='mono'>{_e(str(tx['txid'])[:20])}…</td>"
                f"<td class='mono'>{_e(tx['ts'])}</td>"
                f"<td>{_btc(tx['value_out'])}</td>"
                f"<td>{_e(tx['n_inputs'])}/{_e(tx['n_outputs'])}</td>"
                f"<td>{float(tx['output_entropy'] or 0):.2f}</td>"
                f"<td>{float(tx['tx_score'] or 0):.2f}</td></tr>")
        parts.append("</table>")

    # The key facts as a table, then the full manifest. Print keeps only the
    # table: the manifest carries the model's whole metrics block, which turned a
    # three-page case file into a 36-page PDF of JSON.
    pv = prov.get("provenance", {}) or {}
    mm = pv.get("model_manifest", {}) or {}
    rows = [("source file", pv.get("source_file")), ("source SHA-256", pv.get("source_sha256")),
            ("source bytes", pv.get("source_bytes")), ("seed", pv.get("seed")),
            ("feature version", pv.get("feature_version")),
            ("code", f"{pv.get('git_sha', '')}{' (uncommitted changes)' if pv.get('git_dirty') else ''}"),
            ("model", f"{mm.get('version', '')} · {mm.get('backend', '')} · trained {mm.get('trained_at', '')}")]
    parts.append("<h2>Provenance</h2><table>" + "".join(
        f"<tr><th>{_e(k)}</th><td class='mono'>{_e(v)}</td></tr>" for k, v in rows) + "</table>")
    parts.append("<pre class='manifest'>"
                 + _e(json.dumps(pv, indent=2)) + "</pre>"
                 "<p class='print-only'>The full provenance manifest is embedded in the HTML "
                 "export of this case file.</p>")
    parts.append(
        "<footer><strong>Reproduction.</strong> Every figure in this document derives "
        "from the pinned model artefacts and the input file whose SHA-256 is recorded "
        "above. <code>make reproduce</code> regenerates them from the fixed seed."
        "<br><br><strong>Limitations.</strong> Attribution confidence models Bitcoin "
        "Core's randomised diffusion, which deliberately frustrates first-relay origin "
        "inference. Single observations are weak evidence by construction. Where every "
        "candidate address is shared infrastructure, attribution is suppressed rather "
        "than reported."
        "</footer></div>")
    return "".join(parts)
