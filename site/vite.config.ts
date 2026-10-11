import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [svelte()],
  // Relative so the same build works at /bebibhist/ and on a later custom domain.
  // Hash routing keeps the document at index.html, so ./ resolves there.
  base: "./",
  server: { port: 5173 },
});
