import { afterEach, describe, expect, it, vi } from "vitest";
import { isStaleAssetError } from "../src/utils/lazyWithReload";

/**
 * Recognising a stale-chunk failure.
 *
 * A tab open across a deploy requests chunk hashes from the index.html it loaded, and those files
 * are gone. The page then died with "Unable to preload CSS for /assets/index-<old>.css" — which
 * reads like a CSS bug and is entirely a caching problem. Getting that page back needs a reload,
 * so the failure has to be recognised; a genuine bug must NOT be, or a broken page would reload
 * in a loop instead of showing its error.
 */
describe("isStaleAssetError", () => {
  it("recognises the failures a deploy causes", () => {
    const stale = [
      new Error("Unable to preload CSS for /assets/index-BnuhLJ6X.css"),
      new Error("Loading chunk 5 failed."),
      new Error("Loading CSS chunk 5 failed."),
      new Error(
        "Failed to fetch dynamically imported module: http://x/assets/index-abc.js",
      ),
      Object.assign(new Error("boom"), { name: "ChunkLoadError" }),
    ];
    for (const error of stale) {
      expect(isStaleAssetError(error), error.message).toBe(true);
    }
  });

  it("does not treat a real bug as a stale asset", () => {
    const genuine = [
      new Error("Cannot read properties of undefined (reading 'nodes')"),
      new Error("React Flow: parent container has no dimensions"),
      new TypeError("x is not a function"),
      new Error("审核提交失败 (500)"),
    ];
    for (const error of genuine) {
      expect(isStaleAssetError(error), error.message).toBe(false);
    }
  });

  it("survives non-Error rejections", () => {
    expect(isStaleAssetError("Loading chunk 3 failed.")).toBe(true);
    expect(isStaleAssetError({})).toBe(false);
    expect(isStaleAssetError(null)).toBe(false);
  });
});
