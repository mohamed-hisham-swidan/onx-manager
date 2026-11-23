import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

const backendPort = process.env.ONX_BACKEND_PORT || "8000";
const backendHttp = `http://localhost:${backendPort}`;
const backendWs = `ws://localhost:${backendPort}`;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    emptyOutDir: false,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    proxy: {
      "/ws": { target: backendWs, ws: true },
      "/api": { target: backendHttp },
      "/health": { target: backendHttp },
      "/docs": { target: backendHttp },
      "/openapi.json": { target: backendHttp },
    },
  },
});
