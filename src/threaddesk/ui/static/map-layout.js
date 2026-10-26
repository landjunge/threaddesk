/* A bounded, deterministic map. Relationships order nearby slots; they never
 * acquire extra edges, and later refreshes retain established positions. */
(() => {
  window.ThreadDeskMapLayout = (nodes, relations, options) => {
    const {width, height, radiusOf, previous = new Map()} = options;
    const points = new Map(nodes.filter(node => previous.has(node.id))
      .map(node => [node.id, previous.get(node.id)]));
    if (points.size === nodes.length) return points;
    const byId = new Map(nodes.map(node => [node.id, node]));
    const neighbors = new Map(nodes.map(node => [node.id, new Set()]));
    relations.forEach(relation => {
      if (!byId.has(relation.source_id) || !byId.has(relation.target_id)) return;
      neighbors.get(relation.source_id).add(relation.target_id);
      neighbors.get(relation.target_id).add(relation.source_id);
    });
    const roots = [...nodes].sort((a, b) =>
      Number(b.kind === "project") - Number(a.kind === "project") ||
      neighbors.get(b.id).size - neighbors.get(a.id).size ||
      a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
    const order = [], seen = new Set();
    roots.forEach(root => {
      if (seen.has(root.id)) return;
      const queue = [root.id]; seen.add(root.id);
      for (let index = 0; index < queue.length; index += 1) {
        const id = queue[index]; order.push(byId.get(id));
        [...neighbors.get(id)].sort().forEach(next => {
          if (!seen.has(next)) { seen.add(next); queue.push(next); }
        });
      }
    });

    // Screen proportions influence the initial map, not saved coordinates.
    // Spacing leaves room for readable two-line captions after overview fit.
    const cellWidth = 246, cellHeight = 184;
    const columns = Math.max(1, Math.ceil(Math.sqrt(nodes.length * width / height * cellHeight / cellWidth)));
    const rows = Math.max(1, Math.ceil(nodes.length / columns));
    const slots = [];
    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < columns; col += 1) {
        const x = (col - (columns - 1) / 2) * cellWidth;
        const y = (row - (rows - 1) / 2) * cellHeight;
        slots.push({x: width / 2 + x, y: height / 2 + y, distance: x * x + y * y});
      }
    }
    slots.sort((a, b) => a.distance - b.distance || a.y - b.y || a.x - b.x);
    const occupied = new Map();
    const key = (x, y) => `${Math.floor(x / cellWidth)},${Math.floor(y / cellHeight)}`;
    const occupy = point => {
      const bucket = key(point.x, point.y);
      if (!occupied.has(bucket)) occupied.set(bucket, []);
      occupied.get(bucket).push(point);
    };
    points.forEach(occupy);
    const available = point => {
      const column = Math.floor(point.x / cellWidth), row = Math.floor(point.y / cellHeight);
      for (let dx = -1; dx <= 1; dx += 1) {
        for (let dy = -1; dy <= 1; dy += 1) {
          if ((occupied.get(`${column + dx},${row + dy}`) || []).some(other =>
            Math.abs(point.x - other.x) < cellWidth * .9 &&
            Math.abs(point.y - other.y) < cellHeight * .9)) return false;
        }
      }
      return true;
    };
    let slotIndex = 0;
    order.forEach(node => {
      if (points.has(node.id)) return;
      let point;
      do {
        const index = slotIndex++;
        point = slots[index] || {
          x: width / 2 + (index % columns - (columns - 1) / 2) * cellWidth,
          y: height / 2 + (Math.floor(index / columns) - (rows - 1) / 2) * cellHeight,
        };
      } while (!available(point));
      const placed = {x: point.x, y: point.y, r: radiusOf(node) + 26};
      points.set(node.id, placed); occupy(placed);
    });
    return points;
  };
})();
