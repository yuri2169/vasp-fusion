"""Why the model said what it said, in an officer's words, and the model's two plots.

SHAP values are exact for tree ensembles (shap.TreeExplainer). A reason is one
feature of one address: what the address did, in plain words, and how far that
moved the model's score (signed, in log-odds). All of an address's reasons plus
the model's base value add up to its raw score.

The plots are hand-built SVG: no plotting dependency, the same bytes on every
run, and they follow light or dark mode on their own.
"""
from __future__ import annotations

from html import escape

import numpy as np
import polars as pl

from ..explain import fmt
from .train import Fitted, matrix

FEATURE_NAMES = {
    "forward_ratio": "Share forwarded to one wallet",
    "top_recipient_share": "Outgoing transfers to one wallet",
    "dwell_median_s": "Time funds wait before moving on",
    "left_share": "Share of funds still held",
    "n_senders": "Number of senders",
    "n_recipients": "Number of recipients",
    "n_in": "Incoming transfers",
    "n_out": "Outgoing transfers",
    "out_per_in": "Outgoing per incoming transfer",
    "sweep_gap_cv": "Regularity of outgoing transfers",
    "stable_share": "Share of stablecoin transfers",
    "gas_outside_share": "Network fee covered by someone else",
    "gas_payers": "Number of outside fee payers",
    "age_days": "Time span of activity",
    "to_exchange_share": "Sends straight to a labelled exchange wallet",
    "gas_from_exchange_share": "Fee covered by a labelled exchange wallet",
}


def _n(value, one: str, many: str | None = None) -> str:
    n = int(round(value))
    return f"{n} {one if n == 1 else many or one + 's'}"


def phrase(feature: str, value) -> str:
    """What the address did, for one feature. Never a column name, never a bare number."""
    v = float("nan") if value is None else float(value)
    missing = v != v
    if feature == "forward_ratio":
        return ("no deposit was seen before an outgoing transfer, so how much it forwards is "
                "unknown" if missing
                else f"forwards {fmt.pct(v)} of what it receives to one wallet")
    if feature == "top_recipient_share":
        if missing:
            return "it sent nothing in the listing"
        return ("every outgoing transfer goes to one wallet" if v >= 1
                else f"{fmt.pct(v)} of its outgoing transfers go to one wallet")
    if feature == "dwell_median_s":
        return ("no deposit was seen moving on, so the waiting time is unknown" if missing
                else f"moves funds on about {fmt.duration(v)} after they arrive")
    if feature == "left_share":
        if missing:
            return "it received nothing in the listing"
        return ("keeps nothing of what it receives" if v <= 0
                else f"still holds {fmt.pct(v)} of what it received")
    if feature == "n_senders":
        return "receives from no one in the listing" if missing or v < 1 else \
            f"receives from {_n(v, 'sender')}"
    if feature == "n_recipients":
        return "pays out to no one in the listing" if missing or v < 1 else \
            f"pays out to {_n(v, 'wallet')}"
    if feature == "n_in":
        return _n(0 if missing else v, "incoming transfer")
    if feature == "n_out":
        return _n(0 if missing else v, "outgoing transfer")
    if feature == "out_per_in":
        return ("it has outgoing transfers but no incoming ones" if missing
                else f"{v:.1f} outgoing transfers for each incoming one")
    if feature == "sweep_gap_cv":
        if missing:
            return "too few outgoing transfers to tell whether they come at regular intervals"
        return f"its outgoing transfers come at {'regular' if v < 0.5 else 'irregular'} intervals"
    if feature == "stable_share":
        return f"{fmt.pct(0 if missing else v)} of its transfers are stablecoins"
    if feature == "gas_outside_share":
        if missing:
            return "it sent nothing, so nobody had to pay a network fee"
        return ("pays its own network fees" if v <= 0 else
                f"someone else covered the network fee for {fmt.pct(v)} of its outgoing transfers")
    if feature == "gas_payers":
        return "no outside wallet covered its fees" if missing or v < 1 else \
            f"{_n(v, 'outside wallet')} covered its fees"
    if feature == "age_days":
        return f"its transfers in the listing span {fmt.duration((0 if missing else v) * 86400)}"
    if feature == "to_exchange_share":
        return (f"{fmt.pct(0 if missing else v)} of its outgoing transfers go straight to a "
                "labelled exchange wallet")
    if feature == "gas_from_exchange_share":
        return (f"a labelled exchange wallet covered the fee for {fmt.pct(0 if missing else v)} "
                "of its outgoing transfers")
    raise KeyError(feature)


