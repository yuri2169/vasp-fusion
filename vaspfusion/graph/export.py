"""Link-graph export for other tools: GraphML (Gephi, yEd, Maltego and i2
import it) and a flat CSV edge list."""
from __future__ import annotations

import csv
import io
from xml.sax.saxutils import escape, quoteattr

GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"  # XML namespace name, never fetched
_NODE_KEYS = (("type", "string"), ("label", "string"), ("score", "double"),
              ("alerted", "boolean"), ("subject", "boolean"))
_EDGE_KEYS = (("kind", "string"), ("value_btc", "double"), ("n_tx", "long"),
              ("first_ts", "string"), ("last_ts", "string"))


def _v(x) -> str:
    return ("true" if x else "false") if isinstance(x, bool) else str(x)


def to_graphml(nodes: list[dict], edges: list[dict]) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8"?>', f'<graphml xmlns="{GRAPHML_NS}">']
    out += [f'<key id="n{i}" for="node" attr.name="{k}" attr.type="{t}"/>'
            for i, (k, t) in enumerate(_NODE_KEYS)]
    out += [f'<key id="e{i}" for="edge" attr.name="{k}" attr.type="{t}"/>'
            for i, (k, t) in enumerate(_EDGE_KEYS)]
    out.append('<graph id="vaspfusion" edgedefault="directed">')
    for n in nodes:
        data = "".join(f'<data key="n{i}">{escape(_v(n[k]))}</data>'
                       for i, (k, _) in enumerate(_NODE_KEYS) if n.get(k) is not None)
        out.append(f'<node id={quoteattr(str(n["id"]))}>{data}</node>')
    for j, e in enumerate(edges):
        data = "".join(f'<data key="e{i}">{escape(_v(e[k]))}</data>'
                       for i, (k, _) in enumerate(_EDGE_KEYS) if e.get(k) is not None)
        out.append(f'<edge id="e{j}" source={quoteattr(str(e["src"]))} '
                   f'target={quoteattr(str(e["dst"]))}>{data}</edge>')
    out += ["</graph>", "</graphml>"]
    return "\n".join(out)


def to_csv_edges(edges: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["src", "dst", "kind", "value_btc", "n_tx", "first_ts", "last_ts"])
    for e in edges:
        w.writerow([e["src"], e["dst"], e.get("kind", ""), e.get("value_btc", ""),
                    e.get("n_tx", ""), e.get("first_ts", ""), e.get("last_ts", "")])
    return buf.getvalue()
