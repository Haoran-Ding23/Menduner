import { loadEnv, type ProxyOptions } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // Where /api goes. Defaults to the local backend, but pointing it at the deployed API lets a
  // dev session run on real data, so the interface is designed against what production actually
  // holds rather than against a locally drifted copy of it.
  const apiTarget = env.MENDUNER_API_TARGET || "http://127.0.0.1:8000";
  const secureProxy = (target: string): ProxyOptions => ({
    target,
    changeOrigin: true,
    secure: true,
    rewrite: (path) => path.replace(/^\/_AMapService/, ""),
    configure: (proxy) => {
      proxy.on("proxyReq", (outgoing) => {
        const url = new URL(outgoing.path, "https://placeholder.invalid");
        url.searchParams.set("jscode", env.AMAP_SECURITY_CODE);
        outgoing.path = url.pathname + url.search;
      });
    },
  });
  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      // Editors that write in place leave short-lived <file>.<pid>.<uuid>.tmpdir directories
      // beside the file they are editing. Chokidar tries to watch them, hits EBUSY on Windows
      // when the writer still holds the handle, and the whole dev server exits on the watcher
      // error - so an edit kills HMR instead of triggering it. They are never sources.
      watch: { ignored: ["**/*.tmpdir/**"] },
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
          // The local backend serves /status; the deployed API is reached through nginx, which
          // serves it as /api/status. So the prefix is stripped only when talking to a local
          // backend — stripping it against a deployed host would request /status from nginx,
          // which answers with the SPA rather than the API.
          rewrite: (path: string) =>
            apiTarget.includes("127.0.0.1") || apiTarget.includes("localhost")
              ? path.replace(/^\/api/, "")
              : path,
          // The backend requires an authenticated caller for writes. In production nginx sets
          // this header from its basic-auth login; the dev server can play the same role when
          // MENDUNER_WRITE_LOGIN is set in .env.local. Without it, local writes are refused
          // (401) exactly like an anonymous request to the deployed API — set the variable to
          // keep working on the review pages locally.
          headers: env.MENDUNER_WRITE_LOGIN
            ? { "X-Menduner-Login": env.MENDUNER_WRITE_LOGIN }
            : {},
        },
        ...(env.AMAP_SECURITY_CODE
          ? {
              "/_AMapService/v4/map/styles": secureProxy(
                "https://webapi.amap.com",
              ),
              "/_AMapService": secureProxy("https://restapi.amap.com"),
            }
          : {}),
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./tests/setup.ts"],
      include: ["tests/**/*.test.{ts,tsx}"],
      testTimeout: 30000,
    },
  };
});
