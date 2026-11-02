"""Credential-free n8n topology and deterministic high-level stages.

Only names, types, disabled flags and edges are retained. Node parameters,
credentials, expressions, pinned data and workflow settings never enter this map.
"""
from collections import defaultdict

MAX_NODES = 1000
MAX_EDGES = 5000


def extract_topology(raw: dict) -> dict | None:
    raw_nodes = raw.get("nodes")
    if not isinstance(raw_nodes, list):
        return None
    # Return no partial map: omitting nodes could misrepresent the logic.
    if len(raw_nodes) > MAX_NODES:
        return {"unavailable_reason": "Workflow exceeds the 1,000-node map limit."}
    nodes = []
    names = set()
    for item in raw_nodes:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        if len(item["name"]) > 256:
            return {"unavailable_reason": "A workflow node name exceeds the map limit."}
        name = item["name"]
        kind = str(item.get("type", "unknown"))[:200]
        if kind.endswith(".stickyNote"):
            continue
        if name in names:
            return {"unavailable_reason": "Workflow node names are ambiguous."}
        names.add(name)
        nodes.append({"id": name, "name": name, "type": kind, "disabled": bool(item.get("disabled", False))})
    edges = []
    connections = raw.get("connections")
    if isinstance(connections, dict):
        for source, channels in connections.items():
            if source not in names or not isinstance(channels, dict):
                continue
            for channel, outputs in channels.items():
                if not isinstance(outputs, list):
                    continue
                for output, links in enumerate(outputs):
                    if not isinstance(links, list):
                        continue
                    for link in links:
                        if isinstance(link, dict) and isinstance(link.get("node"), str) and link["node"] in names:
                            edges.append({"source": source, "target": link["node"], "output": output, "channel": str(channel)[:64]})
                            if len(edges) > MAX_EDGES:
                                return {"unavailable_reason": "Workflow exceeds the 5,000-connection map limit."}
    return {"version": 1, "nodes": nodes, "edges": edges}


def build_logic_map(topology: dict | None) -> dict:
    if not topology or topology.get("unavailable_reason"):
        return {"available": False, "reason": (topology or {}).get("unavailable_reason", "Workflow definition is unavailable. Sync an API-connected n8n instance to load its logic.")}
    nodes = topology.get("nodes", [])
    edges = topology.get("edges", [])
    if not nodes:
        return {"available": False, "reason": "No executable nodes were found in the synced definition."}
    by_id = {n["id"]: n for n in nodes}
    outgoing, incoming = defaultdict(list), defaultdict(list)
    for e in edges:
        if e["source"] in by_id and e["target"] in by_id:
            outgoing[e["source"]].append(e)
            incoming[e["target"]].append(e)
    visited, stages, membership = set(), [], {}
    # Roots first, followed by branch/merge points, then cycles/disconnected nodes.
    ordered = sorted(nodes, key=lambda n: (bool(incoming[n["id"]]), nodes.index(n)))
    for node in ordered:
        node_id = node["id"]
        if node_id in visited:
            continue
        chain = []
        current = node_id
        while current not in visited:
            visited.add(current)
            chain.append(by_id[current])
            # Keep routing, merge, error and auxiliary-port connections explicit.
            if len(chain) == 4 or len(outgoing[current]) != 1 or len(incoming[current]) > 1:
                break
            edge = outgoing[current][0]
            nxt = edge["target"]
            if edge.get("channel") != "main" or len(incoming[nxt]) != 1 or len(outgoing[nxt]) > 1 or nxt in visited:
                break
            current = nxt
        stage_id = f"stage-{len(stages) + 1}"
        for n in chain:
            membership[n["id"]] = stage_id
        title = chain[0]["name"] if len(chain) == 1 else f'{chain[0]["name"]} → {chain[-1]["name"]}'
        stages.append({"id": stage_id, "title": title, "nodes": chain})
    links = []
    seen = set()
    for edge in edges:
        source, target = membership.get(edge["source"]), membership.get(edge["target"])
        if not source or not target:
            continue
        # Include cycle back-edges even when their endpoints are in one group.
        if source == target:
            group = next(s for s in stages if s["id"] == source)
            ids = [n["id"] for n in group["nodes"]]
            if ids.index(edge["target"]) > ids.index(edge["source"]):
                continue
        key = (source, target, edge.get("output", 0), edge.get("channel", "main"))
        if key in seen:
            continue
        seen.add(key)
        kind = by_id[edge["source"]]["type"].split(".")[-1].lower()
        label = ("True" if edge.get("output", 0) == 0 else "False") if kind == "if" else (f'Output {edge.get("output", 0) + 1}' if len(outgoing[edge["source"]]) > 1 else "")
        if edge.get("channel", "main") != "main":
            label = edge["channel"]
        links.append({"source": source, "target": target, "label": label})
    return {"available": True, "node_count": len(nodes), "stages": stages, "edges": links, "grouping": "Connected sequences of up to four nodes; branches and merges remain separate."}
