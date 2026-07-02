import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const apiTarget = process.env.F8_API_PROXY_TARGET ?? "http://127.0.0.1:9001";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
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
