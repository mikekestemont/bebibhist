/**
 * A tooltip that shows at once. The browser's own (``title``) waits about a second over the same spot, which on the
 * 9 pixels of the open access padlock left the reader with the question-mark cursor and no text (Mike, 24 Nov 2026).
 * It sits in the body at a fixed place, so no list or button cuts it off, and stays within the window. A finger has
 * no hover: a touch opens the record, which names the access itself.
 */
export function tip(node: HTMLElement, text: string) {
  let box: HTMLElement | null = null;
  const hide = () => {
    box?.remove();
    box = null;
    window.removeEventListener("scroll", hide, true);
  };
  const show = (event: PointerEvent) => {
    if (event.pointerType === "touch" || box) return;
    box = document.createElement("div");
    box.className = "tip";
    box.textContent = text;
    document.body.append(box);
    const at = node.getBoundingClientRect();
    const own = box.getBoundingClientRect();
    const left = Math.min(Math.max(8, at.left + at.width / 2 - own.width / 2), document.documentElement.clientWidth - own.width - 8);
    const above = at.top - own.height - 6;
    box.style.left = `${left}px`;
    box.style.top = `${above >= 8 ? above : at.bottom + 6}px`;
    window.addEventListener("scroll", hide, true);
  };
  node.addEventListener("pointerenter", show);
  node.addEventListener("pointerleave", hide);
  node.addEventListener("pointerdown", hide);
  return {
    update(next: string) { text = next; if (box) box.textContent = next; },
    destroy() {
      hide();
      node.removeEventListener("pointerenter", show);
      node.removeEventListener("pointerleave", hide);
      node.removeEventListener("pointerdown", hide);
    },
  };
}
