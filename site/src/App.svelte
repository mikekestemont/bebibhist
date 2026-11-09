<script lang="ts">
  import { onMount } from "svelte";
  import en from "./i18n/en.json";
  import fr from "./i18n/fr.json";
  import nl from "./i18n/nl.json";
  import { EXPORT_CAP, saveExport, saveExports, type ExportKind } from "./lib/export";
  import { regionWord } from "./lib/topics";
  import { keyWord } from "./lib/words.js";
  import Waiting from "./Waiting.svelte";
  import { HOST_MISSING, escapeHtml, foundThroughTranslation, unknownWords, nothingFound, citationHtml, editorsBeforeHost, findRecord, loadEngine, relatedByMeaning, spellingSuggestions, yearFilter, relaxedQuery, searchBoth, searchQuery, similarOf, type Filters, type Hit, type SearchField } from "./lib/search";

  const asset = (file: string) => `${import.meta.env.BASE_URL}${file}`;

  type Lang = "fr" | "nl" | "en";
  const catalogs = { fr, nl, en };
  const groups = {
    period: ["general", "ancient", "medieval", "burgundian", "early-modern", "contemporary"],
    theme: ["reference", "general", "local", "political", "economic", "social", "religious", "cultural", "unclassified"],
    language: ["nl", "fr", "en", "de", "other"],
    type: ["article", "chapter", "book", "journal-issue", "other"],
    access: ["free"],
  } as const;

  let lang = $state<Lang>(initialLang());
  let text = $derived(catalogs[lang]);
  let query = $state("");
  let path = $state("/");
  let params = $state(new URLSearchParams());
  let loading = $state(true);
  let missing = $state(false);
  let total = $state(0);
  let hits = $state<Hit[]>([]);
  let record = $state<Hit | null>(null);
  let counts = $state<Record<string, Record<string, number>>>({});
  let engine: Awaited<ReturnType<typeof loadEngine>> | null = null;
  let scope = "";
  let exportOpen = $state("");
  let similarSource = $state<Hit | null>(null);
  let similarHits = $state<{ hit: Hit; score: number }[]>([]);
  let exporting = $state(false);
  let listed: { data: () => Promise<Hit> }[] = [];
  let yearCounts = $state<Record<string, number>>({});
  // Counts up with every search, so that a late year histogram from an earlier search is not shown.
  let yearTicket = 0;
  let fieldChoice = $state("all");
  let dragFrom = $state<number | null>(null);
  let dragTo = $state<number | null>(null);
  let openId = $state("");
  let withinBox = $state("");
  let filtersOpen = $state(false);
  let menuOpen = $state(false);
  let menuButton: HTMLButtonElement;
  let menuPanel: HTMLDivElement;
  // Places of the printed indexes (1993–2007), with names and coordinates from the gazetteer: places.json.
  type PlaceInfo = { fr: string; nl: string; de: string; en: string; level: string; lon: number | null; lat: number | null; n: number; p?: Record<string, number> };
  type MapPlace = PlaceInfo & { key: string };
  let placeInfo = $state<Record<string, PlaceInfo>>({});
  let placesLoading: Promise<void> | null = null;
  // The period chosen on the map (#/map?period=medieval): the counts of that period, and its historical layer.
  const MAP_PERIODS = ["ancient", "medieval", "burgundian", "early-modern", "contemporary"];
  let mapPeriod = $derived(path === "/map" && MAP_PERIODS.includes(params.get("period") || "") ? params.get("period")! : "");
  let mapLayerKind = $derived(params.get("layer") === "dioceses" ? "dioceses" : "territories");
  /** The places with their count in the chosen period (every entry when none is chosen), most frequent first. */
  function placesForMap(keep: (place: PlaceInfo) => boolean): MapPlace[] {
    return Object.entries(placeInfo)
      .filter(([, place]) => keep(place))
      .map(([key, place]) => ({ ...place, key, n: mapPeriod ? place.p?.[mapPeriod] || 0 : place.n }))
      .filter((place) => place.n > 0)
      .sort((a, b) => b.n - a.n);
  }
  let mapPlaces = $derived(placesForMap((place) => place.lon !== null && place.lat !== null && place.level !== "area"));
  let mapElsewhere = $derived(placesForMap((place) => place.lon === null || place.level === "area"));
  let mapHover = $state<MapPlace | null>(null);
  // The map of subjects (TopicMap.svelte), loaded with its WebGL library only when the page is first opened.
  let TopicMap = $state<any>(null);
  // Region names of the map of subjects, for the search's region filter chip.
  let topicNames = $state<Record<string, { nl: string; fr: string; en: string }>>({});
  let mapBase = $state<{ country: string; regions: string[]; arrondissements: string[]; credit: string } | null>(null);
  // Historical boundaries per period (public/map-periods.json): territories in one year, dioceses in one century.
  type MapShape = { d: string; fr?: string; nl?: string; en?: string; x?: number; y?: number };
  type MapLayer = { year: number; territories: MapShape[]; diocesesYear?: number; dioceses?: MapShape[] };
  let mapHistory = $state<{ layers: Record<string, MapLayer>; credit: { territories: string; dioceses: string } } | null>(null);
  let mapLayer = $derived(mapPeriod ? mapHistory?.layers[mapPeriod] : undefined);
  let mapShapes = $derived(mapLayer ? (mapLayerKind === "dioceses" && mapLayer.dioceses ? mapLayer.dioceses : mapLayer.territories) : []);
  const MAP_W = 800;
  const MAP_H = 669;
  // The visible part of the map, as an SVG viewBox; zooming shrinks it, dragging moves it.
  let view = $state({ x: 0, y: 0, w: MAP_W, h: MAP_H });
  let mapZoom = $derived(MAP_W / view.w);
  let dragStart: { x: number; y: number; view: { x: number; y: number; w: number; h: number }; moved: boolean } | null = null;

  /** The place names and coordinates, fetched once, when a page first needs them. */
  function loadPlaces(): Promise<void> {
    placesLoading ??= fetch(new URL(`${import.meta.env.BASE_URL}places.json`, document.baseURI).href)
      .then((response) => (response.ok ? response.json() : {}))
      .then((places: Record<string, PlaceInfo>) => {
        placeInfo = places;
      })
      .catch(() => {});
    return placesLoading;
  }

  async function loadMap() {
    if (mapBase) return;
    try {
      const [base, history] = await Promise.all([
        fetch(new URL(`${import.meta.env.BASE_URL}map-base.json`, document.baseURI).href).then((response) => response.json()),
        fetch(new URL(`${import.meta.env.BASE_URL}map-periods.json`, document.baseURI).href).then((response) => (response.ok ? response.json() : null)).catch(() => null),
        loadPlaces(),
      ]);
      mapBase = base;
      mapHistory = history;
    } catch {
      mapBase = null;
    }
  }

  function placeLabel(key: string, fallback = ""): string {
    const place = placeInfo[key];
    return (place ? place[lang] || place.nl || place.fr : "") || fallback || key.replace(/^(nis|name):/, "");
  }

  /** Zoom by ``factor`` around a point of the map (in map units), keeping that point under the cursor. */
  function zoomAt(factor: number, cx = view.x + view.w / 2, cy = view.y + view.h / 2) {
    const w = Math.min(MAP_W, Math.max(MAP_W / 24, view.w / factor));
    const h = (w * MAP_H) / MAP_W;
    const x = cx - ((cx - view.x) * w) / view.w;
    const y = cy - ((cy - view.y) * h) / view.h;
    view = clampView({ x, y, w, h });
  }

  function clampView(next: { x: number; y: number; w: number; h: number }) {
    return { ...next, x: Math.min(Math.max(next.x, 0), MAP_W - next.w), y: Math.min(Math.max(next.y, 0), MAP_H - next.h) };
  }

  function mapPoint(event: MouseEvent, svg: SVGSVGElement) {
    const box = svg.getBoundingClientRect();
    return { x: view.x + ((event.clientX - box.left) / box.width) * view.w, y: view.y + ((event.clientY - box.top) / box.height) * view.h };
  }

  function onMapWheel(event: WheelEvent) {
    event.preventDefault();
    const point = mapPoint(event, event.currentTarget as SVGSVGElement);
    zoomAt(event.deltaY < 0 ? 1.25 : 0.8, point.x, point.y);
  }

  function onMapDown(event: PointerEvent) {
    dragStart = { x: event.clientX, y: event.clientY, view: { ...view }, moved: false };
  }

  function onMapMove(event: PointerEvent) {
    if (!dragStart) return;
    const box = (event.currentTarget as SVGSVGElement).getBoundingClientRect();
    const dx = ((event.clientX - dragStart.x) / box.width) * dragStart.view.w;
    const dy = ((event.clientY - dragStart.y) / box.height) * dragStart.view.h;
    if (Math.abs(event.clientX - dragStart.x) + Math.abs(event.clientY - dragStart.y) > 4) dragStart.moved = true;
    if (dragStart.moved) view = clampView({ ...dragStart.view, x: dragStart.view.x - dx, y: dragStart.view.y - dy });
  }

  function onMapUp() {
    // A drag ends without following the link under the pointer.
    if (dragStart?.moved) addEventListener("click", (event) => event.preventDefault(), { capture: true, once: true });
    dragStart = null;
  }

  function mapX(lon: number): number {
    return ((lon - 2.5) / 3.95) * MAP_W;
  }

  function mapY(lat: number): number {
    return ((51.55 - lat) / 2.1) * MAP_H;
  }

  function placeName(place: MapPlace): string {
    return place[lang] || place.nl || place.fr;
  }

  /** The map page for a period (none: every entry) and a historical layer, as a link. */
  function mapHref(period: string, layer = mapLayerKind): string {
    const next = new URLSearchParams();
    if (period) next.set("period", period);
    if (period && layer === "dioceses") next.set("layer", layer);
    const query = next.toString();
    return `#/map${query ? `?${query}` : ""}`;
  }

  /** A source credit of map-periods.json, its address as a link. */
  function linkedCredit(credit: string): string {
    return escapeHtml(credit).replace(/https:\/\/\S+/, (url) => `<a href="${url}">${url.replace(/^https:\/\//, "")}</a>`);
  }

  /** A place's publications, in the chosen period when there is one. */
  function placeHref(key: string): string {
    return `#/search?place=${encodeURIComponent(key)}${mapPeriod ? `&period=${mapPeriod}` : ""}`;
  }

  function removePlace(key: string) {
    const next = new URLSearchParams(params);
    const kept = next.getAll("place").filter((value) => value !== key);
    next.delete("place");
    for (const value of kept) next.append("place", value);
    next.delete("page");
    go("/search", next);
  }
  let spelling = $state<{ word: string; suggestion: string; count: number }[]>([]);
  /**
   * The Bibliography's classification, for the subject tree and the chip (public/subjects.json, made with the index):
   * code → [parent, entries with those of its sub-codes, name in nl, fr, en]. The tree is the classification itself, as
   * the volumes from 1993 on and the State Archives' records use it; subject area, period and year are filters of the
   * results page.
   */
  type Subject = [string, number, string, string, string];
  let subjects = $state.raw<Record<string, Subject>>({});
  // The codes opened in the tree.
  let openCodes = $state<string[]>([]);

  async function loadSubjects() {
    if (Object.keys(subjects).length) return;
    try {
      const response = await fetch(new URL(`${import.meta.env.BASE_URL}subjects.json`, document.baseURI).href);
      if (response.ok) subjects = await response.json();
    } catch {
      subjects = {};
    }
  }

  /** Each code's sub-codes, in the classification's order; "" holds the top levels (I., II., III.). */
  let childrenOf = $derived.by(() => {
    const found = new Map<string, string[]>();
    for (const [code, [parent]] of Object.entries(subjects)) {
      const key = parent && subjects[parent] ? parent : "";
      found.set(key, [...(found.get(key) || []), code]);
    }
    return found;
  });

  function subjectName(code: string): string {
    const subject = subjects[code];
    if (!subject) return code;
    return (lang === "nl" ? subject[2] : lang === "fr" ? subject[3] : subject[4]) || code;
  }

  /** The number a level has in the printed table of contents: "III.", "B.", "2.", "b.". */
  function levelNumber(code: string): string {
    return `${code.replace(/\.$/, "").split(".").at(-1)}.`;
  }

  /** The chip's wording: the subject after the level above it ("Vlaanderen › Het economische en sociale leven"). */
  function subjectTitle(code: string): string {
    if (!Object.keys(subjects).length) return "…";
    const parent = subjects[code]?.[0];
    return parent && subjects[parent] ? `${subjectName(parent)} › ${subjectName(code)}` : subjectName(code);
  }

  function toggleCode(code: string) {
    openCodes = openCodes.includes(code) ? openCodes.filter((item) => item !== code) : [...openCodes, code];
  }

  function removeSubject() {
    const next = new URLSearchParams(params);
    next.delete("subject");
    next.delete("page");
    go("/search", next);
  }

  let related = $state<Hit[]>([]);
  let relatedKey = $state("");
  let relatedLoading = $state(false);

  const pageSizes = [10, 20, 50, 100];
  let page = $derived(Math.max(1, Number(params.get("page") || "1")));
  let pageSize = $derived(pageSizes.includes(Number(params.get("per"))) ? Number(params.get("per")) : 20);
  let pages = $derived(Math.max(1, Math.ceil(total / pageSize)));
  let filtering = $derived(path === "/search");

  function initialLang(): Lang {
    const stored = localStorage.getItem("bhb-lang");
    if (stored === "fr" || stored === "nl" || stored === "en") return stored;
    const browser = navigator.language.slice(0, 2);
    return browser === "nl" || browser === "en" ? browser : "fr";
  }

  function label(group: keyof typeof groups, value: string): string {
    if (group === "period") return text.periods[value as keyof typeof text.periods] || value;
    if (group === "theme") return text.themes[value as keyof typeof text.themes] || value;
    if (group === "type") return text.types[value as keyof typeof text.types] || value;
    if (group === "language") return text.languages[value as keyof typeof text.languages] || value;
    if (group === "access") return text.openAccess;
    return value;
  }

  function activeFilterCount(): number {
    return Object.keys(groups).reduce((total, group) => total + params.getAll(group).length, 0) + (params.get("from") || params.get("to") ? 1 : 0);
  }

  function correctedQuery(): string {
    let corrected = query;
    for (const { word, suggestion } of spelling) {
      corrected = corrected.replace(new RegExp(`(?<![\\p{L}])${word}(?![\\p{L}])`, "iu"), suggestion);
      if (corrected === query) corrected = foldOnce(corrected, word, suggestion);
    }
    return corrected;
  }

  /** A query word may carry accents the folded word lacks; replace it by position in the folded text. */
  function foldOnce(text: string, word: string, suggestion: string): string {
    const folded = text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
    const at = folded.indexOf(word);
    return at < 0 ? text : `${text.slice(0, at)}${suggestion}${text.slice(at + word.length)}`;
  }

  function correctedHref(): string {
    const next = new URLSearchParams(params);
    next.set("q", correctedQuery());
    next.delete("page");
    return `#/search?${next.toString()}`;
  }

  function selected(group: string, value: string): boolean {
    return params.getAll(group).includes(value);
  }

  function readRoute() {
    const raw = location.hash.replace(/^#/, "") || "/";
    const [nextPath, search = ""] = raw.split("?");
    path = nextPath.startsWith("/") ? nextPath : `/${nextPath}`;
    params = new URLSearchParams(search);
    query = params.get("q") || "";
    fieldChoice = params.get("field") || "all";
    if (!query && (path.startsWith("/record/") || path.startsWith("/similar/"))) {
      query = new URLSearchParams(sessionStorage.getItem("bhb-search") || "").get("q") || "";
    }
  }

  function go(nextPath: string, next = new URLSearchParams(params)) {
    const stay = path === "/search" && nextPath === "/search";
    const y = window.scrollY;
    const queryString = next.toString();
    const hash = queryString ? `${nextPath}?${queryString}` : nextPath;
    if (stay) {
      history.pushState(null, "", `#${hash}`);
      readRoute();
      void refresh();
      window.scrollTo(0, y);
      return;
    }
    location.hash = hash;
  }

  function activeFilters(): Filters | undefined {
    const filters: Filters = {};
    for (const group of Object.keys(groups)) {
      const values = params.getAll(group);
      if (values.length) filters[group] = values;
    }
    const years = yearFilter(Number(params.get("from")), Number(params.get("to")));
    if (years) filters.pubyear = years;
    return Object.keys(filters).length ? filters : undefined;
  }

  async function refresh() {
    if (!engine) return;
    // Place names in the page language; until they arrive the names stored with each record are shown.
    if (path !== "/" && path !== "/about") void loadPlaces();
    if (path.startsWith("/record/")) {
      const id = decodeURIComponent(path.slice("/record/".length));
      const known = recall(id);
      if (!record || record.meta.id !== id) record = known;
      loading = !record;
      const found = await findRecord(engine, id);
      if (found) record = found;
      loading = false;
      return;
    }
    if (path.startsWith("/similar/")) {
      const id = decodeURIComponent(path.slice("/similar/".length));
      if (similarSource?.meta.id !== id) {
        similarSource = recall(id);
        similarHits = [];
      }
      loading = true;
      const source = (await findRecord(engine, id)) || similarSource;
      similarSource = source;
      const wanted = source ? similarOf(source.meta) : [];
      const found = await Promise.all(wanted.map(async (item) => ({ hit: recall(item.id) || (await findRecord(engine!, item.id)), score: item.score })));
      similarHits = found.filter((item): item is { hit: Hit; score: number } => item.hit !== null);
      remember(similarHits.map((item) => item.hit));
      loading = false;
      return;
    }
    if (path === "/map") {
      await loadMap();
      loading = false;
      return;
    }
    if (path === "/topics") {
      try {
        TopicMap ??= (await import("./TopicMap.svelte")).default;
        sessionStorage.removeItem("bhb-reloaded");
      } catch {
        // A page opened before a new release asks for the map's code under its old name, which is gone: load the
        // page again, once, to get the new names.
        if (!sessionStorage.getItem("bhb-reloaded")) {
          sessionStorage.setItem("bhb-reloaded", "1");
          location.reload();
        }
      }
      loading = false;
      return;
    }
    if (params.get("topic") && !Object.keys(topicNames).length) void loadTopicNames();
    if (params.get("subject")) void loadSubjects();
    if (path === "/browse") {
      await loadSubjects();
      loading = false;
      return;
    }
    if (path !== "/search") {
      hits = [];
      listed = [];
      if (!path.startsWith("/record/")) record = null;
      total = 0;
      loading = false;
      return;
    }
    sessionStorage.setItem("bhb-search", params.toString());
    if (hits.length === 0) {
      loading = true;
      await painted();
    }
    const filters = activeFilters();
    const sort = sortOf(params.get("sort"));
    const askedText = [query, ...params.getAll("more")].map((part) => part.trim()).filter(Boolean).join(" ");
    const inside = params.get("in");
    const field = searchField(fieldChoice);
    const translations = withTranslations();
    // Within a volume, a region of the map of subjects, places, a journal or a subject of the classification: words
    // the index adds to those records.
    const topic = params.get("topic");
    const journal = params.get("journal");
    const subject = params.get("subject");
    const within = [
      inside ? `hk_${inside}` : "",
      topic ? regionWord(topic) : "",
      ...params.getAll("place").map((place) => keyWord("pl", place)),
      journal ? keyWord("jn", journal) : "",
      subject ? keyWord("sc", subject) : "",
    ].filter(Boolean).join(" ");
    const asked = [askedText ? searchQuery(askedText, field, translations) : "", within].filter(Boolean).join(" ") || null;
    const relaxed = askedText ? relaxedQuery(askedText, field, translations) : null;
    const loose = relaxed ? [relaxed, within].filter(Boolean).join(" ") : null;
    // A word that is not in the index finds nothing: say so at once rather than let Pagefind answer it with every
    // word sharing its prefix.
    const unknown = await unknownWords(loose || asked || "");
    const response = unknown.length
      ? await nothingFound(engine)
      : await searchBoth(engine, asked, loose, {
          ...(filters ? { filters } : {}),
          ...(sort ? { sort } : {}),
        });
    total = response.results.length;
    listed = response.results;
    const nextScope = scopeOf(params);
    if (nextScope !== scope) {
      counts = Object.fromEntries(
        Object.entries(response.filters || {}).map(([key, values]) => [key, { ...values }]),
      );
      scope = nextScope;
    }
    const ticket = ++yearTicket;
    if (!filters?.pubyear || unknown.length) yearCounts = { ...(response.filters?.pubyear || {}) };
    const slice = response.results.slice((page - 1) * pageSize, page * pageSize);
    hits = await Promise.all(slice.map((item) => item.data()));
    // With a year range, the year filter shows the counts of every year, so it needs the same search without the
    // range. It takes as long as the search itself ("gent" 5 s) and Pagefind computes on the page's own thread, so
    // it waits until the results have been painted (a frame, then a task), or it would hold them back.
    if (filters?.pubyear && !unknown.length) {
      const rest = { ...filters };
      delete rest.pubyear;
      const search = engine;
      requestAnimationFrame(() => setTimeout(() => {
        if (ticket !== yearTicket) return;
        void search.search(loose || asked, {
          ...(Object.keys(rest).length ? { filters: rest } : {}),
          ...(sort ? { sort } : {}),
        }).then((broad) => {
          if (ticket === yearTicket) yearCounts = { ...(broad.filters?.pubyear || {}) };
        }).catch(() => {});
      }, 0));
    }
    // Checked after the results are shown, so it never delays them.
    const spellingFor = askedText;
    spelling = [];
    if (askedText) spellingSuggestions(askedText).then((found) => {
      if (spellingFor === [query, ...params.getAll("more")].map((part) => part.trim()).filter(Boolean).join(" ")) spelling = found;
    });
    remember(hits);
    loading = false;
  }

  /** Whether the search crosses languages: all text and title search the titles' machine translations too. */
  function translatable(): boolean {
    return fieldChoice === "all" || fieldChoice === "title";
  }

  function withTranslations(): boolean {
    return params.get("tr") !== "off";
  }

  function setTranslations(on: boolean) {
    const next = new URLSearchParams(params);
    if (on) next.delete("tr");
    else next.set("tr", "off");
    next.delete("page");
    if (!next.get("q") && query) next.set("q", query);
    go("/search", next);
  }

  /** A hit the query found only in its title's machine translation (indexed for search, never shown) says so. */
  function viaTranslation(hit: Hit): boolean {
    if (!translatable() || !withTranslations()) return false;
    return foundThroughTranslation(hit.content, [query, ...params.getAll("more")].join(" "));
  }

  function scopeOf(search: URLSearchParams): string {
    const copy = new URLSearchParams(search);
    copy.delete("page");
    copy.delete("sort");
    copy.delete("per");
    return copy.toString();
  }

  function sortOf(value: string | null): Record<string, "asc" | "desc"> | undefined {
    const [key, direction] = (value || "").split("-");
    if ((key === "pubyear" || key === "year" || key === "author" || key === "title") && (direction === "asc" || direction === "desc")) {
      return { [key]: direction };
    }
    return undefined;
  }

  function setPer(value: string) {
    const next = new URLSearchParams(params);
    if (!value || value === "20") next.delete("per");
    else next.set("per", value);
    next.delete("page");
    go("/search", next);
  }

  function setSort(value: string) {
    const next = new URLSearchParams(params);
    if (!value || value === "relevance") next.delete("sort");
    else next.set("sort", value);
    next.delete("page");
    go("/search", next);
  }

  function authorParts(value: string): string[] {
    return value.split(/\s*(?:,|&)\s*/).map((name) => name.trim()).filter(Boolean);
  }

  /** The ORCID iDs of an entry's persons, by the name as the author row shows it. */
  function orcidsOf(meta: Hit["meta"]): Map<string, { id: string; note: string }> {
    const notes: Record<string, string> = { openalex: text.orcidFromDoi, name: text.orcidFromName, registry: text.orcidFromRegistry };
    return new Map((meta.orcids || "").split("|").filter(Boolean).map((line) => {
      const [name, id, from] = line.split("\t");
      return [name, { id, note: notes[from] || text.orcidFromDoi }];
    }));
  }

  type FullName = { given: string; dates: string; id: string; note: string };

  /** Given names written out from KBR (machine-derived), by the name as the author row shows it. */
  function fullNamesOf(meta: Hit["meta"]): Map<string, FullName> {
    return new Map((meta.fullNames || "").split("|").filter(Boolean).map((line) => {
      const [name, given, dates, id, from] = line.split("\t");
      return [name, { given, dates, id, note: from === "kbr-name" ? text.nameFromKbrElsewhere : text.nameFromKbr }];
    }));
  }

  function rows(hit: Hit): { label: string; value: string; italic?: boolean; authors?: boolean; orcids?: Map<string, { id: string; note: string }>; fullNames?: Map<string, FullName>; derived?: string; container?: string; suffix?: string; containerTitle?: string; href?: string; free?: string }[] {
    const meta = hit.meta;
    const hostLabel = meta.kind === "article" ? text.journal : text.host;
    const work = meta.kind === "book" || meta.kind === "journal-issue";
    const editors = meta.hostEditors?.trim() || editorsBeforeHost(meta.citation || "", meta.host);
    const pairs: [string, string | undefined, boolean?][] = [
      [text.author, meta.authors],
      // A collected volume's own editors; a chapter's editors are its host's, below.
      [text.hostEditors, meta.editors],
      [text.fieldTitle, meta.title, work],
      [text.subtitle, meta.subtitle ? capitalize(meta.subtitle) : undefined, work],
      // An article's journal by the name of the journal list (the citation keeps the printed spelling).
      [hostLabel, hostLabel === text.journal && meta.journalTitle ? meta.journalTitle : meta.host === HOST_MISSING ? text.hostMissing : meta.host, true],
      [text.hostSubtitle, meta.hostSubtitle ? capitalize(meta.hostSubtitle) : undefined, true],
      [text.hostEditors, editors],
      [text.volume, meta.volume],
      [text.issue, meta.issue],
      [text.pages, meta.pages],
      [meta.yearFromVolume === "1" ? text.yearFromVolume : text.pubyear, meta.yearFromVolume === "1" ? meta.year : meta.pubyear],
      [text.place, meta.place],
      [text.publisher, meta.publisher],
      [text.extent, meta.extent],
      [text.series, seriesLine(meta)],
      [text.contents, meta.kind === "book" && meta.container ? text.contentsCount.replace("{n}", String(Number(meta.containerCount) - 1)) : ""],
      [text.doi, meta.doi],
      [text.isbn, (meta.isbn || "").split("|").join(", ")],
      [text.issn, (meta.issn || "").split("|").join(", ")],
      [text.kbrRecord, meta.kbr],
      [text.type, meta.kind ? text.types[meta.kind as keyof typeof text.types] || meta.kind : ""],
      [text.source, meta.source ? text.sources[meta.source as keyof typeof text.sources] || meta.source : ""],
    ];
    return pairs.flatMap(([label, value, italic]) =>
      value
        ? [{
            label,
            value,
            italic,
            authors: label === text.author || label === text.hostEditors,
            orcids: label === text.author || label === text.hostEditors ? orcidsOf(meta) : undefined,
            fullNames: label === text.author || label === text.hostEditors ? fullNamesOf(meta) : undefined,
            derived: derivedNote(label, meta),
            // The fields read by the language model: a mark after the source, explained in the footer.
            marked: label === text.source && meta.parsedLlm ? text.parsedByModel : undefined,
            container: containerLink(label, meta) || (label === text.journal ? journalLink(meta) : undefined) || (label === text.series ? seriesLink(meta) : undefined),
            // The series link covers the series' name only; its number follows as text.
            ...(label === text.series && meta.seriesTitle ? { value: meta.seriesTitle, suffix: meta.seriesNumber ? `, ${meta.seriesNumber}` : "" } : {}),
            containerTitle: label === text.journal && meta.journalId ? journalNote(meta) : label === text.series && meta.seriesTitle ? text.seriesWhy : undefined,
            href: identifierLink(label, value),
            free: label === text.doi && meta.free ? (meta.free === "persee" ? text.freePersee : text.freeOpenAlex) : undefined,
          }]
        : [],
    );
  }

  /** The journal row's note: the spellings were grouped, and the spelling printed with this entry when it differs. */
  function journalNote(meta: Hit["meta"]): string {
    const printed = meta.host?.trim() || "";
    const differs = printed && meta.journalTitle && printed.toLowerCase() !== meta.journalTitle.toLowerCase();
    return differs ? `${text.journalPrinted.replace("{title}", printed)} ${text.journalGrouped}` : text.journalGrouped;
  }

  /** Every entry in the series: a search for its title's words in the series field, newest first. */
  function seriesLink(meta: Hit["meta"]): string | undefined {
    return meta.seriesTitle ? `#/search?q=${encodeURIComponent(meta.seriesTitle)}&field=series&sort=pubyear-desc` : undefined;
  }

  function seriesLine(meta: Hit["meta"]): string {
    return [meta.seriesTitle, meta.seriesNumber].filter(Boolean).join(", ");
  }

  /** The host title of a chapter, and the contents line of a volume, open the volume's entries. */
  function containerLink(label: string, meta: Hit["meta"]): string | undefined {
    if (!meta.container) return undefined;
    const title = meta.kind === "book" ? meta.title : meta.host;
    if (!(meta.kind === "chapter" && label === text.host) && label !== text.contents) return undefined;
    return `#/search?in=${meta.container}&inTitle=${encodeURIComponent(title || "")}`;
  }

  /** Two frames, so the hourglass is painted and turning before Pagefind's work holds up the page's thread; at most
   * 50 ms, since a tab in the background gets no frames. */
  function painted(): Promise<void> {
    return new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      setTimeout(resolve, 50);
    });
  }

  async function loadTopicNames() {
    try {
      const list: { id: string; name?: { nl: string; fr: string; en: string } }[] = await fetch(new URL(`${import.meta.env.BASE_URL}topics/regions.json`, document.baseURI).href).then((response) => response.json());
      topicNames = Object.fromEntries(list.filter((region) => region.name).map((region) => [region.id, region.name!]));
    } catch {
      topicNames = {};
    }
  }

  function removeTopic() {
    const next = new URLSearchParams(params);
    next.delete("topic");
    next.delete("page");
    go("/search", next);
  }

  function removeJournal() {
    const next = new URLSearchParams(params);
    next.delete("journal");
    next.delete("journalTitle");
    next.delete("page");
    go("/search", next);
  }

  /** All articles of the journal, whatever the spelling, newest first. */
  function journalLink(meta: Hit["meta"]): string | undefined {
    if (!meta.journalId) return undefined;
    return `#/search?journal=${encodeURIComponent(meta.journalId)}&journalTitle=${encodeURIComponent(meta.journalTitle || meta.host || "")}&sort=pubyear-desc`;
  }

  function removeInside() {
    const next = new URLSearchParams(params);
    next.delete("in");
    next.delete("inTitle");
    next.delete("page");
    go("/search", next);
  }

  /** A DOI opens the publication; an ISBN a library catalogue; an ISSN the journal's record at the ISSN portal. */
  function identifierLink(label: string, value: string): string | undefined {
    const first = value.split(",")[0].trim();
    if (label === text.doi) return `https://doi.org/${first}`;
    if (label === text.isbn) return `https://openlibrary.org/search?isbn=${first.replace(/[^0-9Xx]/g, "")}`;
    if (label === text.issn) return `https://portal.issn.org/resource/ISSN/${first}`;
    if (label === text.kbrRecord) return `https://uurl.kbr.be/bib/${first}`;
    return undefined;
  }

  function identifierSource(kind: string, meta: Hit["meta"]): string | undefined {
    const source = (meta.identifiersFrom || "").split("|").find((entry: string) => entry.startsWith(`${kind}:`))?.split(":")[1];
    const notes: Record<string, string> = { crossref: text.fromCrossref, vabb: text.fromVabb, openlibrary: text.fromOpenLibrary,
      volume: text.fromVolume, "openlibrary-volume": text.fromOpenLibraryVolume, kbr: text.fromKbr, "kbr-volume": text.fromKbrVolume };
    return source ? notes[source] : undefined;
  }

  function derivedNote(label: string, meta: Hit["meta"]): string | undefined {
    if (label === text.doi) return identifierSource("doi", meta);
    if (label === text.isbn) return identifierSource("isbn", meta);
    if (label === text.issn) return identifierSource("issn", meta);
    if (label === text.kbrRecord) return identifierSource("kbr", meta);
    if (label === text.journal && meta.hostMatched === "1") return text.hostMatched;
    if ((label === text.journal || label === text.host) && meta.host === HOST_MISSING && !meta.journalTitle) return text.hostMissingNote;
    if ((label === text.journal || label === text.host) && meta.hostFromIbid === "1") return text.hostFromIbid;
    if (label === text.pubyear && meta.yearMachine === "1") return text.yearFromHost;
    if ((label === text.place || label === text.publisher) && meta.imprintMachine === "1") return text.imprintFromHost;
    return undefined;
  }

  async function exportList(kind: ExportKind) {
    if (exporting || listed.length === 0) return;
    exporting = true;
    exportOpen = "";
    const slice = listed.slice(0, EXPORT_CAP);
    const found = total;
    try {
      const loaded: Hit[] = [];
      for (let index = 0; index < slice.length; index += 20) {
        loaded.push(...(await Promise.all(slice.slice(index, index + 20).map((item) => item.data()))));
      }
      saveExports(loaded, kind, text.name, text.source, exportStem(query), found);
    } finally {
      exporting = false;
    }
  }

  function exportStem(value: string): string {
    const slug = value
      .normalize("NFD")
      .replace(/\p{M}/gu, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 40);
    return slug ? `bhb-${slug}` : "bhb";
  }

  function capitalize(value: string): string {
    const match = value.match(/\p{L}/u);
    if (!match || match.index === undefined) return value;
    const index = match.index;
    return value.slice(0, index) + value.charAt(index).toLocaleUpperCase(lang) + value.slice(index + 1);
  }

  /** Related by meaning is offered for a text search in relevance order; an author search has no subject. */
  function canRelate(): boolean {
    return Boolean(query.trim()) && total >= 3 && !params.get("sort") && searchField(fieldChoice) !== "author";
  }

  async function showRelated() {
    if (!engine || relatedLoading) return;
    relatedLoading = true;
    relatedKey = scopeOf(params);
    const top = await Promise.all(listed.slice(0, 20).map((item) => item.data()));
    const asked = [query, ...params.getAll("more")].join(" ");
    related = await relatedByMeaning(engine, top, asked, recall);
    remember(related);
    relatedLoading = false;
  }

  function recall(id: string): Hit | null {
    try {
      const cache = JSON.parse(sessionStorage.getItem("bhb-hits") || "{}") as Record<string, Hit>;
      return cache[id] || null;
    } catch {
      return null;
    }
  }

  function remember(loaded: Hit[]) {
    const cache: Record<string, Hit> = {};
    try {
      Object.assign(cache, JSON.parse(sessionStorage.getItem("bhb-hits") || "{}"));
    } catch {
      /* a bad cache is replaced by the hits just loaded */
    }
    for (const hit of loaded) cache[hit.meta.id] = hit;
    const ids = Object.keys(cache);
    for (const id of ids.slice(0, Math.max(0, ids.length - 80))) delete cache[id];
    sessionStorage.setItem("bhb-hits", JSON.stringify(cache));
  }

  function searchField(value: string | null): SearchField {
    return value === "author" || value === "title" || value === "host" ? value : "all";
  }

  function yearDomain(): { min: number; max: number } {
    const now = new Date().getFullYear();
    const keys = Object.keys(yearCounts).map(Number).filter((year) => year >= 1800 && year <= now);
    if (!keys.length) return { min: 1945, max: now };
    return { min: Math.min(...keys), max: Math.max(...keys) };
  }

  function selectedYears(): { from: number; to: number } {
    const domain = yearDomain();
    const from = dragFrom ?? (Number(params.get("from")) || domain.min);
    const to = dragTo ?? (Number(params.get("to")) || domain.max);
    return { from: Math.min(from, to), to: Math.max(from, to) };
  }

  function yearPercent(year: number, domain: { min: number; max: number }): number {
    const span = domain.max - domain.min;
    if (span <= 0) return 0;
    return ((year - domain.min) / span) * 100;
  }

  function yearTicks(domain: { min: number; max: number }): number[] {
    const span = domain.max - domain.min;
    if (span <= 0) return [];
    const step = span > 100 ? 20 : 10;
    const start = Math.ceil(domain.min / step) * step;
    const marks: number[] = [];
    for (let year = start; year <= domain.max; year += step) marks.push(yearPercent(year, domain));
    return marks;
  }

  function histogram() {
    const domain = yearDomain();
    const span = domain.max - domain.min + 1;
    const bin = span > 90 ? 2 : 1;
    const chosen = selectedYears();
    const buckets: { count: number; year: number }[] = [];
    for (let year = domain.min; year <= domain.max; year += bin) {
      let count = 0;
      for (let step = 0; step < bin && year + step <= domain.max; step += 1) count += yearCounts[String(year + step)] || 0;
      buckets.push({ year, count });
    }
    const peak = Math.max(1, ...buckets.map((bucket) => bucket.count));
    return buckets.map((bucket, index) => ({
      x: (index / buckets.length) * 100,
      y: 32 - (bucket.count / peak) * 32,
      w: Math.max(0.4, 100 / buckets.length - 0.2),
      h: (bucket.count / peak) * 32,
      dim: bucket.year > chosen.to || bucket.year + bin - 1 < chosen.from,
    }));
  }

  function commitYears(from: number, to: number) {
    dragFrom = null;
    dragTo = null;
    const domain = yearDomain();
    const next = new URLSearchParams(params);
    const start = Math.max(domain.min, Math.min(from, to));
    const end = Math.min(domain.max, Math.max(from, to));
    if (start <= domain.min && end >= domain.max) {
      next.delete("from");
      next.delete("to");
    } else {
      next.set("from", String(start));
      next.set("to", String(end));
    }
    next.delete("page");
    if (!next.get("q") && query) next.set("q", query);
    go("/search", next);
  }

  function nudgeYear(which: "from" | "to", event: KeyboardEvent) {
    const step = event.key === "PageUp" ? 10 : event.key === "PageDown" ? -10 : event.key === "ArrowUp" || event.key === "ArrowRight" ? 1 : event.key === "ArrowDown" || event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const domain = yearDomain();
    const chosen = selectedYears();
    if (which === "from") commitYears(Math.min(chosen.to, Math.max(domain.min, chosen.from + step)), chosen.to);
    else commitYears(chosen.from, Math.max(chosen.from, Math.min(domain.max, chosen.to + step)));
  }

  function setField(value: string) {
    fieldChoice = value;
    if (path !== "/search") return;
    const next = new URLSearchParams(params);
    if (value && value !== "all") next.set("field", value);
    else next.delete("field");
    next.delete("page");
    go("/search", next);
  }

  function addWithin(event: SubmitEvent) {
    event.preventDefault();
    const words = withinBox.trim();
    if (!words) return;
    const next = new URLSearchParams(params);
    next.append("more", words);
    next.delete("page");
    if (!next.get("q") && query) next.set("q", query);
    withinBox = "";
    go("/search", next);
  }

  function removeMore(index: number) {
    const next = new URLSearchParams(params);
    const kept = next.getAll("more").filter((_, item) => item !== index);
    next.delete("more");
    next.delete("page");
    for (const chip of kept) next.append("more", chip);
    go("/search", next);
  }

  function submit(event: SubmitEvent) {
    event.preventDefault();
    const next = new URLSearchParams(path === "/search" ? params : undefined);
    next.set("q", query);
    if (fieldChoice && fieldChoice !== "all") next.set("field", fieldChoice);
    else next.delete("field");
    next.delete("page");
    go("/search", next);
  }

  function toggle(group: string, value: string) {
    const next = new URLSearchParams(params);
    const values = next.getAll(group).filter((item) => item !== value);
    if (!selected(group, value)) values.push(value);
    next.delete(group);
    next.delete("page");
    if (!next.get("q")) next.set("q", query);
    for (const item of values) next.append(group, item);
    go("/search", next);
  }

  function clearFilters() {
    const next = new URLSearchParams();
    if (query) next.set("q", query);
    const sort = params.get("sort");
    const per = params.get("per");
    if (sort) next.set("sort", sort);
    if (per) next.set("per", per);
    if (fieldChoice && fieldChoice !== "all") next.set("field", fieldChoice);
    if (params.get("tr")) next.set("tr", params.get("tr")!);
    go("/search", next);
  }

  /** Closes the open record and goes to the top when a link of the site inside it is followed (see resultRow). */
  function leaveRecord(event: MouseEvent) {
    const link = (event.target as Element).closest?.("a[href^='#/']");
    if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    openId = "";
    window.scrollTo(0, 0);
  }

  function turn(nextPage: number) {
    const next = new URLSearchParams(params);
    next.set("page", String(nextPage));
    go("/search", next);
  }

  // The header menu (phones and tablets) closes on Escape (focus goes back to its button) and on a click anywhere outside it.
  function closeMenu(event: KeyboardEvent | MouseEvent) {
    if (!menuOpen) return;
    if (event instanceof KeyboardEvent) {
      if (event.key !== "Escape") return;
      menuOpen = false;
      menuButton.focus();
    } else if (!menuPanel.contains(event.target as Node) && !menuButton.contains(event.target as Node)) {
      menuOpen = false;
    }
  }

  function choose(next: Lang) {
    lang = next;
    localStorage.setItem("bhb-lang", next);
  }

  $effect(() => {
    document.documentElement.lang = lang;
    document.title = text.name;
  });

  onMount(() => {
    const onHash = () => {
      menuOpen = false;
      readRoute();
      void refresh();
    };
    window.addEventListener("hashchange", onHash);
    window.addEventListener("popstate", onHash);
    readRoute();
    // The subject tree needs no search index: it shows while the index loads, and when it cannot.
    if (path === "/browse") void loadSubjects();
    painted()
      .then(loadEngine)
      .then((loaded) => {
        engine = loaded;
        return refresh();
      })
      .catch((error) => {
        // For developers: a local site without its index needs `npm run index` (and a build) in site/.
        console.error("Pagefind index not loaded (locally: npm run index in site/)", error);
        missing = true;
        loading = false;
      });
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("popstate", onHash);
    };
  });
