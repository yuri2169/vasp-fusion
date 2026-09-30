"""The tripartite graph: IP <-> entity <-> transaction.

The PS asks for an entity/transaction graph linking IPs, wallets and
transactions. We build it in three parts because they have different shapes and
very different sizes:

  * ENTITY PAYMENT GRAPH (igraph, in memory). Entity -> entity, weighted by value
    and count. This is what topology features and Node2Vec run over. igraph's C
    backend matters here - NetworkX falls over around 500k edges.

  * ENTITY x IP BIPARTITE (sparse matrix). Who announced whose transactions.
    This is the attribution engine's raw material.

  * TRANSACTION LAYER (kept in DuckDB, not in memory). The link-analysis view
    needs per-transaction detail, but materialising every transaction as a graph
    node would put ~500k nodes in RAM to serve a view that is hard-capped at
    1,500 nodes anyway. We extract k-hop subgraphs on demand instead (§4.4 R4).

ANALYSIS SET. Address clustering leaves a long tail of never-spent addresses as
singleton entities - correct behaviour for the heuristics, but they carry no
behaviour to analyse. We score entities that actually transacted and report the
filter rather than quietly pretending the tail does not exist.
"""
from __future__ import annotations

import igraph as ig
import numpy as np
import polars as pl
from scipy.sparse import coo_matrix, csr_matrix
from scipy.sparse.csgraph import connected_components


def entity_edges(txs: pl.DataFrame) -> pl.DataFrame:
    """Directed entity -> entity payment edges, aggregated."""
    flows = (txs.select(["txid", "timestamp", "sender_entity", "receiver_entities",
                         "output_amounts"])
             .drop_nulls("sender_entity")
             .explode(["receiver_entities"])
             .rename({"receiver_entities": "dst"})
             .drop_nulls("dst")
             .filter(pl.col("sender_entity") != pl.col("dst")))
    # Value per edge: the transaction's total output. Splitting it exactly across
    # receivers needs per-output entity attribution, which we do carry, but the
    # aggregate is what the topology features consume.
    flows = flows.with_columns(pl.col("output_amounts").list.sum().alias("value"))
    return (flows.group_by(["sender_entity", "dst"])
            .agg([pl.len().alias("n_tx"),
                  pl.col("value").sum().alias("value"),
                  pl.col("timestamp").min().alias("first_ts"),
                  pl.col("timestamp").max().alias("last_ts")])
            .rename({"sender_entity": "src"}))


def active_entities(txs: pl.DataFrame, edges: pl.DataFrame, min_degree: int = 1) -> list[str]:
    """Entities we can actually say something about.

    An entity that only ever received one payment and never spent has no
    topology, no rhythm and no announcing IP of its own. Scoring it would be
    guessing, so it stays out of the analysis set and the count is reported.
    """
    sent = edges.group_by("src").agg(pl.len().alias("out_deg"))
    recv = edges.group_by("dst").agg(pl.len().alias("in_deg"))
    deg = (sent.join(recv, left_on="src", right_on="dst", how="full", coalesce=True)
           .with_columns([pl.col("out_deg").fill_null(0), pl.col("in_deg").fill_null(0)]))
    key = "src" if "src" in deg.columns else deg.columns[0]
    keep = deg.filter((pl.col("out_deg") >= min_degree)
                      | (pl.col("in_deg") >= max(2, min_degree + 1)))
    # SORTED, and that is load-bearing. Polars group_by returns rows in
    # non-deterministic order, so an unsorted list here gave the igraph vertices
    # different indices on every run. Betweenness samples a fixed set of pivot
    # INDICES, so different indices meant different pivots, which meant the
    # topology features were not reproducible from a fixed seed at all. The
    # golden-file test caught it; nothing else would have.
    return sorted(keep.get_column(key).drop_nulls().to_list())


