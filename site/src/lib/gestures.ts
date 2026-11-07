// Gestures for the map of subjects. Its camera (dom-2d-camera, inside regl-scatterplot) listens to the mouse and
// the wheel only, and turns a wheel step of d pixels into a zoom of exp(d / height): a trackpad pinch, which comes
// as many small wheel steps with the Ctrl key, then zooms very slowly; Safari sends a pinch as gesture events,
// which the camera does not hear, and a touch screen sends touch events, which it does not hear either. These
// handlers turn all of them into the camera's own wheel and mouse events.

/** Wheel steps from a pinch are this much larger; plain wheel and two-finger scrolling a little larger. */
const PINCH_BOOST = 6;
const WHEEL_BOOST = 1.8;

/** Parts of the map frame that keep their own wheel and touch: the panel scrolls, the controls are controls. */
const OWN = ".topics-panel, .topics-search, .topics-bottom, .topics-zoom";

/** Gestures anywhere over ``area`` (the map's frame, names included) move the map drawn on ``canvas``. */
export function installGestures(canvas: HTMLCanvasElement, area: HTMLElement): () => void {
  const own = (event: Event) => (event.target as Element | null)?.closest?.(OWN) !== null;
  // A name on the map is a button: one finger on it taps it, two fingers pinch the map.
  const onName = (event: Event) => (event.target as Element | null)?.closest?.(".topics-label") !== null;
  const ours = new WeakSet<Event>();
  // The camera reads the pointer from offsetX and offsetY, which a browser does not set relative to the canvas for
  // an event made in code; they are set here, or the zoom would centre on the wrong point.
  const send = (event: MouseEvent) => {
    const box = canvas.getBoundingClientRect();
    Object.defineProperty(event, "offsetX", { value: event.clientX - box.left });
    Object.defineProperty(event, "offsetY", { value: event.clientY - box.top });
    ours.add(event);
    canvas.dispatchEvent(event);
  };
  /** A wheel step that zooms by ``ratio`` (above 1: in) around a point of the page. */
  const zoom = (ratio: number, x: number, y: number) => {
    if (!ratio || !Number.isFinite(ratio)) return;
    const deltaY = -canvas.clientHeight * Math.log(ratio);
    send(new WheelEvent("wheel", { deltaY, clientX: x, clientY: y, bubbles: true, cancelable: true }));
  };
  const mouse = (type: string, x: number, y: number, pressed = type !== "mouseup") =>
    send(new MouseEvent(type, { clientX: x, clientY: y, button: 0, buttons: pressed ? 1 : 0, bubbles: true, cancelable: true }));

  const onWheel = (event: WheelEvent) => {
    if (ours.has(event) || own(event)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const boost = event.ctrlKey ? PINCH_BOOST : WHEEL_BOOST;
    const lines = event.deltaMode === 1 ? 12 : 1;
    send(new WheelEvent("wheel", {
      deltaY: (event.deltaY || event.deltaX) * lines * boost, clientX: event.clientX, clientY: event.clientY, bubbles: true, cancelable: true,
    }));
  };

  // Safari: gesturechange carries the pinch's scale since it began.
  let gestureScale = 1;
  const onGestureStart = (event: Event) => {
    if (own(event)) return;
    event.preventDefault();
    gestureScale = 1;
  };
  const onGestureChange = (event: Event) => {
    if (own(event)) return;
    event.preventDefault();
    const { scale, clientX, clientY } = event as Event & { scale: number; clientX: number; clientY: number };
    zoom(scale / gestureScale, clientX, clientY);
    gestureScale = scale;
  };

  // Touch: one finger drags (and a tap is a click), two fingers pinch around their midpoint.
  let one: { x: number; y: number } | null = null;
  let pressed = false;
  let two: { distance: number } | null = null;
  const spread = (touches: TouchList) => Math.hypot(touches[0].clientX - touches[1].clientX, touches[0].clientY - touches[1].clientY);
  const press = () => {
    if (!one || pressed) return;
    pressed = true;
    mouse("mousedown", one.x, one.y);
  };
  const release = () => {
    if (one && pressed) mouse("mouseup", one.x, one.y);
    pressed = false;
  };
  const onTouchStart = (event: TouchEvent) => {
    if (own(event) || (onName(event) && event.touches.length === 1)) return;
    event.preventDefault();
    if (event.touches.length === 1) {
      // The camera pans by the pointer's move since its last frame: it must first see the finger where it lands,
      // a frame before the press, or the map jumps from wherever the pointer was last.
      one = { x: event.touches[0].clientX, y: event.touches[0].clientY };
      mouse("mousemove", one.x, one.y, false);
      requestAnimationFrame(() => requestAnimationFrame(press));
    } else if (event.touches.length === 2) {
      release();
      one = null;
      two = { distance: spread(event.touches) };
    }
  };
  const onTouchMove = (event: TouchEvent) => {
    if (!one && !two) return;
    event.preventDefault();
    if (one && event.touches.length === 1) {
      one = { x: event.touches[0].clientX, y: event.touches[0].clientY };
      mouse("mousemove", one.x, one.y, pressed);
    } else if (two && event.touches.length === 2) {
      const distance = spread(event.touches);
      const x = (event.touches[0].clientX + event.touches[1].clientX) / 2;
      const y = (event.touches[0].clientY + event.touches[1].clientY) / 2;
      zoom(distance / two.distance, x, y);
      two.distance = distance;
    }
  };
  const onTouchEnd = (event: TouchEvent) => {
    if (!one && !two) return;
    event.preventDefault();
    if (one && !event.touches.length) {
      // A tap ends before the delayed press: press now, so the release and the click follow it.
      press();
      release();
      mouse("click", one.x, one.y, false);
    }
    if (event.touches.length < 2) two = null;
    if (!event.touches.length) one = null;
  };

  const options = { capture: true, passive: false } as const;
  area.addEventListener("wheel", onWheel, options);
  area.addEventListener("gesturestart", onGestureStart, options);
  area.addEventListener("gesturechange", onGestureChange, options);
  area.addEventListener("touchstart", onTouchStart, options);
  area.addEventListener("touchmove", onTouchMove, options);
  area.addEventListener("touchend", onTouchEnd, options);
  area.addEventListener("touchcancel", onTouchEnd, options);
  return () => {
    area.removeEventListener("wheel", onWheel, options);
    area.removeEventListener("gesturestart", onGestureStart, options);
    area.removeEventListener("gesturechange", onGestureChange, options);
    area.removeEventListener("touchstart", onTouchStart, options);
    area.removeEventListener("touchmove", onTouchMove, options);
    area.removeEventListener("touchend", onTouchEnd, options);
    area.removeEventListener("touchcancel", onTouchEnd, options);
  };
}
