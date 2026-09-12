import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const apiTarget = process.env.F8_API_PROXY_TARGET ?? "http://127.0.0.1:9001";

const MAPLIBRE_CSS = "maplibre-gl/dist/maplibre-gl.css";
const EMPTY_MODULE = "\0f8-empty-module";

/**
 * plotly.js's registry requires the MapLibre stylesheet inside an `if` that
 * only runs for map traces. Bundlers cannot see the condition, so 65 kB of map
 * CSS would ship with every chart page. We register no map traces
 * (src/components/Plot.ts), so resolve it to nothing.
 */
function dropUnusedPlotlyCss(): Plugin {
  return {
    name: "f8-drop-unused-plotly-css",
    enforce: "pre",
    resolveId(id) {
      return id === MAPLIBRE_CSS ? EMPTY_MODULE : null;
    },
    load(id) {
      return id === EMPTY_MODULE ? "export default {};" : null;
    },
  };
}

const VENDOR_CHUNKS: Array<[name: string, pattern: RegExp]> = [
  ["react", /[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom|@remix-run)[\\/]/],
  ["mantine", /[\\/]node_modules[\\/](@mantine|@floating-ui)[\\/]/],
  ["tanstack", /[\\/]node_modules[\\/]@tanstack[\\/]/],
  ["plotly", /[\\/]node_modules[\\/](plotly\.js|react-plotly\.js)[\\/]/],
];

export default defineConfig({
  plugins: [react(), dropUnusedPlotlyCss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Libraries change far less often than pages: separate chunks keep
        // them cached across deploys. Plotly is only fetched by chart pages.
        manualChunks(id) {
          for (const [name, pattern] of VENDOR_CHUNKS) {
            if (pattern.test(id)) return name;
          }
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
});
