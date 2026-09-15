"""First extracted knowledge read service behind the compatibility facade."""

from __future__ import annotations

from threaddesk.core.models import GraphEvent, KnowledgeNode, Relation
from threaddesk.storage.protocols import GraphStore


class KnowledgeReader:
    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def get_node(self, node_id: str) -> KnowledgeNode:
        return self.store.get_node(node_id)

    def list_nodes(self) -> list[KnowledgeNode]:
        return self.store.list_nodes()

    def list_relations(self) -> list[Relation]:
        return self.store.list_relations()

    def list_events(self) -> list[GraphEvent]:
        return self.store.list_graph_events()
