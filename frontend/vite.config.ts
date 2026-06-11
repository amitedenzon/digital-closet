import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/sync": "http://localhost:8000",
      "/items": "http://localhost:8000",
      "/orders": "http://localhost:8000",
      "/images": "http://localhost:8000",
    },
  },
});
