import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  base: "/",
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8787",
        changeOrigin: true,
        // The default proxy handles event-streams (SSE) fine; no buffering tweaks needed.
      },
    },
  },
  build: {
    outDir: "../backend/advanced_web_search/web",
    emptyOutDir: true,
  },
});
