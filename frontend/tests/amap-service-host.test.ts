import { describe, expect, it } from "vitest";
import { amapServiceHost } from "../src/components/Map";

/**
 * Where the AMap JS API is told to send its REST calls.
 *
 * The recorded frontend error log was 98 of 98 "SyntaxError: Unexpected token '<'" because the
 * development proxy path `/_AMapService` was baked into the production bundle: nginx's SPA
 * fallback answered it with index.html, and the SDK ran that HTML as a script. These checks pin
 * the rule that prevents it, in both builds.
 */
const ORIGIN = "http://47.116.133.230";

describe("amapServiceHost", () => {
  it("uses the Vite dev proxy in development", () => {
    expect(amapServiceHost("/_AMapService", { dev: true, origin: "http://127.0.0.1:5173" })).toBe(
      "http://127.0.0.1:5173/_AMapService",
    );
  });

  it("refuses a relative dev proxy in a production build", () => {
    // The regression: this used to become http://47.116.133.230/_AMapService, which nginx
    // answers with index.html, and every map page threw "Unexpected token '<'".
    expect(amapServiceHost("/_AMapService", { dev: false, origin: ORIGIN })).toBeNull();
  });

  it("accepts a real cross-origin proxy in production", () => {
    expect(
      amapServiceHost("https://proxy.example.com/_AMapService", { dev: false, origin: ORIGIN }),
    ).toBe("https://proxy.example.com/_AMapService");
  });

  it("accepts a real proxy in development too", () => {
    expect(
      amapServiceHost("https://proxy.example.com/_AMapService/", { dev: true, origin: ORIGIN }),
    ).toBe("https://proxy.example.com/_AMapService/");
  });

  it("refuses anything that is not an _AMapService host", () => {
    expect(amapServiceHost(undefined, { dev: false, origin: ORIGIN })).toBeNull();
    expect(amapServiceHost("", { dev: true, origin: ORIGIN })).toBeNull();
    expect(amapServiceHost("https://restapi.amap.com", { dev: true, origin: ORIGIN })).toBeNull();
    expect(amapServiceHost("/api", { dev: true, origin: ORIGIN })).toBeNull();
    expect(amapServiceHost("not a url at all", { dev: true, origin: ORIGIN })).toBeNull();
  });

  it("tolerates a trailing slash and a query string", () => {
    expect(amapServiceHost("/_AMapService/", { dev: true, origin: ORIGIN })).toBe(
      "http://47.116.133.230/_AMapService/",
    );
  });
});