def base_value(model: Fitted) -> float:
    """The model's score before any feature is read (log-odds)."""
    if model.detector._explainer is None:
        model.detector.shap_values(np.zeros((1, len(model.features))))
    return float(np.atleast_1d(model.detector._explainer.expected_value)[-1])


def reasons(model: Fitted, df: pl.DataFrame, top: int = 3) -> list[list[dict]]:
    """Per row of `df`: its `top` features by |SHAP|, strongest first."""
    X = matrix(df, model.features)
    sv = model.detector.shap_values(X)
    out = []
    for values, shap_row in zip(X, sv):
        order = np.argsort(-np.abs(shap_row), kind="stable")[:top]
        out.append([{"feature": model.features[i],
                     "text": phrase(model.features[i], values[i]),
                     "weight": round(float(shap_row[i]), 4)} for i in order])
    return out


def reasons_sentence(row: list[dict]) -> str:
    said = []
    for word, keep in (("For", lambda w: w > 0), ("Against", lambda w: w < 0)):
        texts = [r["text"] for r in row if keep(r["weight"])]
        if texts:
            said.append(f"{word}: {'; '.join(texts)}.")
    return " ".join(said)


# ------------------------------------------------------------------ plots
_STYLE = """<style>
.viz{--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;
--axis:#c3c2b7;--series:#2a78d6;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
@media (prefers-color-scheme: dark){.viz{--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;
--grid:#2c2c2a;--axis:#383835;--series:#3987e5}}
.bg{fill:var(--surface)}.t{fill:var(--ink);font-size:15px;font-weight:600}
.s{fill:var(--ink2);font-size:12px}.m{fill:var(--muted);font-size:11px}
.v{fill:var(--ink);font-size:12px;font-variant-numeric:tabular-nums}
.g{stroke:var(--grid);stroke-width:1}.a{stroke:var(--axis);stroke-width:1}
.d{stroke:var(--axis);stroke-width:1.5;stroke-dasharray:4 4;fill:none}
.l{stroke:var(--series);stroke-width:2;fill:none;stroke-linejoin:round}
.p{fill:var(--series);stroke:var(--surface);stroke-width:2}.b{fill:var(--series)}
</style>"""


def _open(width: int, height: int, label: str) -> list[str]:
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}" class="viz" role="img" '
            f'aria-label="{escape(label, quote=True)}">', _STYLE,
            f'<rect class="bg" width="{width}" height="{height}"/>']


def _bar_up(x: float, base: float, w: float, h: float) -> str:
    """A bar standing on `base` with its top corners rounded (4px, less if it is short)."""
    r = min(4.0, h, w / 2)
    return (f'M{x:.1f},{base:.1f} v{-(h - r):.1f} q0,{-r:.1f} {r:.1f},{-r:.1f} '
            f'h{w - 2 * r:.1f} q{r:.1f},0 {r:.1f},{r:.1f} v{h - r:.1f} z')


