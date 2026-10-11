<script lang="ts">
  import { onMount } from "svelte";
  import en from "./i18n/en.json";
  import fr from "./i18n/fr.json";
  import nl from "./i18n/nl.json";
  import { EXPORT_CAP, saveExport, saveExports, type ExportKind } from "./lib/export";
  import { authorsWithout, citationHtml, editorsBeforeHost, findRecord, loadEngine, searchQuery, type Hit } from "./lib/search";

  type Lang = "fr" | "nl" | "en";
  const catalogs = { fr, nl, en };
  const groups = {
    period: ["aux", "general", "ancient", "medieval", "burgundian", "early-modern", "contemporary"],
    type: ["article", "chapter", "book", "journal-issue", "other"],
    source: ["print-straive", "print-pdf", "vsmart"],
    decade: ["1950", "1960", "1970", "1980", "1990", "2000", "2010"],
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
  let exporting = $state(false);
  let listed: { data: () => Promise<Hit> }[] = [];

  let page = $derived(Math.max(1, Number(params.get("page") || "1")));
  let pages = $derived(Math.max(1, Math.ceil(total / 20)));
  let filtering = $derived(path === "/search");

  function initialLang(): Lang {
    const stored = localStorage.getItem("bhb-lang");
    if (stored === "fr" || stored === "nl" || stored === "en") return stored;
    const browser = navigator.language.slice(0, 2);
    return browser === "nl" || browser === "en" ? browser : "fr";
  }

  function label(group: keyof typeof groups, value: string): string {
    if (group === "period") return text.periods[value as keyof typeof text.periods] || value;
    if (group === "type") return text.types[value as keyof typeof text.types] || value;
    if (group === "source") return text.sources[value as keyof typeof text.sources] || value;
    return value;
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
    if (!query && path.startsWith("/record/")) {
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
    const response = await engine.search(query.trim() ? searchQuery(query) : null, {
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
    const slice = response.results.slice((page - 1) * 20, page * 20);
    hits = await Promise.all(slice.map((item) => item.data()));
    remember(hits);
    loading = false;
  }

  function scopeOf(search: URLSearchParams): string {
    const copy = new URLSearchParams(search);
    copy.delete("page");
    copy.delete("sort");
    return copy.toString();
  }

  function sortOf(value: string | null): Record<string, "asc" | "desc"> | undefined {
    const [key, direction] = (value || "").split("-");
    if ((key === "pubyear" || key === "year" || key === "author" || key === "title") && (direction === "asc" || direction === "desc")) {
      return { [key]: direction };
    }
    return undefined;
  }

  function setSort(value: string) {
    const next = new URLSearchParams(params);
    if (!value || value === "relevance") next.delete("sort");
    else next.set("sort", value);
    next.delete("page");
    go("/search", next);
  }

  function rows(hit: Hit): { label: string; value: string; italic?: boolean }[] {
    const meta = hit.meta;
    const hostLabel = meta.kind === "article" ? text.journal : text.host;
    const work = meta.kind === "book" || meta.kind === "journal-issue";
    const editors = meta.hostEditors?.trim() || editorsBeforeHost(meta.citation || "", meta.host);
    const pairs: [string, string | undefined, boolean?][] = [
      [text.author, authorsWithout(meta.authors, editors)],
      [text.fieldTitle, meta.title, work],
      [text.subtitle, meta.subtitle ? capitalize(meta.subtitle) : undefined, work],
      [hostLabel, meta.host, true],
      [text.hostSubtitle, meta.hostSubtitle ? capitalize(meta.hostSubtitle) : undefined, true],
      [text.hostEditors, editors],
      [text.volume, meta.volume],
      [text.issue, meta.issue],
      [text.pages, meta.pages],
      [text.pubyear, meta.pubyear],
      [text.place, meta.place],
      [text.publisher, meta.publisher],
      [text.extent, meta.extent],
      [text.type, meta.kind ? text.types[meta.kind as keyof typeof text.types] || meta.kind : ""],
    ];
    return pairs.flatMap(([label, value, italic]) => (value ? [{ label, value, italic }] : []));
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

  function submit(event: SubmitEvent) {
    event.preventDefault();
    const next = new URLSearchParams(path === "/search" ? params : undefined);
    next.set("q", query);
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

  function example(value: string) {
    query = value;
    go("/search", new URLSearchParams({ q: value }));
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
    <img src="/crh-logo.svg" alt="" />
    <strong>{text.name}</strong>
  </a>
  {#if filtering || path.startsWith("/record/") || path === "/about"}
    <form class="search" onsubmit={submit}>
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
      <p class="citation">{@html citationHtml(record.meta.citation || record.meta.title, record.meta)}</p>
      <div class="record-export">{@render exporter(record)}</div>
      {#if rows(record).length}
        <dl class="fields">
          {#each rows(record) as row}
            <div>
              <dt>{row.label}</dt>
              <dd>{#if row.italic}<em>{row.value}</em>{:else}{row.value}{/if}</dd>
            </div>
          {/each}
        </dl>
      {/if}
      {#if record.meta.section}<p><span class="theme">{text.theme}</span> {record.meta.section}</p>{/if}
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
          <legend>{text[group as "period" | "type" | "source" | "decade"]}</legend>
          {#each values as value}
            {@const count = counts[group]?.[value] ?? 0}
            <label>
              <input type="checkbox" checked={selected(group, value)} onchange={() => toggle(group, value)} />
              <span>{label(group as keyof typeof groups, value)}{#if count} <em>{count.toLocaleString(lang)}</em>{/if}</span>
            </label>
          {/each}
        </fieldset>
      {/each}
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
          <a class="result" href={hit.url}>
            <span class="citation">{@html citationHtml(hit.meta.citation || hit.meta.title, hit.meta)}</span>
          </a>
        {/each}
        <div class="results-foot">{@render tools()}</div>
      {/if}
    </section>
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
      <input bind:value={query} type="search" placeholder={text.placeholder} aria-label={text.search} />
      <button type="submit">{text.search}</button>
    </form>
    <ul class="chips">
      {#each text.examples as sample}
        <li><button type="button" onclick={() => example(sample)}>{sample}</button></li>
      {/each}
    </ul>
    <p class="about-link"><a href="#/about">{text.aboutTitle}</a></p>
  </main>
{/if}

<footer>
  <div class="footer">
    <img class="crest" src="/crh-logo-footer.svg" alt="" />
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
        <img src="/marks/kvab.png" alt="KVAB" />
        <img src="/marks/arb.png" alt="ARB" />
        <img src="/marks/belspo.png" alt="BELSPO" />
        <img src="/marks/rijksarchief.png" alt="Rijksarchief" />
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
