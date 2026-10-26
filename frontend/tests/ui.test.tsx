import { sampleDataset } from "../src/services/repository";
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PlatformProvider } from "../src/hooks/usePlatform";
import App from "../src/App";
import { ENTERPRISE_ACCOUNT } from "./fixtures";
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
        {/* These pages exercise the PAID workflow (hotel intelligence / district insights), so the
            active enterprise account is seeded; tests/plans.test.tsx covers the locked states. */}
        <App initialAccount={ENTERPRISE_ACCOUNT} />
      </PlatformProvider>
    </MemoryRouter>,
  );
}
/** 演示数据默认关闭；测试用的 sampleDataset 本身是演示夹具，所以在测试里显式打开。 */
function withDemo(path: string): string {
  return path + (path.includes("?") ? "&" : "?") + "demo=1";
}

describe("Integrated platform routes and interactions", () => {
  for (const [route, title] of [
    ["map", "城市活动地图"],
    ["calendar", "活动日历"],
    ["graph", "知识图谱"],
    ["hotels", "酒店活动情报"],
    ["insights", "商圈洞察"],
    ["evidence", "数据质量与来源"],
    ["login", "登录"],
    ["register", "注册"],
  ])
    it(`loads /${route} using shared layout`, async () => {
      mount("/" + route);
      expect(
        await screen.findByRole("heading", { name: new RegExp(title) }),
      ).toBeInTheDocument();
      expect(screen.getByRole("navigation")).toBeInTheDocument();
    });
  it("changes month and displays an empty state when DEMO is off", async () => {
    mount("/map");
    await screen.findByRole("heading", { name: "城市活动地图" });
    expect(
      screen.getByRole("button", { name: /城市商业交流会/ }),
    ).toBeInTheDocument();
    // F08：月份行改为折叠控件，先展开再选月份。
    fireEvent.click(screen.getByRole("button", { name: /月份：/ }));
    fireEvent.click(screen.getByRole("button", { name: "11月" }));
    expect(
      screen.queryByRole("button", { name: /城市商业交流会/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /冬季企业交流会/ }),
    ).toBeInTheDocument();
    // 「包含演示数据」现在收在「更多筛选」里：先展开折叠区，再切换开关。
    fireEvent.click(screen.getByRole("button", { name: /更多筛选/ }));
fireEvent.click(screen.getByRole("switch", { name: "包含演示数据" }));
    expect(
      await screen.findByText("所选月份或筛选下暂无活动"),
    ).toBeInTheDocument();
  });
  it("opens shared drawer and moves to calendar retaining selected event date", async () => {
    mount("/map");
    const card = await screen.findByRole("button", { name: /城市商业交流会/ });
    fireEvent.click(card);
    expect(
      await screen.findByText("活动详情"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看日历" }));
    expect(
      await screen.findByRole("heading", { name: "活动日历" }),
    ).toBeInTheDocument();
    // Week view is the default; the month heading appears once switched.
    fireEvent.click(screen.getByText("月视图"));
    expect(
      screen.getByRole("heading", { name: "2026 年 10 月" }),
    ).toBeInTheDocument();
  });
  it("shows overlapping multi-day calendar entries and navigates months", async () => {
    mount("/calendar?year=2026&month=10");
    await screen.findByRole("heading", { name: "活动日历" });
    // The calendar opens in week view; the month grid assertions below switch to it first.
    fireEvent.click(screen.getByText("月视图"));
    expect(
      screen.getAllByRole("button", { name: "D · 城市商业交流会" }),
    ).toHaveLength(4);
    fireEvent.click(screen.getByRole("button", { name: "下个月" }));
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "2026 年 11 月" }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getAllByRole("button", { name: "D · 民俗故事分享会" }),
    ).toHaveLength(6);
  });
  it("opens a graph node inspector", async () => {
    mount("/graph");
    await screen.findByRole("heading", { name: "知识图谱" });
    fireEvent.click(screen.getByText("苏州国际博览中心"));
    expect(
      await screen.findByRole("button", { name: "在地图中查看" }),
    ).toBeInTheDocument();
  });
  it("shows computed hotel distances without missing-coordinate events", async () => {
    mount("/hotels");
    await screen.findByRole("heading", { name: "酒店活动情报" });
    expect(
      await screen.findByRole("button", { name: /城市商业交流会.*0\.56 km/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /场馆待核验活动/ }),
    ).not.toBeInTheDocument();
  });
  it("searches evidence index and shows conflict provenance", async () => {
    mount("/evidence?event=demo-02");
    await screen.findByRole("heading", { name: "数据质量与来源" });
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索活动证据" }), {
      target: { value: "秋季文化展" },
    });
    expect(screen.queryByText("城市商业交流会")).not.toBeInTheDocument();
    expect(screen.getAllByText("冲突").length).toBeGreaterThan(0);
    expect(document.body.textContent).toContain("冲突");
  });
});
