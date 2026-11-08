<script lang="ts">
  // The map of subjects: every entry a point, placed by its title's meaning (bhb topicmap), with named regions at
  // three levels, a search that lights up its hits, and filters by subject area, period and year of publication.
  // The points are drawn with WebGL (regl-scatterplot); the names, the tooltip and the panel are HTML on top.
  import { onDestroy, onMount, untrack } from "svelte";
  import { scaleLinear } from "d3-scale";
  import createScatterplot from "regl-scatterplot";
  import Waiting from "./Waiting.svelte";
  import { installGestures } from "./lib/gestures";
  import { PERIODS, THEMES, YEAR_BASE, decodePoints, matchQuery, shardOf, tokens, type CellTitle, type Points, type Region } from "./lib/topics";

  type Lang = "nl" | "fr" | "en";
  type Text = Record<string, any>;
  let { text, lang, initial }: { text: Text; lang: Lang; initial: URLSearchParams } = $props();

  const base = import.meta.env.BASE_URL;
  const url = (path: string) => new URL(`${base}topics/${path}`, document.baseURI).href;
  // Point states, the scatterplot's first value: shown, dimmed (outside the filters), lit (a search hit).
  const SHOWN = 0;
  const DIM = 1;
  const LIT = 2;
  const COLORS = ["#3f5a44", "#b9bfba", "#c4622d"];
  const OPACITY = [0.15, 0.065, 0.95];

  let frame: HTMLDivElement;
  let removeGestures: (() => void) | null = null;
  let canvas: HTMLCanvasElement;
  let plot = $state.raw<ReturnType<typeof createScatterplot> | null>(null);
  // Plain state: the columns are read 180,000 times per filter change, and a deep proxy would slow every read.
  let points = $state.raw<Points | null>(null);
  let regions = $state.raw<Region[]>([]);
  let failed = $state(false);
  // Set once the points are first drawn: until then the hourglass shows.
  let drawn = $state(false);
  let width = $state(0);
  let height = $state(0);
  // Pixels per unit of the map and its offset, from the scatterplot's view: [scaleX, offsetX, scaleY, offsetY].
  let view = $state<[number, number, number, number]>([0, 0, 0, 0]);

  // The view as the address gave it when the page opened; afterwards the page keeps the address up to date.
  const start = untrack(() => new URLSearchParams(initial));
  let query = $state(start.get("q") || "");
  let theme = $state(THEMES.indexOf((start.get("theme") || "") as (typeof THEMES)[number]));
  let period = $state(PERIODS.indexOf((start.get("period") || "") as (typeof PERIODS)[number]));
  let yearFrom = $state(Number(start.get("from")) || 0);
  let yearTo = $state(Number(start.get("to")) || 0);
  let hits = $state<Set<number> | null>(null);
  let searching = $state(false);
  let hover = $state<{ index: number; x: number; y: number } | null>(null);
  let chosen = $state<{ kind: "region"; id: string } | { kind: "point"; index: number } | null>(null);
  let playing = $state(false);
  let playTimer: ReturnType<typeof setInterval> | null = null;

  const cells = new Map<number, CellTitle[]>();
  let cellVersion = $state(0);
  const shards = new Map<string, Record<string, number[]>>();

  let byId = $derived(new Map(regions.map((region) => [region.id, region])));
  let finest = $derived(regions.length ? Math.max(...regions.map((region) => region.level)) : 3);
  let children = $derived.by(() => {
    const out = new Map<string, Region[]>();
    for (const region of regions) if (region.parent) (out.get(region.parent) || out.set(region.parent, []).get(region.parent)!).push(region);
    for (const list of out.values()) list.sort((a, b) => b.n - a.n);
    return out;
  });
  // Each finest cell's chain of regions, coarsest first, and every region's bounding box on the map.
  let chains = $derived.by(() => {
    const out = new Map<string, string[]>();
    for (const region of regions) {
      const path: string[] = [];
      for (let at: Region | undefined = region; at; at = at.parent ? byId.get(at.parent) : undefined) path.unshift(at.id);
      out.set(region.id, path);
    }
    return out;
  });
  let boxes = $derived.by(() => {
    const out = new Map<string, [number, number, number, number]>();
    if (!points) return out;
    for (let i = 0; i < points.n; i += 1) {
      for (const id of chains.get(`r${finest}.${points.cell[i]}`) || []) {
        const box = out.get(id);
        if (!box) out.set(id, [points.x[i], points.y[i], points.x[i], points.y[i]]);
        else {
          if (points.x[i] < box[0]) box[0] = points.x[i];
          if (points.y[i] < box[1]) box[1] = points.y[i];
          if (points.x[i] > box[2]) box[2] = points.x[i];
          if (points.y[i] > box[3]) box[3] = points.y[i];
        }
      }
    }
    return out;
  });

  /** Whether point i passes the subject, period and year filters. */
  function passes(i: number): boolean {
    if (!points) return false;
    if (theme >= 0 && !(points.theme[i] & (1 << theme))) return false;
    if (period >= 0 && !(points.period[i] & (1 << period))) return false;
    const year = points.year[i] ? points.year[i] + YEAR_BASE : 0;
    if (yearFrom && (!year || year < yearFrom)) return false;
    if (yearTo && (!year || year > yearTo)) return false;
    return true;
  }

  let states = $derived.by(() => {
    const out = new Float32Array(points?.n || 0);
    if (!points) return out;
    for (let i = 0; i < points.n; i += 1) {
      const kept = passes(i);
      out[i] = !kept ? DIM : hits ? (hits.has(i) ? LIT : DIM) : SHOWN;
    }
    return out;
  });
  let shownCount = $derived.by(() => {
    let count = 0;
    for (let i = 0; i < states.length; i += 1) if (states[i] !== DIM) count += 1;
    return count;
  });
  // Publications per year (from 1945), all and those the filters and search keep, for the timeline.
  const FIRST_YEAR = 1945;
  const LAST_YEAR = new Date().getFullYear();
  let histogram = $derived.by(() => {
    const all = new Array(LAST_YEAR - FIRST_YEAR + 1).fill(0);
    const kept = new Array(LAST_YEAR - FIRST_YEAR + 1).fill(0);
    if (!points) return { all, kept, max: 1 };
    for (let i = 0; i < points.n; i += 1) {
      const year = points.year[i] + YEAR_BASE;
      if (!points.year[i] || year < FIRST_YEAR || year > LAST_YEAR) continue;
      all[year - FIRST_YEAR] += 1;
      const themeOk = theme < 0 || points.theme[i] & (1 << theme);
      const periodOk = period < 0 || points.period[i] & (1 << period);
      if (themeOk && periodOk && (!hits || hits.has(i))) kept[year - FIRST_YEAR] += 1;
    }
    return { all, kept, max: Math.max(1, ...all) };
  });

  onMount(async () => {
    try {
      const [buffer, list] = await Promise.all([
        fetch(url("points.bin")).then((response) => response.arrayBuffer()),
        fetch(url("regions.json")).then((response) => response.json()),
      ]);
      points = decodePoints(buffer);
      regions = list;
    } catch {
      failed = true;
      return;
    }
    fitFrame();
    const box = frame.getBoundingClientRect();
    width = box.width;
    height = box.height;
    plot = createScatterplot({
      canvas,
      width: "auto",
      height: "auto",
      backgroundColor: "#f7f6f1",
      pointSize: [1.9, 1.5, 4.5],
      pointSizeSelected: 6,
      pointOutlineWidth: 1.5,
      pointColorActive: "#8b3d14",
      pointColorHover: "#8b3d14",
      pointScaleMode: "asinh",
      colorBy: "valueA",
      opacityBy: "valueA",
      sizeBy: "valueA",
      pointColor: COLORS,
      opacity: OPACITY,
      xScale: scaleLinear().domain([0, 1]).range([0, width]),
      yScale: scaleLinear().domain([0, 1]).range([height, 0]),
      actionKeyMap: {},
      lassoInitiator: false,
      deselectOnEscape: true,
      deselectOnDblClick: false,
    } as any);
    plot.subscribe("view", ({ xScale, yScale }: any) => onView(xScale, yScale));
    plot.subscribe("pointOver", (index: number) => onPointOver(index));
    plot.subscribe("pointOut", () => { hover = null; });
    plot.subscribe("select", ({ points: picked }: { points: number[] }) => {
      if (picked.length) chosen = { kind: "point", index: picked[0] };
    });
    await redraw();
    fitAll(false);
    drawn = true;
    if (query) void runSearch(query);
    const region = start.get("region");
    if (region && byId.has(region)) openRegion(region);
    addEventListener("resize", onResize);
    removeGestures = installGestures(canvas, frame);
  });

  onDestroy(() => {
    left = true;
    stopPlay();
    removeEventListener("resize", onResize);
    removeGestures?.();
    plot?.destroy();
  });

  // Redraw when the states change (filters, search), keeping the camera; one draw at a time, the last one wins.
  let drawing: Promise<void> | null = null;
  let again = false;
  async function redraw() {
    if (!plot || !points) return;
    if (drawing) {
      again = true;
      return drawing;
    }
    drawing = plot.draw({ x: xs(), y: ys(), valueA: states } as any, { zDataType: "categorical", preventFilterReset: true } as any);
    await drawing;
    drawing = null;
    if (again) {
      again = false;
      await redraw();
    }
  }
  $effect(() => {
    states;
    void redraw();
  });
  // Fewer points shown (a decade, a subject area) are drawn stronger, so they read as clearly as the whole map.
  $effect(() => {
    if (!plot || !points || hits) return;
    const share = Math.max(shownCount, 1) / points.n;
    const strength = Math.min(0.45, OPACITY[SHOWN] / Math.sqrt(share) * 0.75);
    plot.set({ opacity: [strength, OPACITY[DIM], OPACITY[LIT]], pointSize: [Math.min(2.6, 1.9 / Math.sqrt(Math.sqrt(share))), 1.5, 4.5] } as any);
  });
  let xsCache: Float32Array | null = null;
  let ysCache: Float32Array | null = null;
  function xs() {
    if (!xsCache && points) xsCache = points.x.map((value) => value * 2 - 1);
    return xsCache!;
  }
  function ys() {
    if (!ysCache && points) ysCache = points.y.map((value) => value * 2 - 1);
    return ysCache!;
  }

  /** The map fills the window below the page head, with the line of help under it in view. */
  function fitFrame() {
    const top = frame.getBoundingClientRect().top + scrollY;
    frame.style.height = `${Math.max(540, innerHeight - top - 34)}px`;
  }

  function onResize() {
    fitFrame();
    const box = frame.getBoundingClientRect();
    width = box.width;
    height = box.height;
    plot?.set({ xScale: scaleLinear().domain([0, 1]).range([0, width]), yScale: scaleLinear().domain([0, 1]).range([height, 0]) } as any);
  }

  let viewFrame = 0;
  function onView(xScale: any, yScale: any) {
    if (viewFrame) return;
    viewFrame = requestAnimationFrame(() => {
      viewFrame = 0;
      const x0 = xScale(0);
      const y0 = yScale(0);
      view = [xScale(1) - x0, x0, yScale(1) - y0, y0];
    });
  }

  const screenX = (x: number) => view[1] + x * view[0];
  const screenY = (y: number) => view[3] + y * view[2];

  // Where the bulk of the map lies: the 1st to 99th percentile of the points on each axis, so the first view is
  // filled by the publications and not by a few strays at the edges.
  let bulk = $derived.by(() => {
    if (!points) return [0, 0, 1, 1];
    const cut = (values: Float32Array) => {
      const sorted = Float32Array.from(values).sort();
      return [sorted[Math.floor(sorted.length * 0.01)], sorted[Math.floor(sorted.length * 0.99)]];
    };
    const [x0, x1] = cut(points.x);
    const [y0, y1] = cut(points.y);
    return [x0, y0, x1, y1];
  });

  function fitAll(transition = true) {
    // Room at the bottom for the timeline and at the top for the search box.
    const [x0, y0, x1, y1] = bulk;
    const w = (x1 - x0) * 2;
    const h = (y1 - y0) * 2;
    plot?.zoomToArea(
      { x: x0 * 2 - 1 - w * 0.04, y: y0 * 2 - 1 - h * 0.16, width: w * 1.08, height: h * 1.26 },
      { transition, transitionDuration: 600 } as any,
    );
  }

  function zoomToRegion(id: string) {
    const box = boxes.get(id);
    if (!box || !plot) return;
    const pad = Math.max(box[2] - box[0], box[3] - box[1]) * 0.12 + 0.01;
    plot.zoomToArea(
      { x: (box[0] - pad) * 2 - 1, y: (box[1] - pad) * 2 - 1, width: (box[2] - box[0] + 2 * pad) * 2, height: (box[3] - box[1] + 2 * pad) * 2 },
      { transition: true, transitionDuration: 700 } as any,
    );
  }

  function zoomBy(factor: number) {
    const camera = (plot as any)?.get("camera");
    if (!camera) return;
    const [cx, cy] = camera.target;
    const distance = camera.distance[0] / factor;
    (plot as any).zoomToLocation([cx, cy], distance, { transition: true, transitionDuration: 300 });
  }

  // The names on the map: the finest level whose regions have room on screen, with the level above as larger,
  // fainter names behind it; overlapping names give way to the bigger region.
  const FONT = [0, 19, 15, 12.5];
  let labels = $derived.by(() => {
    if (!regions.length || !view[0] || !width) return [];
    const scale = Math.abs(view[0]);
    const levels = [1, 2, 3].filter((level) => level <= finest);
    const spacing = (level: number) => scale / Math.sqrt(regions.filter((region) => region.level === level).length);
    let primary = levels[0];
    for (const level of levels) if (spacing(level) >= 120) primary = level;
    const shown: { region: Region; x: number; y: number; size: number; faint: boolean; w: number; h: number }[] = [];
    const taken: [number, number, number, number][] = [];
    const candidates = regions
      .filter((region) => region.name && (region.level === primary || region.level === primary - 1))
      .sort((a, b) => a.level - b.level || b.n - a.n);
    for (const region of candidates) {
      const x = screenX(region.x);
      const y = screenY(region.y);
      if (x < -50 || y < -20 || x > width + 50 || y > height + 20) continue;
      const faint = region.level < primary;
      const size = faint ? FONT[region.level] + 3 : FONT[region.level];
      const name = region.name![lang];
      const w = Math.min(name.length, 26) * size * (faint ? 0.62 : 0.56) + 8;
      const h = size * (name.length > 26 ? 2.5 : 1.35);
      const rect: [number, number, number, number] = [x - w / 2, y - h / 2, x + w / 2, y + h / 2];
      if (!faint && taken.some((other) => rect[0] < other[2] && rect[2] > other[0] && rect[1] < other[3] && rect[3] > other[1])) continue;
      if (!faint) taken.push(rect);
      shown.push({ region, x, y, size, faint, w, h });
    }
    return shown;
  });

  async function onPointOver(index: number) {
    if (!points) return;
    const x = screenX(points.x[index]);
    const y = screenY(points.y[index]);
    hover = { index, x, y };
    await loadCell(points.cell[index]);
  }

  async function loadCell(cell: number) {
    if (cells.has(cell)) return;
    cells.set(cell, []);
    try {
      cells.set(cell, await fetch(url(`cells/${cell}.json`)).then((response) => response.json()));
    } catch {
      cells.delete(cell);
    }
    cellVersion += 1;
  }

  function titleOf(index: number): CellTitle | undefined {
    cellVersion;
    if (!points) return undefined;
    return cells.get(points.cell[index])?.find((row) => row[0] === index);
  }

  /** The title's machine translation into the reader's language, when the title is in another. */
  function translationOf(row: CellTitle): string {
    const translated = { nl: row[5], fr: row[6], en: row[7] }[lang];
    return translated && translated.toLowerCase() !== row[2].toLowerCase() ? translated : "";
  }

  let searchTimer: ReturnType<typeof setTimeout> | null = null;
  function onQuery() {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => void runSearch(query), 220);
  }

  async function runSearch(value: string) {
    const words = tokens(value);
    if (!words.length) {
      hits = null;
      remember();
      return;
    }
    searching = true;
    const needed = [...new Set(words.map(shardOf))].filter((shard) => !shards.has(shard));
    await Promise.all(needed.map(async (shard) => {
      try {
        shards.set(shard, await fetch(url(`words/${shard}.json`)).then((response) => (response.ok ? response.json() : {})));
      } catch {
        shards.set(shard, {});
      }
    }));
    if (value !== query) return;
    hits = matchQuery(value, shards);
    searching = false;
    remember();
  }

  function clearSearch() {
    query = "";
    hits = null;
    remember();
  }

  /** Zoom to where most hits are: the 80 % nearest their median point, so a few strays elsewhere do not count. */
  function zoomToHits() {
    if (!plot || !points || !hits?.size) return;
    const kept = [...hits].filter((i) => passes(i));
    if (!kept.length) return;
    const median = (values: number[]) => values.sort((a, b) => a - b)[Math.floor(values.length / 2)];
    const mx = median(kept.map((i) => points!.x[i]));
    const my = median(kept.map((i) => points!.y[i]));
    const near = kept
      .map((i) => [i, (points!.x[i] - mx) ** 2 + (points!.y[i] - my) ** 2] as [number, number])
      .sort((a, b) => a[1] - b[1])
      .slice(0, Math.max(1, Math.ceil(kept.length * 0.8)))
      .map(([i]) => i);
    (plot as any).zoomToPoints(near, { padding: 0.25, transition: true, transitionDuration: 700 });
  }

  function openRegion(id: string) {
    chosen = { kind: "region", id };
    zoomToRegion(id);
    const region = byId.get(id);
    if (region?.level === finest) void loadCell(Number(id.split(".")[1]));
    remember();
  }

  function closePanel() {
    chosen = null;
    plot?.deselect();
    remember();
  }

  // Set when the reader leaves the page: from then on the page must not write its address over the next one's.
  let left = false;

  /** The address of this view, kept in the page's hash without a new history entry. */
  function remember() {
    if (left || !location.hash.startsWith("#/topics")) return;
    const next = new URLSearchParams();
    if (query.trim()) next.set("q", query.trim());
    if (theme >= 0) next.set("theme", THEMES[theme]);
    if (period >= 0) next.set("period", PERIODS[period]);
    if (yearFrom) next.set("from", String(yearFrom));
    if (yearTo) next.set("to", String(yearTo));
    if (chosen?.kind === "region") next.set("region", chosen.id);
    const hash = `#/topics${next.size ? `?${next}` : ""}`;
    if (location.hash !== hash) history.replaceState(null, "", hash);
  }

  // The timeline: drag across it to choose years, click a year to clear, or play the decades one after the other.
  let brushStart: number | null = null;
  function yearAt(event: PointerEvent, element: HTMLElement): number {
    const box = element.getBoundingClientRect();
    const share = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
    return FIRST_YEAR + Math.round(share * (LAST_YEAR - FIRST_YEAR));
  }
  function onBrushDown(event: PointerEvent) {
    stopPlay();
    const element = event.currentTarget as HTMLElement;
    element.setPointerCapture(event.pointerId);
    brushStart = yearAt(event, element);
    yearFrom = brushStart;
    yearTo = brushStart;
  }
  function onBrushMove(event: PointerEvent) {
    if (brushStart === null) return;
    const year = yearAt(event, event.currentTarget as HTMLElement);
    yearFrom = Math.min(brushStart, year);
    yearTo = Math.max(brushStart, year);
  }
  function onBrushUp() {
    if (brushStart === null) return;
    brushStart = null;
    if (yearFrom === yearTo) {
      yearFrom = 0;
      yearTo = 0;
    }
    remember();
  }
  function clearYears() {
    stopPlay();
    yearFrom = 0;
    yearTo = 0;
    remember();
  }
  function togglePlay() {
    if (playing) return stopPlay();
    playing = true;
    let start = yearFrom && yearTo && yearTo - yearFrom === 9 ? yearFrom + 10 : Math.floor(FIRST_YEAR / 10) * 10;
    const step = () => {
      if (start > LAST_YEAR) return stopPlay();
      yearFrom = Math.max(FIRST_YEAR, start);
      yearTo = Math.min(LAST_YEAR, start + 9);
      start += 10;
    };
    step();
    playTimer = setInterval(step, 1400);
  }
  function stopPlay() {
    playing = false;
    if (playTimer) clearInterval(playTimer);
    playTimer = null;
    remember();
  }

  function onKey(event: KeyboardEvent) {
    const target = event.target as HTMLElement;
    if (target.tagName === "INPUT" || target.tagName === "SELECT") return;
    if (event.key === "+" || event.key === "=") zoomBy(1.6);
    else if (event.key === "-") zoomBy(1 / 1.6);
    else if (event.key === "0") fitAll();
    else if (event.key === "Escape") closePanel();
  }

  function name(id: string): string {
    return byId.get(id)?.name?.[lang] || "…";
  }

  /** Points of a region that the filters and search keep, and its publications per decade. */
  function regionStats(id: string) {
    const decades = new Map<number, [number, number]>();
    let kept = 0;
    let total = 0;
    if (!points) return { kept, total, decades: [] as [number, number, number][] };
    const cellsOf = new Set(regions.filter((region) => region.level === finest && chains.get(region.id)?.includes(id)).map((region) => Number(region.id.split(".")[1])));
    for (let i = 0; i < points.n; i += 1) {
      if (!cellsOf.has(points.cell[i])) continue;
      total += 1;
      const on = states[i] !== DIM;
      if (on) kept += 1;
      const year = points.year[i] + YEAR_BASE;
      if (points.year[i] && year >= FIRST_YEAR) {
        const decade = Math.floor(year / 10) * 10;
        const entry = decades.get(decade) || [0, 0];
        entry[0] += 1;
        if (on) entry[1] += 1;
        decades.set(decade, entry);
      }
    }
    return { kept, total, decades: [...decades].sort((a, b) => a[0] - b[0]).map(([decade, [all, on]]) => [decade, all, on] as [number, number, number]) };
  }

  let panelStats = $derived(chosen?.kind === "region" ? regionStats(chosen.id) : null);
  // Where the search hits lie: the regions one level below the top with the most hits.
  let hitRegions = $derived.by(() => {
    if (!hits || !points || !regions.length) return [];
    const level = Math.min(2, finest);
    const counts = new Map<string, number>();
    for (const i of hits) {
      if (states[i] !== LIT) continue;
      const id = chains.get(`r${finest}.${points.cell[i]}`)?.[level - 1];
      if (id) counts.set(id, (counts.get(id) || 0) + 1);
    }
    return [...counts].sort((a, b) => b[1] - a[1]).slice(0, 5);
  });
  let pointRow = $derived(chosen?.kind === "point" ? titleOf(chosen.index) : undefined);
  $effect(() => {
    if (chosen?.kind === "point" && points) void loadCell(points.cell[chosen.index]);
  });
  let cellTitles = $derived.by(() => {
    cellVersion;
    if (chosen?.kind !== "region" || byId.get(chosen.id)?.level !== finest || !points) return [];
    const rows = cells.get(Number(chosen.id.split(".")[1])) || [];
    return rows.filter((row) => states[row[0]] !== DIM).sort((a, b) => (b[4] || "").localeCompare(a[4] || ""));
  });
