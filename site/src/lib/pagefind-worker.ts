// Pagefind in a worker of its own. Pagefind computes a search on the thread that calls it, for seconds on a search
// such as "gent" over the whole bibliography; on the page's thread that froze the page and its hourglass. Here it
// computes apart, and the page asks it by message (search.ts, ``workerPagefind``). Pagefind's page-only code (the
// page's language, its address) is guarded, so it runs in a worker as it is; the index is the one language "und".

type Result = { id: string; score?: number; data: () => Promise<unknown> };
type Pagefind = Record<string, (...args: unknown[]) => Promise<unknown>>;

let pagefind: Pagefind | null = null;
// The results of every search so far, by Pagefind's id, so the page can ask for a result's data later.
const results = new Map<string, Result>();

self.onmessage = async (event: MessageEvent<{ id: number; method: string; args: unknown[] }>) => {
  const { id, method, args } = event.data;
  try {
    let value: unknown = null;
    if (method === "load") {
      pagefind = (await import(/* @vite-ignore */ args[0] as string)) as Pagefind;
    } else if (method === "search") {
      const response = (await pagefind!.search(...args)) as { results: Result[]; filters?: unknown };
      for (const result of response.results) results.set(result.id, result);
      value = { results: response.results.map(({ id: key, score }) => ({ id: key, score })), filters: response.filters };
    } else if (method === "data") {
      value = await results.get(args[0] as string)?.data();
    } else {
      value = await pagefind![method](...args);
    }
    self.postMessage({ id, value });
  } catch (error) {
    self.postMessage({ id, error: String(error) });
  }
};
