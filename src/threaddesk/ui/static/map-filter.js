/* One filter projection for both renderers and the DOM node list. */
window.ThreadDeskGraphFilter = (graph, filters, activity, selected) => {
  const normalize = value => String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase();
  const query = normalize(filters.query).trim(), project = filters.project_id;
  const members = new Set(project ? [project] : []);
  if (project) {
    const thread = graph.nodes.find(node => node.id === project && node.kind === 'project')?.metadata?.thread_id;
    graph.nodes.forEach(node => {
      if (node.metadata?.project_id === project || node.metadata?.project_ids?.includes(project)
          || thread && node.metadata?.thread_id === thread) members.add(node.id);
    });
    let changed = true;
    while (changed) {
      const previous = members.size;
      graph.relations.forEach(edge => {
        if (edge.kind === 'contains' && members.has(edge.source_id)) members.add(edge.target_id);
      });
      changed = members.size !== previous;
    }
  }
  const center = filters.center || (filters.hops ? selected : null);
  let neighborhood = new Set(center ? [center] : []);
  for (let step = 0; step < filters.hops && neighborhood.size; step++) {
    const reached = new Set(neighborhood);
    graph.relations.forEach(edge => {
      if (neighborhood.has(edge.source_id)) reached.add(edge.target_id);
      if (neighborhood.has(edge.target_id)) reached.add(edge.source_id);
    });
    neighborhood = reached;
  }
  return new Set(graph.nodes.filter(node =>
    (!query || normalize(`${node.title} ${node.details || ''}`).includes(query)) &&
    (!filters.kind || node.kind === filters.kind) && (!project || members.has(node.id)) &&
    (!filters.status || node.status === filters.status) &&
    (!filters.band || activity.current(node).band === filters.band) &&
    (!center || neighborhood.has(node.id))).map(node => node.id));
};