</script>

<svelte:window onkeydown={onKey} />

<main class="topics-page">
  <div class="topics-head">
    <h1>{text.topics}</h1>
    <p>{text.topicsIntro}</p>
  </div>
  <div class="topics-frame" bind:this={frame}>
    <canvas bind:this={canvas} class="topics-canvas" aria-label={text.topics}></canvas>
    {#if failed}
      <p class="topics-status">{text.topicsFailed}</p>
    {:else if !drawn}
      <div class="topics-status"><Waiting message={text.topicsLoading} large /></div>
    {/if}

    <div class="topics-labels" aria-hidden="false">
      {#each labels as label (label.region.id)}
        <button
          type="button"
          class="topics-label level-{label.region.level}"
          class:faint={label.faint}
          class:chosen={chosen?.kind === "region" && chosen.id === label.region.id}
          style="left: {label.x}px; top: {label.y}px; font-size: {label.size}px; max-width: {label.faint ? 18 : 14}em;"
          onclick={() => openRegion(label.region.id)}
        >{label.region.name?.[lang]}</button>
      {/each}
    </div>

    <form class="topics-search" role="search" onsubmit={(event) => { event.preventDefault(); void runSearch(query).then(zoomToHits); }}>
      <input type="search" bind:value={query} oninput={onQuery} placeholder={text.topicsSearch} aria-label={text.topicsSearch} />
      {#if hits}
        <p class="topics-hits">
          {text.topicsHits.replace("{n}", shownCount.toLocaleString(lang))}
          {#if shownCount}<button type="button" onclick={zoomToHits}>{text.topicsZoomHits}</button>{/if}
          <button type="button" onclick={clearSearch} aria-label={text.topicsClear}>×</button>
        </p>
        {#if hitRegions.length && !chosen}
          <ol class="topics-where">
            {#each hitRegions as [id, count] (id)}
              <li><button type="button" onclick={() => openRegion(id)}>{name(id)}</button> <span class="tree-count">{count.toLocaleString(lang)}</span></li>
            {/each}
          </ol>
        {/if}
      {:else if searching}
        <p class="topics-hits">…</p>
      {/if}
    </form>

    <div class="map-zoom topics-zoom">
      <button type="button" aria-label={text.zoomIn} title={text.zoomIn} onclick={() => zoomBy(1.6)}>+</button>
      <button type="button" aria-label={text.zoomOut} title={text.zoomOut} onclick={() => zoomBy(1 / 1.6)}>−</button>
      <button type="button" aria-label={text.zoomReset} title={text.zoomReset} onclick={() => fitAll()}>⟲</button>
    </div>

    {#if hover}
      {@const row = titleOf(hover.index)}
      <div class="topics-tip" style="left: {Math.min(hover.x + 14, width - 330)}px; top: {Math.max(8, hover.y - 12)}px;">
        {#if row}
          <strong>{row[2]}</strong>
          {#if translationOf(row)}<span class="topics-tip-tr">{translationOf(row)}</span>{/if}
          <span class="topics-tip-by">{[row[3], row[4]].filter(Boolean).join(" · ")}</span>
        {:else}
          <span class="topics-tip-by">…</span>
        {/if}
      </div>
    {/if}

    <div class="topics-bottom">
      <div class="topics-filters">
        <select bind:value={theme} onchange={remember} aria-label={text.subjects}>
          <option value={-1}>{text.topicsAllSubjects}</option>
          {#each THEMES as value, index}<option value={index}>{text.themes[value] || value}</option>{/each}
        </select>
        <select bind:value={period} onchange={remember} aria-label={text.periodsLabel}>
          <option value={-1}>{text.topicsAllPeriods}</option>
          {#each PERIODS as value, index}<option value={index}>{text.periods[value] || value}</option>{/each}
        </select>
      </div>
      <div class="topics-time">
        <button type="button" class="topics-play" onclick={togglePlay} aria-label={playing ? text.topicsPause : text.topicsPlay} title={playing ? text.topicsPause : text.topicsPlay}>
          {#if playing}
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><rect x="3" y="2" width="3.5" height="12" /><rect x="9.5" y="2" width="3.5" height="12" /></svg>
          {:else}
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 2l10 6-10 6z" /></svg>
          {/if}
        </button>
        <div
          class="topics-histogram"
          role="slider"
          tabindex="0"
          aria-label={text.topicsYears}
          aria-valuemin={FIRST_YEAR}
          aria-valuemax={LAST_YEAR}
          aria-valuenow={yearFrom || FIRST_YEAR}
          aria-valuetext={yearFrom ? `${yearFrom}–${yearTo}` : text.topicsAllYears}
          onpointerdown={onBrushDown}
          onpointermove={onBrushMove}
          onpointerup={onBrushUp}
        >
          <svg viewBox="0 0 {histogram.all.length} 40" preserveAspectRatio="none" aria-hidden="true">
            {#each histogram.all as count, index}
              {@const year = FIRST_YEAR + index}
              {@const inside = !yearFrom || (year >= yearFrom && year <= yearTo)}
              <rect x={index + 0.1} width="0.8" y={40 - (count / histogram.max) * 40} height={(count / histogram.max) * 40} class="bar-all" />
              <rect x={index + 0.1} width="0.8" y={40 - (histogram.kept[index] / histogram.max) * 40} height={(histogram.kept[index] / histogram.max) * 40} class:bar-on={inside} class:bar-off={!inside} />
            {/each}
          </svg>
          <div class="topics-axis" aria-hidden="true">
            {#each [1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020] as tick}
              <span class:minor={tick % 20 !== 10} style="left: {((tick - FIRST_YEAR) / (LAST_YEAR - FIRST_YEAR)) * 100}%">{tick}</span>
            {/each}
          </div>
        </div>
        <span class="topics-range">
          {#if yearFrom}{yearFrom}–{yearTo} <button type="button" onclick={clearYears} aria-label={text.topicsAllYears}>×</button>{:else}{text.topicsAllYears}{/if}
        </span>
      </div>
    </div>

    {#if chosen}
      <aside class="topics-panel">
        <button type="button" class="topics-close" onclick={closePanel} aria-label={text.topicsClose}>×</button>
        {#if chosen.kind === "region"}
          {@const region = byId.get(chosen.id)}
          {#if region}
            <nav class="topics-crumbs">
              {#each (chains.get(region.id) || []).slice(0, -1) as id}
                <button type="button" onclick={() => openRegion(id)}>{name(id)}</button><span aria-hidden="true">›</span>
              {/each}
            </nav>
            <h2>{name(region.id)}</h2>
            {#if panelStats}
              <p class="topics-count">
                {#if panelStats.kept !== panelStats.total}
                  {text.topicsMatching.replace("{m}", panelStats.kept.toLocaleString(lang)).replace("{n}", panelStats.total.toLocaleString(lang))}
                {:else}
                  {text.topicsHits.replace("{n}", panelStats.total.toLocaleString(lang))}
                {/if}
              </p>
              <svg class="topics-decades" viewBox="0 0 {panelStats.decades.length * 10} 34" aria-hidden="true">
                {#each panelStats.decades as [decade, all, on], index}
                  {@const top = Math.max(...panelStats.decades.map((entry) => entry[1]))}
                  <rect x={index * 10 + 1} width="8" y={30 - (all / top) * 28} height={(all / top) * 28} class="bar-all" />
                  <rect x={index * 10 + 1} width="8" y={30 - (on / top) * 28} height={(on / top) * 28} class="bar-on" />
                {/each}
              </svg>
              <p class="topics-decade-axis"><span>{panelStats.decades[0]?.[0] || ""}</span><span>{panelStats.decades.at(-1)?.[0] || ""}</span></p>
            {/if}
            <p><a class="topics-search-link" href={`#/search?topic=${encodeURIComponent(region.id)}${query.trim() ? `&q=${encodeURIComponent(query.trim())}` : ""}`}>{text.topicsShowInSearch}</a></p>
            {#if children.get(region.id)?.length}
              <h3>{text.topicsParts}</h3>
              <ul class="topics-parts">
                {#each children.get(region.id) || [] as part (part.id)}
                  <li><button type="button" onclick={() => openRegion(part.id)}>{name(part.id)}</button> <span class="tree-count">{part.n.toLocaleString(lang)}</span></li>
                {/each}
              </ul>
            {:else}
              <h3>{text.topicsTitles}</h3>
              <ul class="topics-titles">
                {#each cellTitles.slice(0, 200) as row (row[0])}
                  <li><a href={`#/record/${encodeURIComponent(row[1])}`}>{row[2]}</a> <span class="topics-tip-by">{[row[3], row[4]].filter(Boolean).join(" · ")}</span></li>
                {/each}
              </ul>
            {/if}
            <p class="topics-note">{text.topicsNamesNote}</p>
          {/if}
        {:else if pointRow}
          {@const cell = points ? `r${finest}.${points.cell[chosen.index]}` : ""}
          <nav class="topics-crumbs">
            {#each chains.get(cell) || [] as id}
              <button type="button" onclick={() => openRegion(id)}>{name(id)}</button><span aria-hidden="true">›</span>
            {/each}
          </nav>
          <h2 class="topics-point-title">{pointRow[2]}</h2>
          {#if translationOf(pointRow)}<p class="topics-tip-tr"><span class="derived" title={text.topicsTranslated}>{translationOf(pointRow)}</span></p>{/if}
          <p class="topics-tip-by">{[pointRow[3], pointRow[4]].filter(Boolean).join(" · ")}</p>
          <p class="topics-actions">
            <a href={`#/record/${encodeURIComponent(pointRow[1])}`}>{text.topicsOpen}</a>
            <a href={`#/similar/${encodeURIComponent(pointRow[1])}`}>{text.topicsSimilar}</a>
          </p>
        {:else}
          <p class="topics-tip-by">…</p>
        {/if}
      </aside>
    {/if}
  </div>
  <p class="topics-help">{text.topicsHelp}</p>
</main>