def reliability_svg(bins: list[dict], title: str, ece: float | None,
                    brier: float | None) -> str:
    """Predicted probability against the observed share of deposit addresses, per bin,
    with the number of addresses in each bin underneath."""
    W, H, x0, y0, w, h = 640, 452, 64, 76, 536, 240
    base, strip = y0 + h + 104, 56

    def px(v: float) -> float:
        return x0 + v * w

    def py(v: float) -> float:
        return y0 + (1 - v) * h

    figures = " · ".join(f"{name} {value:.3f}" for name, value in (("ECE", ece),
                                                                    ("Brier", brier))
                         if value is not None)
    out = _open(W, H, f"Reliability of the deposit-address model: {title}")
    out += [f'<text class="t" x="{x0}" y="28">How well the probabilities hold: '
            f'{escape(title)}</text>',
            f'<text class="s" x="{x0}" y="48">Share that really were deposit addresses, by '
            f'predicted probability{" · " + figures if figures else ""}</text>']
    for tick in (0, 0.25, 0.5, 0.75, 1):
        out.append(f'<line class="{"a" if tick == 0 else "g"}" x1="{x0}" x2="{x0 + w}" '
                   f'y1="{py(tick):.1f}" y2="{py(tick):.1f}"/>')
        out.append(f'<text class="m" x="{x0 - 8}" y="{py(tick) + 4:.1f}" '
                   f'text-anchor="end">{tick:.0%}</text>')
        out.append(f'<text class="m" x="{px(tick):.1f}" y="{y0 + h + 18}" '
                   f'text-anchor="middle">{tick:.0%}</text>')
    out += [f'<text class="m" x="{x0 + w}" y="{y0 + h + 36}" text-anchor="end">predicted '
            'probability</text>',
            f'<text class="m" x="{x0}" y="{y0 - 10}">observed share</text>',
            f'<line class="d" x1="{px(0):.1f}" y1="{py(0):.1f}" x2="{px(1):.1f}" '
            f'y2="{py(1):.1f}"/>',
            f'<text class="m" x="{px(0.72):.1f}" y="{py(0.8):.1f}" text-anchor="end">'
            'perfect calibration</text>']
    pts = [(px(b["predicted"]), py(b["observed"])) for b in bins]
    if len(pts) > 1:
        out.append('<polyline class="l" points="'
                   + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + '"/>')
    for b, (x, y) in zip(bins, pts):
        out.append(f'<circle class="p" cx="{x:.1f}" cy="{y:.1f}" r="5"><title>Predicted '
                   f'{b["predicted"]:.0%}, observed {b["observed"]:.0%}, '
                   f'{b["count"]:,} addresses</title></circle>')
    most = max((b["count"] for b in bins), default=1) or 1
    bar_w = w / 10 - 2
    out.append(f'<text class="m" x="{x0}" y="{base - strip - 8}">addresses per bin</text>')
    out.append(f'<line class="a" x1="{x0}" x2="{x0 + w}" y1="{base}" y2="{base}"/>')
    for b in bins:
        height = max(1.0, strip * b["count"] / most)
        left = px(b["bin_mid"]) - bar_w / 2
        out.append(f'<path class="b" d="{_bar_up(left, base, bar_w, height)}"><title>'
                   f'{b["count"]:,} addresses predicted near {b["bin_mid"]:.0%}</title></path>')
        if b["count"] == most:
            out.append(f'<text class="v" x="{px(b["bin_mid"]):.1f}" '
                       f'y="{base - height - 5:.1f}" text-anchor="middle">{b["count"]:,}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def importance_svg(rows: list[dict], title: str, labelled: int = 5) -> str:
    """What the model leans on: each feature's share of the mean |SHAP|, largest first."""
    row_h, x0, w, top = 26, 300, 280, 68
    W, H = 640, top + row_h * len(rows) + 20
    most = max((r["importance"] for r in rows), default=1) or 1
    out = _open(W, H, f"What the deposit-address model leans on: {title}")
    out += [f'<text class="t" x="24" y="28">What the model leans on: {escape(title)}</text>',
            '<text class="s" x="24" y="48">Each feature\'s share of the average effect on a '
            'prediction (mean |SHAP|)</text>',
            f'<line class="a" x1="{x0}" x2="{x0}" y1="{top - 6}" y2="{H - 14}"/>']
    for i, r in enumerate(rows):
        y = top + i * row_h
        name = FEATURE_NAMES[r["feature"]]
        length = max(2.0, w * r["importance"] / most)
        rad = min(4.0, length / 2)
        out.append(f'<text class="s" x="{x0 - 10}" y="{y + 14}" text-anchor="end">'
                   f'{escape(name)}</text>')
        out.append(f'<path class="b" d="M{x0},{y + 2} h{length - rad:.1f} q{rad:.1f},0 '
                   f'{rad:.1f},{rad:.1f} v{18 - 2 * rad:.1f} q0,{rad:.1f} {-rad:.1f},{rad:.1f} '
                   f'h{-(length - rad):.1f} z"><title>{escape(name)}: '
                   f'{r["importance"]:.1%}</title></path>')
        if i < labelled:
            out.append(f'<text class="v" x="{x0 + length + 8:.1f}" y="{y + 15}">'
                       f'{r["importance"]:.0%}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"
