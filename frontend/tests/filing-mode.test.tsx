import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PlatformProvider } from "../src/hooks/usePlatform";
import { sampleDataset } from "../src/services/repository";
import App from "../src/App";
import { ENTERPRISE_ACCOUNT } from "./fixtures";

/**
 * The ICP filing review needs a non-commercial information site: no plan page, no paid workflow,
 * no login/register, no commercial copy. FILING_MODE is a build-time switch (frontend/src/config.ts)
 * so the same codebase can be rebuilt as the normal product after the filing is approved.
 */
vi.mock("../src/config", () => ({
  FILING_MODE: true,
  SITE_TAGLINE: "苏州城市活动信息",
  SITE_SHORT: "城市活动信息",
  SITE_TITLE: "Menduner · 城市活动信息",
}));
vi.mock("@amap/amap-jsapi-loader", () => ({
  default: { load: vi.fn().mockRejectedValue(new Error("offline")) },
}));
vi.mock("echarts", () => ({
  init: () => ({
    setOption: vi.fn(),
    on: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  }),
}));

afterEach(cleanup);

function mount(path: string) {
  return render(
    <MemoryRouter initialEntries={[withDemo(path)]}>
      <PlatformProvider initialDataset={sampleDataset}>
        <App initialAccount={ENTERPRISE_ACCOUNT} />
      </PlatformProvider>
    </MemoryRouter>,
  );
}

/** 演示数据默认关闭；测试用的 sampleDataset 本身是演示夹具，所以在测试里显式打开。 */
function withDemo(path: string): string {
  return path + (path.includes("?") ? "&" : "?") + "demo=1";
}

describe("ICP filing mode", () => {
  it("shows only the public information pages, with no commercial entry points", async () => {
    mount("/map");
    await screen.findByRole("heading", { name: "城市活动地图" });
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("套餐与升级");
    expect(text).not.toContain("酒店活动情报");
    expect(text).not.toContain("商圈洞察");
    expect(text).not.toContain("登录 / 注册");
    expect(text).toContain("公开活动信息展示");
    // The tab title now names the current view; the site name must still be in it.
      expect(document.title).toContain("城市活动信息");
  });

  it("redirects commercial routes to the public map", async () => {
    mount("/plans");
    await screen.findByRole("heading", { name: "城市活动地图" });
    expect(document.body.textContent).not.toContain("¥980");
  });
});