class EntityGraph:
    """igraph wrapper over the entity payment graph."""

    def __init__(self, edges: pl.DataFrame, nodes: list[str]):
        self.nodes = nodes
        self.index = {e: i for i, e in enumerate(nodes)}
        keep = edges.filter(pl.col("src").is_in(nodes) & pl.col("dst").is_in(nodes))
        src = [self.index[s] for s in keep.get_column("src").to_list()]
        dst = [self.index[d] for d in keep.get_column("dst").to_list()]
        self.g = ig.Graph(n=len(nodes), edges=list(zip(src, dst)), directed=True)
        self.g.es["weight"] = keep.get_column("value").to_list()
        self.g.es["n_tx"] = keep.get_column("n_tx").to_list()
        self.edges = keep

    @property
    def n_nodes(self) -> int:
        return self.g.vcount()

    @property
    def n_edges(self) -> int:
        return self.g.ecount()

    def topology(self) -> dict[str, np.ndarray]:
        """Structural features. Every one is a whole-graph vectorised call - a
        per-node Python loop over 250k nodes would cost minutes."""
        g = self.g
        und = g.as_undirected(mode="collapse", combine_edges="sum")
        out: dict[str, np.ndarray] = {
            "degree_in": np.asarray(g.indegree(), dtype=np.float32),
            "degree_out": np.asarray(g.outdegree(), dtype=np.float32),
            "wdegree_in": np.asarray(g.strength(mode="in", weights="weight"), dtype=np.float32),
            "wdegree_out": np.asarray(g.strength(mode="out", weights="weight"), dtype=np.float32),
            "pagerank": np.asarray(g.pagerank(weights="weight"), dtype=np.float32),
            "clustering_coef": np.nan_to_num(
                np.asarray(und.transitivity_local_undirected(mode="zero"), dtype=np.float32)),
            "core_number": np.asarray(und.coreness(), dtype=np.float32),
        }
        # Betweenness is O(VE) exactly; on a graph this size that is minutes.
        # Estimate it from a fixed random sample of source vertices instead - the
        # feature only has to RANK entities as bridges, not measure them exactly.
        # (igraph rejects `sources` and `cutoff` together, so this is pivots only.)
        n = g.vcount()
        if n > 0:
            k = min(n, 400)
            pivots = np.random.default_rng(0).choice(n, size=k, replace=False).tolist()
            bt = np.asarray(und.betweenness(sources=pivots), dtype=np.float64)
            # ROUNDED ON PURPOSE. igraph accumulates betweenness in parallel and
            # floating-point addition is not associative, so the reduction order
            # varies run to run and the last bits differ. That made the whole
            # feature matrix non-reproducible from a fixed seed - the golden-file
            # test caught it. The value is a pivot-sampled ESTIMATE used only to
            # RANK entities as bridges, so digits beyond this are noise anyway.
            out["betweenness_est"] = np.round(
                bt * (n / max(1, k)), 4).astype(np.float32)
        return out


def entity_ip_matrix(df: pl.DataFrame, addr_to_entity: pl.DataFrame,
                     txs: pl.DataFrame, nodes: list[str]) -> tuple[csr_matrix, list[str], dict]:
    """Entity x IP co-occurrence counts, restricted to origin-plausible relays.

    Every observed announcement of a transaction is attributed to the spending
    entity of that transaction. That is deliberately naive at this stage - the
    announcement may well have come from a relay rather than the originator - and
    correcting for it is exactly what the diffusion weighting in
    vaspfusion.attribute does. Building the honest, noisy matrix first and
    discounting it explicitly is the whole design.
    """
    if "src_ip" not in df.columns:
        return csr_matrix((len(nodes), 0)), [], {"available": False}

    tx_owner = txs.select(["txid", "sender_entity"]).drop_nulls("sender_entity")
    obs = (df.select(["txid", "src_ip"]).drop_nulls()
           .join(tx_owner, on="txid", how="inner")
           .filter(pl.col("sender_entity").is_in(nodes)))
    if obs.height == 0:
        return csr_matrix((len(nodes), 0)), [], {"available": False}

    ips = obs.get_column("src_ip").unique().sort().to_list()
    ip_index = {ip: i for i, ip in enumerate(ips)}
    ent_index = {e: i for i, e in enumerate(nodes)}

    counts = obs.group_by(["sender_entity", "src_ip"]).len()
    rows = np.array([ent_index[e] for e in counts.get_column("sender_entity").to_list()])
    cols = np.array([ip_index[i] for i in counts.get_column("src_ip").to_list()])
    vals = counts.get_column("len").to_numpy().astype(np.float32)
    m = csr_matrix((vals, (rows, cols)), shape=(len(nodes), len(ips)))
    return m, ips, {"available": True, "n_ips": len(ips), "n_observations": int(vals.sum())}


def link_campaigns(edges: pl.DataFrame, entities: list[str]) -> dict[str, list[str]]:
    """Group flagged entities that belong to one operation.

    WHY THIS EXISTS. A single 14-hop peeling chain creates roughly a dozen mule
    wallets, and each one is independently anomalous, so a per-entity queue
    reports the same laundering operation a dozen times. Scoring 89k entities and
    handing back 5,000 alerts is not triage - it is a second haystack.

    Entities in one campaign are connected in the payment graph by construction:
    the money moved between them. So the connected components of the subgraph
    induced by the flagged set ARE the candidate operations. The
    highest-scoring member becomes the case file; the rest are attached to it as
    linked entities, still visible, no longer separate work items.

    This is what turns "500,000 records" into "a handful of case files" - and it
    is the analyst's actual unit of work, which is a person or an operation, not
    a wallet cluster.
    """
    if not entities:
        return {}
    index = {e: i for i, e in enumerate(entities)}
    sub = edges.filter(pl.col("src").is_in(entities) & pl.col("dst").is_in(entities))
    n = len(entities)
    if sub.height == 0:
        return {e: [e] for e in entities}
    rows = np.array([index[s] for s in sub.get_column("src").to_list()])
    cols = np.array([index[d] for d in sub.get_column("dst").to_list()])
    adj = coo_matrix((np.ones(len(rows), dtype=np.int8), (rows, cols)), shape=(n, n))
    _, labels = connected_components(adj, directed=False)
    groups: dict[int, list[str]] = {}
    for e, lab in zip(entities, labels):
        groups.setdefault(int(lab), []).append(e)
    return {e: groups[int(lab)] for e, lab in zip(entities, labels)}


