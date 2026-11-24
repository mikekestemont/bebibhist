// The search in a worker of its own. Pagefind computes a search on the thread that calls it, and on the page's thread
// that froze the page and its hourglass. Here it computes apart, and the page asks it by message (search.ts,
// ``workerSearcher``). Pagefind's page-only code (the page's language, its address) is guarded, so it runs in a worker
// as it is; the index is the one language "und".
import { createSearcher, type PagefindModule, type Searcher } from "./searcher.ts";

let searcher: Searcher | null = null;

self.onmessage = async (event: MessageEvent<{ id: number; method: string; args: unknown[] }>) => {
  const { id, method, args } = event.data;
  try {
    let value: unknown = null;
    if (method === "load") {
      const url = args[0] as string;
      searcher = createSearcher((await import(/* @vite-ignore */ url)) as PagefindModule, url.replace(/pagefind\.js$/, ""));
    } else {
      value = await (searcher as unknown as Record<string, (...args: unknown[]) => Promise<unknown>>)[method](...args);
    }
    self.postMessage({ id, value });
  } catch (error) {
    self.postMessage({ id, error: String(error) });
  }
};