</script>

{#snippet listExporter()}
  <div class="results-export">
    <div class="export">
      <button
        type="button"
        class="export-toggle"
        aria-expanded={exportOpen === "all" ? "true" : "false"}
        aria-haspopup="menu"
        disabled={exporting}
        onclick={() => { exportOpen = exportOpen === "all" ? "" : "all"; }}
      >{exporting ? text.loading : text.export}</button>
      {#if exportOpen === "all"}
        <div class="menu" role="menu">
          {#each Object.entries(text.exports) as [kind, label]}
            <button type="button" role="menuitem" onclick={() => exportList(kind as ExportKind)}>{label}</button>
          {/each}
        </div>
      {/if}
    </div>
    {#if total > EXPORT_CAP}<span class="export-cap">{text.exportCap.replace("{n}", String(EXPORT_CAP))}</span>{/if}
  </div>
{/snippet}

{#snippet fieldValue(row: { value: string; italic?: boolean; authors?: boolean; orcids?: Map<string, { id: string; note: string }>; fullNames?: Map<string, FullName>; derived?: string; marked?: string; container?: string; suffix?: string; containerTitle?: string; href?: string; free?: string })}
  {#if row.href}
    <a class="derived" href={row.href} title={row.derived} target="_blank" rel="noopener">{row.value}</a>{#if row.free}
      <span class="tag tag-free" title={row.free}>{@render padlock()}{text.freeToRead}</span>{/if}
  {:else if row.container}
    <a class={row.derived ? "container-link derived" : "container-link"} href={row.container} title={[row.derived, row.containerTitle || text.containerWhy].filter(Boolean).join(" ")}>{#if row.italic}<em>{row.value}</em>{:else}{row.value}{/if}</a>{row.suffix || ""}
  {:else if row.authors}
    {@const names = authorParts(row.value)}
    {#each names as name, index}
      {@const orcid = row.orcids?.get(name)}
      {@const full = row.fullNames?.get(name)}
      {#if index > 0}{index === names.length - 1 ? " & " : ", "}{/if}<a class="author-link" href={"#/search?q=" + encodeURIComponent(name) + "&field=author"} title={text.authorMatch}>{name}</a>{#if orcid}<a class="orcid" href={"https://orcid.org/" + orcid.id} title={`ORCID ${orcid.id}. ${orcid.note}`} target="_blank" rel="noopener"><span class="sr-only">ORCID {orcid.id}</span><svg viewBox="0 0 256 256" width="15" height="15" aria-hidden="true"><path fill="#A6CE39" d="M256 128c0 70.7-57.3 128-128 128S0 198.7 0 128 57.3 0 128 0s128 57.3 128 128z"/><path fill="#fff" d="M86.3 186.2H70.9V79.1h15.4v107.1zM108.9 79.1h41.6c39.6 0 57 28.3 57 53.6 0 27.5-21.5 53.6-56.8 53.6h-41.8V79.1zm15.4 93.3h24.5c34.9 0 42.9-26.5 42.9-39.7 0-21.5-13.7-39.7-43.7-39.7h-23.7v79.4zM88.7 56.8c0 5.5-4.5 10.1-10.1 10.1s-10.1-4.6-10.1-10.1 4.5-10.1 10.1-10.1 10.1 4.6 10.1 10.1z"/></svg></a>{/if}{#if full?.given}{@const note = `${full.given} ${name.split(" (")[0]}${full.dates ? ` (${full.dates.replace("-", "–")})` : ""}. ${full.note}`}{" "}{#if full.id}<a class="full-name derived" href={"https://opac.kbr.be/Library/search.aspx?SC=CATALOGUE&QUERY=Authority_id_idx%3a" + full.id} title={`${note} ${text.nameKbrLink}`} target="_blank" rel="noopener">[{full.given}]</a>{:else}<span class="full-name derived" title={note}>[{full.given}]</span>{/if}{/if}
    {/each}
  {:else if row.italic && row.derived}
    <em class="derived" title={row.derived}>{row.value}</em>
  {:else if row.italic}
    <em>{row.value}</em>
  {:else if row.derived}
    <span class="derived" title={row.derived}>{row.value}</span>
  {:else}
    {row.value}{#if row.marked}<sup class="note-mark" title={row.marked}>*</sup>{/if}
  {/if}
{/snippet}

{#snippet facetValues(group: "theme" | "period", values: string, suggested: string)}
  {@const own = values.split("|").filter(Boolean)}
  {@const machine = suggested.split("|").filter(Boolean)}
  <span class="tags">
    {#each own as value}
      {#if machine.includes(value)}
        <span class="tag tag-suggested" title={text.suggestedValue}>{label(group, value)}</span>
      {:else}
        <span class="tag">{label(group, value)}</span>
      {/if}
    {/each}
  </span>
{/snippet}

<!-- One level of the classification: its name opens the levels below it, its count lists its publications (those of
     the levels below included). A level without levels below is a link itself. -->
{#snippet subjectNode(code: string)}
  {@const kids = childrenOf.get(code) || []}
  {@const open = openCodes.includes(code)}
  {@const count = text.browsePublications.replace("{n}", (subjects[code]?.[1] || 0).toLocaleString(lang))}
  {@const href = `#/search?subject=${encodeURIComponent(code)}`}
  <!-- Every level alike: the arrow (or its empty place), the printed number in a column of its own, the name (it opens
       the levels below, or the publications when there are none), and the count, which lists the publications. -->
  <li>
    <div class="tree-row">
      {#if kids.length}
        <button type="button" class="tree-name" aria-expanded={open} onclick={() => toggleCode(code)}>
          <svg class="chevron" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M6 4l4 4-4 4" /></svg>
          <span class="tree-number" title={`${text.bhbCode} ${code}`}>{levelNumber(code)}</span>
          <span class="tree-text">{subjectName(code)}</span>
        </button>
      {:else}
        <a class="tree-name" {href}>
          <span class="chevron" aria-hidden="true"></span>
          <span class="tree-number" title={`${text.bhbCode} ${code}`}>{levelNumber(code)}</span>
          <span class="tree-text">{subjectName(code)}</span>
        </a>
      {/if}
      <a class="tree-publications" {href} aria-label={`${subjectName(code)}: ${count}`}>{count}</a>
    </div>
    {#if open && kids.length}
      <ul>{#each kids as kid (kid)}{@render subjectNode(kid)}{/each}</ul>
    {/if}
  </li>
{/snippet}

{#snippet categoryBlock(hit: Hit)}
  {@const specific = (lang === "nl" ? hit.meta.specificNl : lang === "en" ? hit.meta.specificEn : hit.meta.specificFr) || hit.meta.specificFr || ""}
  {#if hit.meta.themes || specific}
    <p class="category-line">
      <span class="theme">{text.subjects}</span>
      {#if hit.meta.themes}{@render facetValues("theme", hit.meta.themes, hit.meta.themesSuggested || "")}{/if}
      <!-- The finest subject: the last part of the BHB code's label, or of the printed heading before 1993. -->
      {#if specific && hit.meta.specificFrom && hit.meta.specificFrom !== "printed"}
        <!-- A subject of the classification opens all its entries, as in the subject tree. -->
        <a
          class={hit.meta.specificMachine === "1" ? "tag tag-narrow tag-link tag-suggested" : "tag tag-narrow tag-link"}
          href={`#/search?subject=${encodeURIComponent(hit.meta.specificFrom)}`}
          title={`${hit.meta.specificMachine === "1" ? `${text.suggestedValue} ` : ""}${text.bhbCode} ${hit.meta.specificFrom} — ${text.subjectLink}`}
        >{specific}</a>
      {:else if specific}
        <span
          class={hit.meta.specificMachine === "1" ? "tag tag-narrow tag-suggested" : "tag tag-narrow"}
          title={hit.meta.specificMachine === "1" ? text.suggestedValue : text.asPrinted}
        >{specific}</span>
      {/if}
    </p>
  {/if}
  {#if hit.meta.periods}
    <p class="category-line"><span class="theme">{text.periodsLabel}</span> {@render facetValues("period", hit.meta.periods, hit.meta.periodsSuggested || "")}</p>
  {/if}
  {#if hit.meta.languages}
    <!-- Every language is a machine value: read in the title, or lent by the journal or volume. -->
    {@const why = text.languageWhy[(hit.meta.languageFrom || "title") as keyof typeof text.languageWhy] || text.languageWhy.title}
    <p class="category-line">
      <span class="theme">{text.languagesLabel}</span>
      <span class="tags">
        {#each hit.meta.languages.split("|") as code (code)}
          <span class="tag tag-suggested" title={why}>{label("language", code)}</span>
        {/each}
      </span>
    </p>
  {/if}
  {#if hit.meta.placeIds}
    {@const names = (hit.meta.places || "").split("|")}
    <p class="category-line">
      <span class="theme">{text.placesLabel}</span>
      <span class="tags">
        {#each hit.meta.placeIds.split("|") as key, index (key)}
          <a
            class={hit.meta.placesSuggested ? "tag tag-link tag-suggested" : "tag tag-link"}
            href={`#/search?place=${encodeURIComponent(key)}`}
            title={hit.meta.placesSuggested ? text.placeFromTitle : text.placeIndexed}>{placeLabel(key, names[index])}</a
          >
        {/each}
      </span>
    </p>
  {/if}
{/snippet}

{#snippet fieldSelect()}
  <select class="field" aria-label={text.fieldSearch} value={fieldChoice} onchange={(event) => setField(event.currentTarget.value)}>
    <option value="all">{text.fields.all}</option>
    <option value="author">{text.fields.author}</option>
    <option value="title">{text.fields.title}</option>
    <option value="host">{text.fields.host}</option>
    <option value="series">{text.fields.series}</option>
  </select>
{/snippet}

{#snippet typeIcon(kind: string | undefined)}
  {@const name = text.types[(kind || "other") as keyof typeof text.types] || text.types.other}
  <span class="type-mark" title={name}>
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      {#if kind === "book"}
        <path d="M3 2.5h7.5A1.5 1.5 0 0 1 12 4v9.5H4.5A1.5 1.5 0 0 0 3 15V2.5zM3 12.5h9" />
      {:else if kind === "chapter"}
        <path d="M3.5 2h6l3 3v9h-9V2zM9.5 2v3h3M5.5 8h5M5.5 10.5h3.5" />
      {:else if kind === "journal-issue"}
        <path d="M2.5 4h8v10h-8zM5.5 2.5h8v10" />
      {:else if kind === "other"}
        <path d="M4 4h8v8H4z" />
      {:else}
        <path d="M4 2h8v12H4zM6 5.5h4M6 8h4M6 10.5h2.5" />
      {/if}
    </svg>
    <span class="sr-only">{name}</span>
  </span>
{/snippet}

{#snippet wand(hit: Hit)}
  {#if similarOf(hit.meta).length}
    <a class="wand" href={"#/similar/" + encodeURIComponent(hit.meta.id)} title={text.similarWhy}>
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        <path d="M2.5 13.5l7.5-7.5M9 5l2 2M12 1.5v2.5M10.75 2.75h2.5M14 6v2M13 7h2M6 1.5v2M5 2.5h2" />
      </svg>
      <span>{text.similar}</span>
    </a>
  {/if}
{/snippet}

{#snippet padlock()}
  <!-- The open access padlock (PLoS, public domain): an open shackle over the lock. -->
  <svg class="padlock" viewBox="0 0 64 100" width="9" height="14" aria-hidden="true"><path d="M14 47V30a18 18 0 0 1 36 0v5" /><circle cx="32" cy="70" r="24" /><circle class="keyhole" cx="32" cy="70" r="7" /></svg>
{/snippet}

{#snippet openAccess(source: string)}
  <span class="open-access" title={source === "persee" ? text.freePersee : text.freeOpenAlex} aria-label={text.freeToRead}>{@render padlock()}</span>
{/snippet}

{#snippet resultRow(hit: Hit)}
  {@const open = openId === hit.meta.id}
  <article class="result">
    <button type="button" class="result-toggle" aria-expanded={open} onclick={() => { openId = open ? "" : hit.meta.id; }}>
      {@render typeIcon(hit.meta.kind)}
      <span class="citation">{@html citationHtml(hit.meta.citation || hit.meta.title, hit.meta, text.yearFromHost, text.volumeFromEntry, text.hostMatched, text.hostMissing, text.hostMissingNote, text.yearFromShort, text.yearNotPrinted)}{#if hit.meta.free}{@render openAccess(hit.meta.free)}{/if}{#if viaTranslation(hit)}<span class="via-translation">{text.viaTranslation}</span>{/if}</span>
      <svg class="chevron" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M4 6l4 4 4-4" /></svg>
    </button>
    {#if open}
      <!-- A click on a link of the site inside an open record (an author, a journal, a place, a subject) starts a new
           search or opens a page: the record closes and the page goes to the top, so the reader sees the new list and
           its count, not the record they left. Keyboard users reach the links themselves, so no key handler is needed. -->
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
      <div class="expanded" onclick={leaveRecord}>
        {#if rows(hit).length}
          <dl class="fields">
            {#each rows(hit) as row}
              <div>
                <dt>{row.label}</dt>
                <dd>{@render fieldValue(row)}</dd>
              </div>
            {/each}
          </dl>
        {/if}
        {@render categoryBlock(hit)}
        <div class="expanded-actions">
          {@render wand(hit)}
          {@render exporter(hit)}
          <a href={hit.url}>{text.recordLink}</a>
        </div>
      </div>
    {/if}
  </article>
{/snippet}

{#snippet exporter(hit: Hit)}
  <div class="export">
    <button
      type="button"
      class="export-toggle"
      aria-expanded={exportOpen === hit.meta.id ? "true" : "false"}
      aria-haspopup="menu"
      onclick={() => { exportOpen = exportOpen === hit.meta.id ? "" : hit.meta.id; }}
    >{text.export}</button>
    {#if exportOpen === hit.meta.id}
      <div class="menu" role="menu">
        {#each Object.entries(text.exports) as [kind, label]}
          <button
            type="button"
            role="menuitem"
            onclick={() => {
              saveExport(hit, kind as ExportKind, text.name, text.source);
              exportOpen = "";
            }}
          >{label}</button>
        {/each}
      </div>
    {/if}
  </div>
{/snippet}

<svelte:window onkeydown={closeMenu} onclick={closeMenu} />

<header class="bar">
  <a class="brand" href="#/">
    <img src={asset("crh-logo.svg")} alt="" />
    <strong>{text.name}</strong>
  </a>
  {#if filtering || path.startsWith("/record/") || path.startsWith("/similar/") || path === "/about"}
    <form class="search" onsubmit={submit}>
      {@render fieldSelect()}
      <input bind:value={query} type="search" aria-label={text.search} />
      <button type="submit">{text.search}</button>
    </form>
  {/if}
  <!-- On phones and tablets the links and languages fold into a menu; on wide screens the button is hidden and they sit in the bar. -->
  <button type="button" class="menu-button" aria-expanded={menuOpen} aria-controls="site-menu" aria-label={text.menu} bind:this={menuButton} onclick={() => { menuOpen = !menuOpen; }}>
    <svg viewBox="0 0 20 14" width="20" height="14" aria-hidden="true"><path d="M0 1h20M0 7h20M0 13h20" /></svg>
  </button>
  <div class="site-menu" class:open={menuOpen} id="site-menu" bind:this={menuPanel}>
    <a class="browse-link" href="#/browse" aria-current={path === "/browse" ? "true" : undefined} onclick={() => { menuOpen = false; }}>{text.browse}</a>
    <a class="browse-link" href="#/topics" aria-current={path === "/topics" ? "true" : undefined} onclick={() => { menuOpen = false; }}>{text.topics}</a>
    <a class="browse-link" href="#/map" aria-current={path === "/map" ? "true" : undefined} onclick={() => { menuOpen = false; }}>{text.map}</a>
    <nav class="langs">
      {#each ["fr", "nl", "en"] as code}
        <button type="button" aria-current={lang === code ? "true" : undefined} onclick={() => choose(code as Lang)}>{code.toUpperCase()}</button>
      {/each}
    </nav>
  </div>
</header>
<p class="banner">{text.beta}</p>

{#if path.startsWith("/record/")}
  <main class="wrap">
    <p><a href="#/search?{sessionStorage.getItem("bhb-search") || ""}">{text.back}</a></p>
    {#if loading}
      <Waiting message={text.loading} />
    {:else if record}
      <h1>
        {#if record.meta.kind === "book" || record.meta.kind === "journal-issue"}<em>{record.meta.title}</em>{:else}{record.meta.title}{/if}
      </h1>
      <p class="citation">{@html citationHtml(record.meta.citation || record.meta.title, record.meta, text.yearFromHost, text.volumeFromEntry, text.hostMatched, text.hostMissing, text.hostMissingNote, text.yearFromShort, text.yearNotPrinted)}</p>
      <div class="record-export">{@render wand(record)}{@render exporter(record)}</div>
      {#if rows(record).length}
        <dl class="fields">
          {#each rows(record) as row}
            <div>
              <dt>{row.label}</dt>
              <dd>{@render fieldValue(row)}</dd>
            </div>
          {/each}
        </dl>
      {/if}
      {@render categoryBlock(record)}
      <p class="imprint">{text.printed}{record.meta.year ? ` · BGB ${record.meta.year}` : ""}{record.meta.number ? ` · ${record.meta.number}` : ""}</p>
    {:else}
      <p>{text.notFound}</p>
    {/if}
  </main>
{:else if filtering}
  <main class="wrap layout">
    <aside class="filters" class:open={filtersOpen}>
      <!-- On a phone the column stacks above the results, so it starts closed behind this button. -->
      <button type="button" class="filters-button" aria-expanded={filtersOpen} onclick={() => { filtersOpen = !filtersOpen; }}>
        {text.filters}{activeFilterCount() ? ` (${activeFilterCount()})` : ""}
        <svg class="chevron" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 6l4 4 4-4" /></svg>
      </button>
      <h2>{text.filters}</h2>
      {#each Object.entries(groups) as [group, values]}
        <fieldset>
          <legend>{text[group as "period" | "theme" | "language" | "type" | "access"]}</legend>
          {#each values as value}
            {@const count = counts[group]?.[value] ?? 0}
            <label>
              <input type="checkbox" checked={selected(group, value)} onchange={() => toggle(group, value)} />
              <span>{label(group as keyof typeof groups, value)}<em>{count ? count.toLocaleString(lang) : ""}</em></span>
            </label>
          {/each}
        </fieldset>
      {/each}
      {#if true}
      {@const domain = yearDomain()}
      {@const chosen = selectedYears()}
      <fieldset class="years">
        <legend>{text.yearFilter}</legend>
        <svg class="hist" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
          {#each histogram() as bar}
            <rect x={bar.x} y={bar.y} width={bar.w} height={bar.h} class:dim={bar.dim} />
          {/each}
        </svg>
        <div class="handles">
          <div class="track" aria-hidden="true">
            <span class="chosen" style="left: {yearPercent(chosen.from, domain)}%; width: {yearPercent(chosen.to, domain) - yearPercent(chosen.from, domain)}%"></span>
            {#each yearTicks(domain) as tick}
              <i style="left: {tick}%"></i>
            {/each}
          </div>
          <input type="range" min={domain.min} max={domain.max} value={chosen.from} aria-label={text.yearFrom} oninput={(event) => { dragFrom = Number(event.currentTarget.value); }} onchange={(event) => commitYears(Number(event.currentTarget.value), chosen.to)} onkeydown={(event) => nudgeYear("from", event)} />
          <input type="range" min={domain.min} max={domain.max} value={chosen.to} aria-label={text.yearTo} oninput={(event) => { dragTo = Number(event.currentTarget.value); }} onchange={(event) => commitYears(chosen.from, Number(event.currentTarget.value))} onkeydown={(event) => nudgeYear("to", event)} />
        </div>
        <div class="year-fields">
          <label>{text.yearFrom} <input type="number" min={domain.min} max={chosen.to} value={chosen.from} onchange={(event) => commitYears(Number(event.currentTarget.value), chosen.to)} /></label>
          <label>{text.yearTo} <input type="number" min={chosen.from} max={domain.max} value={chosen.to} onchange={(event) => commitYears(chosen.from, Number(event.currentTarget.value))} /></label>
        </div>
      </fieldset>
      {/if}
      <button class="clear" type="button" onclick={clearFilters}>{text.clear}</button>
    </aside>
    {#snippet pager()}
      {#if pages > 1}
        <div class="pager">
          <button type="button" disabled={page <= 1} onclick={() => turn(page - 1)} aria-label={text.previous}>←</button>
          <span>{page} / {pages}</span>
          <button type="button" disabled={page >= pages} onclick={() => turn(page + 1)} aria-label={text.next}>→</button>
        </div>
      {/if}
    {/snippet}
    {#snippet tools()}
      <div class="tools">
        <label class="sort">
          {text.perPage}
          <select value={pageSize} onchange={(event) => setPer(event.currentTarget.value)}>
            {#each pageSizes as size}
              <option value={size}>{size}</option>
            {/each}
          </select>
        </label>
        <label class="sort">
          {text.sort}
          <select value={params.get("sort") || "relevance"} onchange={(event) => setSort(event.currentTarget.value)}>
            {#each Object.entries(text.sorts) as [key, label]}
              <option value={key}>{label}</option>
            {/each}
          </select>
        </label>
        {@render pager()}
        {@render listExporter()}
      </div>
    {/snippet}
    <section>
      <form class="within" onsubmit={addWithin}>
        <input bind:value={withinBox} type="search" aria-label={text.within} placeholder={text.within} />
      </form>
      {#if query.trim() && translatable()}
        <label class="translations-switch" title={text.searchTranslationsNote}>
          <input type="checkbox" checked={withTranslations()} onchange={(event) => setTranslations(event.currentTarget.checked)} />
          {text.searchTranslations}
        </label>
      {/if}
      {#if params.getAll("place").length}
        <ul class="chips refine">
          {#each params.getAll("place") as key (key)}
            <li><button type="button" onclick={() => removePlace(key)}>{text.placeChip} <em>{placeLabel(key)}</em> <span aria-hidden="true">×</span> <span class="sr-only">{text.removeChip}</span></button></li>
          {/each}
        </ul>
      {/if}
      {#if params.get("journal")}
        <ul class="chips refine">
          <li><button type="button" onclick={removeJournal} title={text.journalGrouped}>{text.journalChip} <em>{params.get("journalTitle") || ""}</em> <span aria-hidden="true">×</span> <span class="sr-only">{text.removeChip}</span></button></li>
        </ul>
      {/if}
      {#if params.get("subject")}
        <ul class="chips refine">
          <li><button type="button" onclick={removeSubject} title={`${text.bhbCode} ${params.get("subject")}`}>{text.subjectChip} <em>{subjectTitle(params.get("subject") || "")}</em> <span aria-hidden="true">×</span> <span class="sr-only">{text.removeChip}</span></button></li>
        </ul>
      {/if}
      {#if params.get("topic")}
        <ul class="chips refine">
          <li><button type="button" onclick={removeTopic}>{text.topicsChip} <em>{topicNames[params.get("topic") || ""]?.[lang] || "…"}</em> <span aria-hidden="true">×</span> <span class="sr-only">{text.removeChip}</span></button></li>
        </ul>
      {/if}
      {#if params.get("in")}
        <ul class="chips refine">
          <li><button type="button" onclick={removeInside}>{text.inVolume} <em>{params.get("inTitle") || ""}</em> <span aria-hidden="true">×</span> <span class="sr-only">{text.removeChip}</span></button></li>
        </ul>
      {/if}
      {#if params.getAll("more").length}
        <ul class="chips refine">
          {#each params.getAll("more") as chip, index}
            <li><button type="button" onclick={() => removeMore(index)}>{chip} <span aria-hidden="true">×</span> <span class="sr-only">{text.removeChip}</span></button></li>
          {/each}
        </ul>
      {/if}
      {#if spelling.length}
        <p class="did-you-mean">{text.didYouMean} <a href={correctedHref()}>{correctedQuery()}</a>?</p>
      {/if}
      {#if loading && hits.length === 0}
        <Waiting message={text.loading} />
      {:else if missing}
        <p>{text.missing}</p>
      {:else if total === 0}
        <p>{text.empty}</p>
      {:else}
        <div class="results-head">
          <p class="count">{total.toLocaleString(lang)} {text.results}</p>
          {@render tools()}
        </div>
        {#each hits as hit}
          {@render resultRow(hit)}
        {/each}
        <div class="results-foot">{@render tools()}</div>
        {#if page === 1 && canRelate()}
          <div class="related">
            {#if relatedKey !== scopeOf(params)}
              <button type="button" class="related-button" onclick={showRelated} disabled={relatedLoading}>
                <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
                  <path d="M2.5 13.5l7.5-7.5M9 5l2 2M12 1.5v2.5M10.75 2.75h2.5M14 6v2M13 7h2M6 1.5v2M5 2.5h2" />
                </svg>
                {relatedLoading ? text.loading : text.related}
              </button>
            {:else}
              <h2>{text.related}</h2>
              <p class="similar-note">{text.relatedNote}</p>
              {#if relatedLoading}
                <Waiting message={text.loading} />
              {:else if related.length === 0}
                <p>{text.relatedNone}</p>
              {:else}
                {#each related as hit (hit.meta.id)}
                  {@render resultRow(hit)}
                {/each}
              {/if}
            {/if}
          </div>
        {/if}
      {/if}
    </section>
  </main>
{:else if path.startsWith("/similar/")}
  <main class="wrap similar">
    <p><a href="#/search?{sessionStorage.getItem("bhb-search") || ""}">{text.back}</a></p>
    <h1>{text.similar}</h1>
    {#if similarSource}
      <p class="similar-for">{text.similarFor} <a href={similarSource.url}>{@html citationHtml(similarSource.meta.citation || similarSource.meta.title, similarSource.meta, text.yearFromHost, text.volumeFromEntry, text.hostMatched, text.hostMissing, text.hostMissingNote, text.yearFromShort, text.yearNotPrinted)}</a></p>
    {/if}
    {#if loading && similarHits.length === 0}
      <Waiting message={text.loading} />
    {:else if similarHits.length === 0}
      <p>{text.similarNone}</p>
    {:else}
      {#each similarHits as item (item.hit.meta.id)}
        {@render resultRow(item.hit)}
      {/each}
    {/if}
  </main>
{:else if path === "/topics"}
  {#if TopicMap}
    <TopicMap {text} {lang} initial={params} />
  {:else}
    <main class="wrap"><Waiting message={text.topicsLoading} large /></main>
  {/if}
{:else if path === "/map"}
  <main class="wrap map-page">
    <h1>{text.map}</h1>
    <p class="similar-note">{text.mapIntro}</p>
    <nav class="map-periods" aria-label={text.periodsLabel}>
      <a href={mapHref("")} aria-current={mapPeriod === "" ? "true" : undefined}>{text.mapAllPeriods}</a>
      {#each MAP_PERIODS as period}
        <a href={mapHref(period)} aria-current={mapPeriod === period ? "true" : undefined}>{label("period", period)}</a>
      {/each}
    </nav>
    {#if mapPeriod}
      <p class="map-layer-line">
        {#if mapLayer}
          {#if mapLayer.dioceses}
            <a href={mapHref(mapPeriod, "territories")} aria-current={mapLayerKind === "territories" ? "true" : undefined}>{text.mapTerritories.replace("{y}", String(mapLayer.year))}</a>
            <a href={mapHref(mapPeriod, "dioceses")} aria-current={mapLayerKind === "dioceses" ? "true" : undefined}>{text.mapDioceses.replace("{y}", String(mapLayer.diocesesYear))}</a>
          {:else}
            <span class="map-layer-only">{text.mapTerritories.replace("{y}", String(mapLayer.year))}</span>
          {/if}
          <span class="map-layer-note">{text.mapLayerNote}</span>
        {:else}
          <span class="map-layer-note">{text.mapNoLayer}</span>
        {/if}
      </p>
    {/if}
    <div class="map-layout">
      <div class="map-frame">
      <svg
        class="map"
        viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
        role="img"
        aria-label={text.map}
        onwheel={onMapWheel}
        onpointerdown={onMapDown}
        onpointermove={onMapMove}
        onpointerup={onMapUp}
        onpointerleave={onMapUp}
      >
        {#if mapBase && mapLayer}
          {#each mapShapes as shape, index}<path class={`past-shape past-${index % 5}`} class:diocese={mapLayerKind === "dioceses"} d={shape.d} />{/each}
          <path class="base-country-now" d={mapBase.country} />
        {:else if mapBase}
          <path class="base-country" d={mapBase.country} />
          {#each mapBase.arrondissements as d}<path class="base-arrondissement" d={d} />{/each}
          {#each mapBase.regions as d}<path class="base-region" d={d} />{/each}
        {/if}
        {#each mapPlaces as place (place.key)}
          <a href={placeHref(place.key)} aria-label={`${placeName(place)}: ${place.n}`}>
            <circle
              class="place"
              class:active={mapHover?.key === place.key}
              cx={mapX(place.lon!)}
              cy={mapY(place.lat!)}
              r={(2 + Math.sqrt(place.n) * 0.9) / Math.sqrt(mapZoom)}
              role="presentation"
              onmouseenter={() => { mapHover = place; }}
              onmouseleave={() => { if (mapHover?.key === place.key) mapHover = null; }}
            ><title>{placeName(place)} — {place.n}</title></circle>
          </a>
        {/each}
        {#if mapLayer}
          {#each mapShapes.filter((shape) => shape.x !== undefined) as shape}
            <text class="past-label" class:diocese={mapLayerKind === "dioceses"} x={shape.x} y={shape.y} font-size={18 / mapZoom}>{shape[lang] || shape.en}</text>
          {/each}
        {/if}
      </svg>
      <div class="map-zoom">
        <button type="button" aria-label={text.zoomIn} title={text.zoomIn} onclick={() => zoomAt(1.6)}>+</button>
        <button type="button" aria-label={text.zoomOut} title={text.zoomOut} onclick={() => zoomAt(1 / 1.6)}>−</button>
        <button type="button" aria-label={text.zoomReset} title={text.zoomReset} onclick={() => { view = { x: 0, y: 0, w: MAP_W, h: MAP_H }; }}>⟲</button>
      </div>
      {#if mapBase}<p class="map-credit">{mapBase.credit}</p>{/if}
      {#if mapLayer && mapHistory}
        <p class="map-credit">{text.mapCreditPast}: {@html linkedCredit(mapLayerKind === "dioceses" && mapLayer.dioceses ? mapHistory.credit.dioceses : mapHistory.credit.territories)}</p>
      {/if}
      </div>
      <aside class="map-side">
        {#if mapHover}
          <p class="map-hover"><strong>{placeName(mapHover)}</strong><br />{mapHover.n.toLocaleString(lang)} {text.results}</p>
        {:else}
          <p class="map-hover">{text.mapHint}</p>
        {/if}
        <h2>{text.mapTop}</h2>
        <ol class="map-list">
          {#each mapPlaces.slice(0, 12) as place (place.key)}
            <li><a href={placeHref(place.key)}>{placeName(place)}</a> <span class="tree-count">{place.n.toLocaleString(lang)}</span></li>
          {/each}
        </ol>
        <h2>{text.mapElsewhere}</h2>
        <ul class="map-list">
          {#each mapElsewhere.slice(0, 20) as place (place.key)}
            <li><a href={placeHref(place.key)}>{placeName(place)}</a> <span class="tree-count">{place.n.toLocaleString(lang)}</span></li>
          {/each}
        </ul>
      </aside>
    </div>
  </main>
{:else if path === "/browse"}
  <main class="wrap browse">
    <h1>{text.browse}</h1>
    <p class="similar-note">{text.browseIntro}</p>
    <ul class="tree">
      {#each childrenOf.get("") || [] as code (code)}{@render subjectNode(code)}{/each}
    </ul>
  </main>
{:else if path === "/about"}
  <main class="wrap about">
    <h1>{text.aboutTitle}</h1>
    {#each text.aboutSections as section}
      <h2>{section.title}</h2>
      {#each section.paragraphs as paragraph}
        <p>{@html paragraph}</p>
      {/each}
    {/each}
  </main>
{:else}
  <main class="home">
    {#if missing}<p>{text.missing}</p>{/if}
    <h1>{text.name}</h1>
    <p>{text.tagline}</p>
    <form class="search" onsubmit={submit}>
      {@render fieldSelect()}
      <input bind:value={query} type="search" placeholder={text.placeholder} aria-label={text.search} />
      <button type="submit">{text.search}</button>
    </form>
    <p class="about-link"><a href="#/browse">{text.browse}</a> · <a href="#/about">{text.aboutTitle}</a></p>
  </main>
{/if}

<footer>
  <div class="footer">
    <img class="crest" src={asset("crh-logo-footer.svg")} alt="" />
    <div>
      <h2>{text.commission}</h2>
      {#each text.address as line}
        <p>{line}</p>
      {/each}
      <p><a href="tel:+3225502206">{text.phone}</a></p>
      <p><a href="mailto:jeanluc.depaepe@gmail.com">{text.email}</a></p>
      <p class="credit">{text.team}</p>
      <p class="credit">{text.attribution}</p>
    </div>
    <div>
      <p class="support">{text.support}</p>
      <div class="marks">
        <img src={asset("marks/kvab.png")} alt="KVAB" />
        <img src={asset("marks/arb.png")} alt="ARB" />
        <img src={asset("marks/belspo.png")} alt="BELSPO" />
        <img src={asset("marks/rijksarchief.png")} alt="Rijksarchief" />
      </div>
    </div>
  </div>
  <div class="legal">
    <span class="legend"><span class="tag tag-suggested">{text.suggestedSample}</span> {text.suggestedLegend}</span>
    <span class="legend"><span class="tag tag-narrow">{text.narrowerSample}</span> {text.narrowerLegend}</span>
    <span class="legend"><sup class="note-mark">*</sup> = {text.parsedByModel}</span>
    <span>{text.copyright}</span>
    <a href="#/about" aria-current={path === "/about" ? "true" : undefined}>{text.about}</a>
    <a href={text.privacyUrl}>{text.privacy}</a>
    <a href={text.accessibilityUrl}>{text.accessibility}</a>
  </div>
</footer>
