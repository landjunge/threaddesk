/* Screen-pixel SVG labels and hit regions, independently of camera zoom. */
window.ThreadDeskMapLabels = (nodeLayer, state) => {
  const {SHAPE, SIZE} = state.shapes, viewport = state.viewport;
    const labelItems = [...nodeLayer.querySelectorAll(".map-node")].map((group, order) => {
      const label = group.querySelector(".map-label");
      const texts = [...label.querySelectorAll("text")];
      return {group, label, texts, hit: group.querySelector(".map-node-hit"),
        labelHit: label.querySelector(".map-label-hit"), order, widths: new Map()};
    });
    const invalidate = () => labelItems.forEach(item => item.widths.clear());
    const update = () => {
      const {scale, offsetX, offsetY} = state.camera();
      const {width: VIEW_W, height: VIEW_H} = state.dimensions();
      const placed = state.positions();
      const candidates = labelItems.filter(item => item.group.style.display !== "none")
        .map(item => {
          const {group, label, texts, order, widths} = item;
          const important = group.classList.contains("is-selected") ||
            group.classList.contains("is-hovered") || document.activeElement === group;
          const font = important ? 16 : 14;
          texts.forEach((text, index) => {
            text.style.fontSize = `${font}px`;
            text.setAttribute("y", index * (font + 4));
          });
          const type = getComputedStyle(texts[0] || label);
          const metricKey = `${font}|${type.fontFamily}|${type.fontWeight}|${type.fontStyle}|${type.fontStretch}|${type.letterSpacing}`;
          if (!widths.has(metricKey)) widths.set(metricKey,
            Math.min(VIEW_W - 24, Math.max(1, ...texts.map(text => text.getComputedTextLength()))));
          const point = placed.get(group.dataset.nodeId);
          const shape = SHAPE[group.dataset.kind] || "circle";
          const dimensions = Array.isArray(SIZE[shape]) ? SIZE[shape] : [SIZE[shape], SIZE[shape]];
          return {...item, font, width: widths.get(metricKey), height: Math.max(1, texts.length) * (font + 4),
            x: offsetX + scale * point.x, y: offsetY + scale * point.y,
            radius: dimensions[1] * scale,
            halfWidth: dimensions[0] * scale, halfHeight: dimensions[1] * scale,
            priority: important ? 3 : group.classList.contains("is-near") ? 2 :
              group.dataset.kind === "project" ? 1 : 0};
        });
      viewport.labels(candidates, VIEW_W, VIEW_H).forEach(item => {
        item.label.style.display = item.visible ? "" : "none";
        item.label.dataset.screenFontSize = String(item.font);
        item.label.setAttribute("transform",
          `translate(${item.shiftX / scale} ${item.baseline / scale}) scale(${1 / scale})`);
        // The empty space between a displaced caption and its shape must stay
        // clickable for other nodes. Two exact regions avoid an invisible wall.
        const halfWidth = item.halfWidth / scale, halfHeight = item.halfHeight / scale;
        Object.entries({x: -halfWidth, y: -halfHeight, width: halfWidth * 2, height: halfHeight * 2})
          .forEach(([key, value]) => item.hit.setAttribute(key, value));
        Object.entries({x: -item.width / 2, y: -item.font,
          width: item.width, height: item.height})
          .forEach(([key, value]) => item.labelHit.setAttribute(key, value));
      });
    };
  return {update, invalidate};
};
