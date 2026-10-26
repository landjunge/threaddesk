"""Derive project filters from confirmed thread/node assignments, without writes."""
from collections import defaultdict


def project_records(store, records):
    if store is None:
        yield from records
        return
    nodes = {node.id: node for node in store.list_nodes()}
    projects = {identity: node for identity, node in nodes.items() if node.kind == "project"}
    by_thread = defaultdict(set)
    for identity, node in projects.items():
        if node.metadata.get("thread_id"):
            by_thread[node.metadata["thread_id"]].add(identity)
    for thread in store.list_threads(include_archived=True):
        project = (thread.context.extra.get("organization") or {}).get("project_id")
        if project in projects:
            by_thread[thread.id].add(project)
    for record in records:
        memberships = set(by_thread.get(record.get("thread_id"), set()))
        if record.get("project_id"):
            memberships.add(record["project_id"])
        targets = [*record.get("node_ids", []), record.get("node_id")]
        for target in targets:
            if target in projects:
                memberships.add(target)
            elif target in nodes and nodes[target].metadata.get("project_id") in projects:
                memberships.add(nodes[target].metadata["project_id"])
        ordered = sorted(memberships)
        yield {**record, "project_id": record.get("project_id") or next(iter(ordered), ""),
               "project_ids": ordered,
               "project_title": " ".join(projects[identity].title for identity in ordered if identity in projects)}
