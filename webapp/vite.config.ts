import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      host: true,
      // Telegram opens the Mini App through an HTTPS tunnel (see README); allow its host.
      allowedHosts: true,
      proxy: {
        "/api": { target: env.VESTNIO_API_PROXY || "http://127.0.0.1:8000", changeOrigin: true },
      },
    },
    build: {
      target: "es2020",
      cssMinify: true,
      sourcemap: false,
      rollupOptions: {
        output: {
          manualChunks: { react: ["react", "react-dom"], query: ["@tanstack/react-query"] },
        },
      },
    },
  };
});
