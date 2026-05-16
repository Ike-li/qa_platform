import path from "path"
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return
          }

          if (id.includes("@tanstack/react-query")) {
            return "query"
          }

          if (id.includes("recharts")) {
            return "charts"
          }

          if (id.includes("@radix-ui")) {
            return "ui"
          }

          if (
            id.includes("react") ||
            id.includes("react-dom") ||
            id.includes("react-router-dom")
          ) {
            return "vendor"
          }
        },
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 3000,
    proxy: {
      "/api/v1": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
})
