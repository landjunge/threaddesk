/* Screen geometry shared by the SVG camera and its readable label layer. */
(() => {
  const fit = (points, width, height, padding = 76) => {
    if (!points.length) return null;
    const left = Math.min(...points.map(p => p.x - p.r));
    const right = Math.max(...points.map(p => p.x + p.r));
    const top = Math.min(...points.map(p => p.y - p.r));
    const bottom = Math.max(...points.map(p => p.y + p.r));
    const scale = Math.max(0.04, Math.min(2,
      Math.max(1, width - padding * 2) / Math.max(1, right - left),
      Math.max(1, height - padding * 2) / Math.max(1, bottom - top)));
    return {scale, x: width / 2 - scale * (left + right) / 2,
      y: height / 2 - scale * (top + bottom) / 2};
  };
  const resize = (camera, before, after) => ({
    x: camera.x + (after.width - before.width) / 2,
    y: camera.y + (after.height - before.height) / 2,
  });
  const overlaps = (a, b) => a.x < b.x + b.width + 8 &&
    a.x + a.width + 8 > b.x && a.y < b.y + b.height + 6 &&
    a.y + a.height + 6 > b.y;

  // Label sizes remain in screen pixels. Shape bounds and earlier labels are
  // obstacles; selected titles may move to a free nearby space, never on top.
  const labels = (candidates, width, height) => {
    const occupied = candidates.map(item => ({
      x: item.x - item.halfWidth, y: item.y - item.halfHeight,
      width: item.halfWidth * 2, height: item.halfHeight * 2,
    }));
    return candidates.sort((a, b) => b.priority - a.priority || a.order - b.order)
      .map(item => {
        const x = Math.max(10, Math.min(width - item.width - 10, item.x - item.width / 2));
        const below = {x, y: item.y + item.radius + 12};
        const above = {x, y: item.y - item.radius - item.height - 12};
        const choices = [below, above];
        if (item.priority >= 3) {
          choices.push({x: item.x + item.halfWidth + 12, y: item.y - item.height / 2},
            {x: item.x - item.halfWidth - item.width - 12, y: item.y - item.height / 2});
          // Bounded fallback for a crowded overview selection.
          for (let distance = 24; distance <= Math.max(width, height); distance += 24) {
            choices.push({x, y: below.y + distance}, {x, y: above.y - distance},
              {x: x + distance, y: below.y}, {x: x - distance, y: below.y});
          }
        }
        const onStage = item.x >= 0 && item.x <= width && item.y >= 0 && item.y <= height;
        const box = onStage && choices.map(choice => ({...choice, width: item.width, height: item.height}))
          .find(choice => choice.x >= 8 && choice.y >= 8 && choice.x + choice.width <= width - 8 &&
            choice.y + choice.height <= height - 8 && !occupied.some(other => overlaps(choice, other)));
        if (box) occupied.push(box);
        return {...item, visible: Boolean(box), shiftX: (box || below).x + item.width / 2 - item.x,
          baseline: (box || below).y + item.font - item.y};
      });
  };
  // A page may have positive SVG dimensions before its final styles arrive.
  // Only the first layout waits; ordinary interaction never pays this delay.
  const stable = (stage, quietMs = 120, timeoutMs = 4000) => new Promise((resolve, reject) => {
    let previous = "", unchangedSince = performance.now(), frame;
    const timeout = setTimeout(() => {
      cancelAnimationFrame(frame);
      reject(new Error("map_stage_not_ready"));
    }, timeoutMs);
    const sample = () => {
      const now = performance.now();
      const width = stage.clientWidth, height = stage.clientHeight;
      const current = `${width}:${height}`;
      if (current !== previous || width <= 1 || height <= 1) unchangedSince = now;
      previous = current;
      if (width > 1 && height > 1 && now - unchangedSince >= quietMs) {
        clearTimeout(timeout);
        resolve({width, height});
      } else frame = requestAnimationFrame(sample);
    };
    frame = requestAnimationFrame(sample);
  });
  const ready = async stage => {
    let timer;
    const assets = async () => {
      if (document.readyState !== "complete") {
        await new Promise(resolve => window.addEventListener("load", resolve, {once: true}));
      }
      if ([...document.querySelectorAll('link[rel="stylesheet"]')].some(link =>
        !link.disabled && !link.sheet)) throw new Error("map_styles_not_ready");
      if (document.fonts?.ready) await document.fonts.ready;
    };
    try {
      await Promise.race([assets(), new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("map_assets_timeout")), 8000);
      })]);
    } finally { clearTimeout(timer); }
    return stable(stage);
  };
  window.ThreadDeskMapViewport = Object.freeze({fit, resize, labels, ready, stable});
})();
