import { loadEnv, type ProxyOptions } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
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
      proxy: {
        "/api": {
          target: "http://127.0.0.1:8000",
          changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/api/, ""),
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
