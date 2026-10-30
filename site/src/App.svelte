<script lang="ts">
  import { onMount } from "svelte";
  import en from "./i18n/en.json";
  import fr from "./i18n/fr.json";
  import nl from "./i18n/nl.json";
  import { EXPORT_CAP, saveExport, saveExports, type ExportKind } from "./lib/export";
  import { authorsWithout, citationHtml, editorsBeforeHost, findRecord, loadEngine, relaxedQuery, searchBoth, searchQuery, similarOf, type Hit, type SearchField } from "./lib/search";

  const asset = (file: string) => `${import.meta.env.BASE_URL}${file}`;

  type Lang = "fr" | "nl" | "en";
  const catalogs = { fr, nl, en };
  const groups = {
    period: ["aux", "general", "ancient", "medieval", "burgundian", "early-modern", "contemporary"],
    theme: ["reference", "general", "local", "political", "economic", "social", "religious", "cultural", "unclassified"],
    type: ["article", "chapter", "book", "journal-issue", "other"],
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
  let fieldChoice = $state("all");
  let dragFrom = $state<number | null>(null);
  let dragTo = $state<number | null>(null);
  let openId = $state("");
  let withinBox = $state("");

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
    return value;
  }

  function categoryOf(hit: Hit): string {
    const meta = hit.meta;
    const byLang = lang === "nl" ? meta.categoryNl : lang === "en" ? meta.categoryEn : meta.categoryFr;
    if (byLang) return byLang;
    if (meta.categoryTheme) return text.themes[meta.categoryTheme as keyof typeof text.themes] || meta.categoryTheme;
    return meta.categoryFr || meta.categoryNl || meta.categoryEn || "";
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

  function activeFilters(): Record<string, string[]> | undefined {
    const filters: Record<string, string[]> = {};
    for (const group of Object.keys(groups)) {
      const values = params.getAll(group);
      if (values.length) filters[group] = values;
    }
    const from = Number(params.get("from"));
    const to = Number(params.get("to"));
    if (from || to) {
      const start = Math.min(from || 1945, to || new Date().getFullYear());
      const end = Math.max(from || 1945, to || new Date().getFullYear());
      const years: string[] = [];
      for (let year = start; year <= end; year += 1) years.push(String(year));
      filters.pubyear = years;
    }
    return Object.keys(filters).length ? filters : undefined;
  }

  async function refresh() {
    if (!engine) return;
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
    if (path !== "/search") {
      hits = [];
      listed = [];
      if (!path.startsWith("/record/")) record = null;
      total = 0;
      loading = false;
      return;
    }
    sessionStorage.setItem("bhb-search", params.toString());
    if (hits.length === 0) loading = true;
    const filters = activeFilters();
    const sort = sortOf(params.get("sort"));
    const askedText = [query, ...params.getAll("more")].map((part) => part.trim()).filter(Boolean).join(" ");
    const inside = params.get("in");
    const field = searchField(fieldChoice);
    const within = inside ? `hk_${inside}` : "";
    const asked = [askedText ? searchQuery(askedText, field) : "", within].filter(Boolean).join(" ") || null;
    const relaxed = askedText ? relaxedQuery(askedText, field) : null;
    const loose = relaxed ? [relaxed, within].filter(Boolean).join(" ") : null;
    const response = await searchBoth(engine, asked, loose, {
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
    if (filters?.pubyear) {
      const rest = { ...filters };
      delete rest.pubyear;
      const broad = await engine.search(loose || asked, {
        ...(Object.keys(rest).length ? { filters: rest } : {}),
        ...(sort ? { sort } : {}),
      });
      yearCounts = { ...(broad.filters?.pubyear || {}) };
    } else {
      yearCounts = { ...(response.filters?.pubyear || {}) };
    }
    const slice = response.results.slice((page - 1) * pageSize, page * pageSize);
    hits = await Promise.all(slice.map((item) => item.data()));
    remember(hits);
    loading = false;
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

  function rows(hit: Hit): { label: string; value: string; italic?: boolean; authors?: boolean; derived?: string; container?: string }[] {
    const meta = hit.meta;
    const hostLabel = meta.kind === "article" ? text.journal : text.host;
    const work = meta.kind === "book" || meta.kind === "journal-issue";
    const editors = meta.hostEditors?.trim() || editorsBeforeHost(meta.citation || "", meta.host);
    const pairs: [string, string | undefined, boolean?][] = [
      [text.author, authorsWithout(meta.authors, editors)],
      // A collected volume's own editors; a chapter's editors are its host's, below.
      [text.hostEditors, meta.editors],
      [text.fieldTitle, meta.title, work],
      [text.subtitle, meta.subtitle ? capitalize(meta.subtitle) : undefined, work],
      [hostLabel, meta.host, true],
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
            derived: derivedNote(label, meta),
            container: containerLink(label, meta),
          }]
        : [],
    );
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

  function removeInside() {
    const next = new URLSearchParams(params);
    next.delete("in");
    next.delete("inTitle");
    next.delete("page");
    go("/search", next);
  }

  function derivedNote(label: string, meta: Hit["meta"]): string | undefined {
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
    go("/search", next);
  }

  function turn(nextPage: number) {
    const next = new URLSearchParams(params);
    next.set("page", String(nextPage));
    go("/search", next);
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
      readRoute();
      void refresh();
    };
    window.addEventListener("hashchange", onHash);
    window.addEventListener("popstate", onHash);
    readRoute();
    loadEngine()
      .then((loaded) => {
        engine = loaded;
        return refresh();
      })
      .catch(() => {
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

{#snippet fieldValue(row: { value: string; italic?: boolean; authors?: boolean; derived?: string; container?: string })}
  {#if row.container}
    <a class="container-link" href={row.container} title={text.containerWhy}>{#if row.italic}<em>{row.value}</em>{:else}{row.value}{/if}</a>
  {:else if row.authors}
    {@const names = authorParts(row.value)}
    {#each names as name, index}
      {#if index > 0}{index === names.length - 1 ? " & " : ", "}{/if}<a class="author-link" href={"#/search?q=" + encodeURIComponent(name) + "&field=author"} title={text.authorMatch}>{name}</a>
    {/each}
  {:else if row.italic}
    <em>{row.value}</em>
  {:else if row.derived}
    <span class="derived" title={row.derived}>{row.value}</span>
  {:else}
    {row.value}
  {/if}
{/snippet}

{#snippet categoryBlock(hit: Hit)}
  {@const category = categoryOf(hit)}
  <p class="category-line">
    <span class="theme">{text.category}</span>
    {category || text.themes.unclassified}
    {#if category && hit.meta.categoryDraft === "1" && lang === "en"} <span class="suggested">{text.draftLabel}</span>{/if}
    {#if category && hit.meta.categoryMachine === "1"}
      <span class="suggested" title={text.suggestedWhy[hit.meta.categorySource as keyof typeof text.suggestedWhy] || text.suggestedWhy.classifier}>{text.suggested}</span>
    {/if}
  </p>
{/snippet}

{#snippet fieldSelect()}
  <select class="field" aria-label={text.fieldSearch} value={fieldChoice} onchange={(event) => setField(event.currentTarget.value)}>
    <option value="all">{text.fields.all}</option>
    <option value="author">{text.fields.author}</option>
    <option value="title">{text.fields.title}</option>
    <option value="host">{text.fields.host}</option>
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

{#snippet resultRow(hit: Hit)}
  {@const open = openId === hit.meta.id}
  <article class="result">
    <button type="button" class="result-toggle" aria-expanded={open} onclick={() => { openId = open ? "" : hit.meta.id; }}>
      {@render typeIcon(hit.meta.kind)}
      <span class="citation">{@html citationHtml(hit.meta.citation || hit.meta.title, hit.meta, text.yearFromHost, text.volumeFromEntry)}</span>
      <svg class="chevron" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M4 6l4 4 4-4" /></svg>
    </button>
    {#if open}
      <div class="expanded">
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
        {#if hit.meta.section}<p><span class="theme">{text.printedTheme}</span> {hit.meta.section}</p>{/if}
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
  <nav class="langs">
    {#each ["fr", "nl", "en"] as code}
      <button type="button" aria-current={lang === code ? "true" : undefined} onclick={() => choose(code as Lang)}>{code.toUpperCase()}</button>
    {/each}
  </nav>
</header>
<p class="banner">{text.beta}</p>

{#if path.startsWith("/record/")}
  <main class="wrap">
    <p><a href="#/search?{sessionStorage.getItem("bhb-search") || ""}">{text.back}</a></p>
    {#if loading}
      <p>{text.loading}</p>
    {:else if record}
      <h1>
        {#if record.meta.kind === "book" || record.meta.kind === "journal-issue"}<em>{record.meta.title}</em>{:else}{record.meta.title}{/if}
      </h1>
      <p class="citation">{@html citationHtml(record.meta.citation || record.meta.title, record.meta, text.yearFromHost, text.volumeFromEntry)}</p>
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
      {#if record.meta.section}<p><span class="theme">{text.printedTheme}</span> {record.meta.section}</p>{/if}
      <p class="imprint">{text.printed}{record.meta.year ? ` · BGB ${record.meta.year}` : ""}{record.meta.number ? ` · ${record.meta.number}` : ""}</p>
    {:else}
      <p>{text.notFound}</p>
    {/if}
  </main>
{:else if filtering}
  <main class="wrap layout">
    <aside class="filters">
      <h2>{text.filters}</h2>
      {#each Object.entries(groups) as [group, values]}
        <fieldset>
          <legend>{text[group as "period" | "theme" | "type"]}</legend>
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
        <svg class="hist" viewBox="0 0 100 32" aria-hidden="true">
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
      {#if loading && hits.length === 0}
        <p>{text.loading}</p>
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
      {/if}
    </section>
  </main>
{:else if path.startsWith("/similar/")}
  <main class="wrap similar">
    <p><a href="#/search?{sessionStorage.getItem("bhb-search") || ""}">{text.back}</a></p>
    <h1>{text.similar}</h1>
    {#if similarSource}
      <p class="similar-for">{text.similarFor} <a href={similarSource.url}>{@html citationHtml(similarSource.meta.citation || similarSource.meta.title, similarSource.meta, text.yearFromHost, text.volumeFromEntry)}</a></p>
    {/if}
    <p class="similar-note">{text.similarNote}</p>
    {#if loading && similarHits.length === 0}
      <p>{text.loading}</p>
    {:else if similarHits.length === 0}
      <p>{text.similarNone}</p>
    {:else}
      {#each similarHits as item (item.hit.meta.id)}
        {@render resultRow(item.hit)}
      {/each}
    {/if}
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
    <p class="about-link"><a href="#/about">{text.aboutTitle}</a></p>
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
    <span>{text.copyright}</span>
    <a href="#/about" aria-current={path === "/about" ? "true" : undefined}>{text.about}</a>
    <a href={text.privacyUrl}>{text.privacy}</a>
    <a href={text.accessibilityUrl}>{text.accessibility}</a>
  </div>
</footer>
