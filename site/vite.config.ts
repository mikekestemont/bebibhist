import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [svelte()],
  // Relative so the same build works at /bebibhist/ and on a later custom domain.
  // Hash routing keeps the document at index.html, so ./ resolves there.
  base: "./",
  server: {
    port: 5173,
    // The Pagefind index is hundreds of megabytes. Watching it makes the dev server spin.
    watch: { ignored: ["**/public/pagefind/**"] },
  },
});
