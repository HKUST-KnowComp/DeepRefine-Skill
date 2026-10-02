from __future__ import annotations

import copy
import json
import pickle
import shutil
from pathlib import Path
from typing import Any

import networkx as nx
from networkx.readwrite import json_graph

from atlas_rag.vectorstore.create_graph_index import (
    build_faiss_index_flat,
    compute_graph_embeddings,
    compute_text_embeddings,
)
from atlas_rag.vectorstore.embedding_model import BaseEmbeddingModel

from .passage_roundtrip import merge_passages, snapshot_passages


def load_graphify_json(path: Path) -> tuple[dict[str, Any], nx.DiGraph]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    links_key = "links" if "links" in raw else "edges"
    # node_link_graph returns Graph/ DiGraph depending on attrs; force DiGraph
    base = json_graph.node_link_graph(raw, edges=links_key, directed=True)
    if not isinstance(base, nx.DiGraph):
        kg = nx.DiGraph(base)
    else:
        kg = base

    id_to_meta = {n.get("id"): n for n in raw.get("nodes", []) if n.get("id")}

    for nid in list(kg.nodes):
        meta = id_to_meta.get(nid, {})
        label = meta.get("label") or meta.get("id") or str(nid)
        kg.nodes[nid]["id"] = label
        kg.nodes[nid]["type"] = kg.nodes[nid].get("type") or "entity"
        kg.nodes[nid]["file_id"] = meta.get("source_file")
        if "community" in meta:
            kg.nodes[nid]["community"] = meta["community"]

    for u, v, data in kg.edges(data=True):
        if "relation" not in data:
            data["relation"] = data.pop("label", "related_to")
        data.setdefault("type", "Relation")
        conf = data.get("confidence", "INFERRED")
        data.setdefault("confidence", conf)

    return raw, kg


def _entity_nodes(kg: nx.DiGraph) -> list[str]:
    return [
        n
        for n in kg.nodes
        if kg.nodes[n].get("type") != "passage"
    ]


def build_deeprefine_data(
    kg: nx.DiGraph,
    sentence_encoder: BaseEmbeddingModel,
    *,
    normalize_embeddings: bool = False,
    batch_size: int = 64,
) -> dict[str, Any]:
    node_list = _entity_nodes(kg)
    node_set = set(node_list)
    edge_list = [(u, v) for u, v in kg.edges if u in node_set and v in node_set]
    node_list_string = [kg.nodes[n]["id"] for n in node_list]
    edge_list_string = [
        f"{kg.nodes[u]['id']} {kg.edges[u, v]['relation']} {kg.nodes[v]['id']}"
        for u, v in edge_list
    ]

    node_embeddings, edge_embeddings = compute_graph_embeddings(
        node_list_string,
        edge_list_string,
        sentence_encoder,
        batch_size=batch_size,
        normalize_embeddings=normalize_embeddings,
    )

    node_faiss_index = build_faiss_index_flat(node_embeddings)
    edge_faiss_index = build_faiss_index_flat(edge_embeddings)

    passage_id = "__deeprefine_passage__"
    if passage_id not in kg.nodes:
        kg.add_node(
            passage_id,
            id="graphify knowledge graph",
            type="passage",
            file_id=None,
        )
    text_dict = {passage_id: "graphify knowledge graph"}
    text_embeddings = compute_text_embeddings(
        list(text_dict.values()),
        sentence_encoder,
        batch_size=8,
        normalize_embeddings=normalize_embeddings,
    )
    text_faiss_index = build_faiss_index_flat(text_embeddings)

    n_nodes = len(node_list)
    n_edges = len(edge_list)
    return {
        "KG": kg,
        "node_faiss_index": node_faiss_index,
        "edge_faiss_index": edge_faiss_index,
        "text_faiss_index": text_faiss_index,
        "node_embeddings": node_embeddings,
        "edge_embeddings": edge_embeddings,
        "text_embeddings": text_embeddings,
        "node_list": node_list,
        "edge_list": edge_list,
        "text_dict": text_dict,
        "edge_faiss_id_to_list_idx": {i: i for i in range(n_edges)},
        "node_faiss_id_to_list_idx": {i: i for i in range(n_nodes)},
        "text_faiss_id_to_list_idx": {0: 0},
    }


def load_or_build_data(
    graph_path: Path,
    cache_pkl: Path,
    sentence_encoder: BaseEmbeddingModel,
    *,
    rebuild: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    graph_mtime = graph_path.stat().st_mtime
    if (
        not rebuild
        and cache_pkl.is_file()
        and cache_pkl.stat().st_mtime >= graph_mtime
    ):
        with cache_pkl.open("rb") as f:
            bundle = pickle.load(f)
        raw = bundle["graphify_raw"]
        data = bundle["deeprefine_data"]
        return raw, data

    raw, kg = load_graphify_json(graph_path)
    data = build_deeprefine_data(kg, sentence_encoder)
    cache_pkl.parent.mkdir(parents=True, exist_ok=True)
    with cache_pkl.open("wb") as f:
        pickle.dump({"graphify_raw": raw, "deeprefine_data": data}, f)
    return raw, data


def sync_kg_to_graphify(raw: dict[str, Any], kg: nx.DiGraph) -> dict[str, Any]:
    """Merge refined nx graph back into graphify node-link JSON."""
    out = copy.deepcopy(raw)
    links_key = "links" if "links" in out else "edges"
    passages = snapshot_passages(out)

    old_nodes = {n["id"]: n for n in out.get("nodes", [])}
    new_nodes: list[dict[str, Any]] = []
    for nid in sorted(kg.nodes, key=str):
        if kg.nodes[nid].get("type") == "passage":
            continue
        base = copy.deepcopy(old_nodes.get(nid, {}))
        base["id"] = nid
        base["label"] = kg.nodes[nid].get("id", nid)
        if kg.nodes[nid].get("file_id"):
            base["source_file"] = kg.nodes[nid]["file_id"]
        if "community" in kg.nodes[nid]:
            base["community"] = kg.nodes[nid]["community"]
        new_nodes.append(base)

    new_links: list[dict[str, Any]] = []
    for u, v, edata in kg.edges(data=True):
        if kg.nodes[u].get("type") == "passage" or kg.nodes[v].get("type") == "passage":
            continue
        link: dict[str, Any] = {
            "source": u,
            "target": v,
            "relation": edata.get("relation", "related_to"),
            "confidence": edata.get("confidence", "INFERRED"),
        }
        if link["confidence"] == "INFERRED":
            link["confidence_score"] = 0.7
        elif link["confidence"] == "EXTRACTED":
            link["confidence_score"] = 1.0
        else:
            link["confidence_score"] = 0.4
        new_links.append(link)

    out["nodes"] = new_nodes
    out[links_key] = new_links
    return merge_passages(out, passages)


def save_graphify_json(
    path: Path,
    graph_data: dict[str, Any],
    *,
    backup_path: Path | None = None,
) -> None:
    if backup_path and path.is_file():
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_path)
    path.write_text(json.dumps(graph_data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_bundle(cache_pkl: Path, raw: dict[str, Any], data: dict[str, Any]) -> None:
    cache_pkl.parent.mkdir(parents=True, exist_ok=True)
    with cache_pkl.open("wb") as f:
        pickle.dump({"graphify_raw": raw, "deeprefine_data": data}, f)