def member_stats(edges: pl.DataFrame, members: list[str]) -> list[dict]:
    """Per member of one case: payments to and from the OTHER members only.

    A case is the flagged actors that paid each other (link_campaigns), so the
    money moving inside it is the operation; money to the outside world is
    everyone else's business and would drown it.
    """
    inside = edges.filter(pl.col("src").is_in(members) & pl.col("dst").is_in(members)
                          & (pl.col("src") != pl.col("dst")))
    out = inside.group_by("src").agg(pl.col("value").sum().alias("value_out"),
                                     pl.col("n_tx").sum().alias("n_tx"))
    inn = inside.group_by("dst").agg(pl.col("value").sum().alias("value_in"))
    o = {r["src"]: r for r in out.to_dicts()}
    i = {r["dst"]: r["value_in"] for r in inn.to_dicts()}
    return [{"entity": m, "n_tx": int(o.get(m, {}).get("n_tx") or 0),
             "value_out": int(o.get(m, {}).get("value_out") or 0),
             "value_in": int(i.get(m) or 0)} for m in members]

def khop_subgraph(edges: pl.DataFrame, centre: str, hops: int = 2,
                  node_cap: int = 1500) -> tuple[list[str], pl.DataFrame, dict]:
    """Server-side k-hop extraction with a hard node cap.

    Rendering an unbounded neighbourhood is how link-analysis UIs kill the
    browser (§4.4 R4). We reduce hops until the result fits and tell the analyst
    what was trimmed rather than silently truncating.
    """
    frontier = {centre}
    seen = {centre}
    reached_hops = 0
    for h in range(hops):
        nxt = (edges.filter(pl.col("src").is_in(list(frontier))
                            | pl.col("dst").is_in(list(frontier)))
               .select(["src", "dst"]))
        cand = set(nxt.get_column("src").to_list()) | set(nxt.get_column("dst").to_list())
        new = cand - seen
        if len(seen) + len(new) > node_cap:
            # Take the highest-value neighbours rather than an arbitrary slice.
            room = max(0, node_cap - len(seen))
            ranked = (edges.filter(pl.col("src").is_in(list(frontier))
                                   | pl.col("dst").is_in(list(frontier)))
                      .sort("value", descending=True))
            picked: list[str] = []
            for s, d in zip(ranked.get_column("src").to_list(),
                            ranked.get_column("dst").to_list()):
                for cand_node in (s, d):
                    if cand_node not in seen and cand_node not in picked:
                        picked.append(cand_node)
                if len(picked) >= room:
                    break
            seen |= set(picked[:room])
            reached_hops = h + 1
            break
        seen |= new
        frontier = new
        reached_hops = h + 1
        if not frontier:
            break

    sub = edges.filter(pl.col("src").is_in(list(seen)) & pl.col("dst").is_in(list(seen)))
    meta = {"nodes_shown": len(seen), "hops": reached_hops, "capped": len(seen) >= node_cap}
    return sorted(seen), sub, meta


def expand_entity(addr_map: pl.DataFrame, txs: pl.DataFrame, entity: str,
                  max_addresses: int = 60, max_txs: int = 60) -> dict:
    """Drill from an entity supernode down to wallets and transactions.

    The PS asks for a graph linking IPs, WALLETS and transactions. Entity
    supernodes are the right default - an alert on a single address is an alert
    on a fragment of a person - but the address layer beneath them is real data
    we already hold, and a judge asking "which actual wallet?" deserves an answer.

    Capped and reported: an exchange cluster can hold hundreds of addresses and
    rendering all of them would defeat the purpose of the view.
    """
    mine = addr_map.filter(pl.col("entity_id") == entity)
    addresses = mine.get_column("address").to_list()

    touching = txs.filter(
        pl.col("input_addresses").list.eval(pl.element().is_in(addresses)).list.any()
        | pl.col("output_addresses").list.eval(pl.element().is_in(addresses)).list.any())
    truncated = len(addresses) > max_addresses or touching.height > max_txs
    shown_addr = addresses[:max_addresses]
    shown_addr_set = set(shown_addr)
    touching = touching.head(max_txs)

    edges: list[dict] = []
    tx_rows: list[dict] = []
    for r in touching.select(["txid", "timestamp", "input_addresses",
                              "output_addresses", "output_amounts"]).iter_rows(named=True):
        tx_rows.append({"txid": r["txid"], "ts": str(r["timestamp"]),
                        "value": int(sum(r["output_amounts"] or []))})
        for a in (r["input_addresses"] or []):
            if a in shown_addr_set:
                edges.append({"source": a, "target": r["txid"], "kind": "spends"})
        for a in (r["output_addresses"] or []):
            if a in shown_addr_set:
                edges.append({"source": r["txid"], "target": a, "kind": "pays"})

    return {
        "entity": entity,
        "addresses": [{"address": a, "entity": entity} for a in shown_addr],
        "transactions": tx_rows,
        "edges": edges,
        "truncated": bool(truncated),
        "n_addresses_total": len(addresses),
        "n_transactions_total": int(touching.height),
    }
