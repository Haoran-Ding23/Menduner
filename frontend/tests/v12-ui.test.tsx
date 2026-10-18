import { sampleDataset } from "../src/services/repository";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, within } from "@testing-library/react";
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
const mount = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <PlatformProvider initialDataset={sampleDataset}>
        {/* Active enterprise account: these pages exercise the paid hotel/insight workflow. */}
        <App initialAccount={ENTERPRISE_ACCOUNT} />
      </PlatformProvider>
    </MemoryRouter>,
  );
describe("V1.2 traceable city event intelligence", () => {
  it("explains event attention without exposed scores, pricing advice or an empty layer switch", async () => {
    mount("/map");
    await screen.findByRole("heading", { name: "苏州城市活动地图" });
    expect(
      screen.queryByRole("switch", { name: "酒店需求层" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /城市商业交流会/ }));
    expect(await screen.findByText("1 家（非全市场数量）")).toBeInTheDocument();
    expect(screen.getByText("活动官网 待核验")).toBeInTheDocument();
    expect(screen.getByText("场馆来源 ✓")).toBeInTheDocument();
    expect(screen.getByText(/持续 4 天/)).toBeInTheDocument();
    expect(
      screen.queryByText(/规则评分|Recommended action|房价、预订/),
    ).not.toBeInTheDocument();
  });
  it("highlights only the overlap period and displays its factual reason", async () => {
    mount("/calendar");
    fireEvent.click(
      await screen.findByRole("button", { name: "2026-10-14 → 2026-10-15" }),
    );
    expect(screen.getByText("多个活动重叠")).toBeInTheDocument();
    expect(document.querySelectorAll(".peak-day")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "清除时段高亮" }));
    expect(document.querySelectorAll(".peak-day")).toHaveLength(0);
    expect(screen.queryByText(/提前30天准备/)).not.toBeInTheDocument();
  });
  it("renders a technical relationship graph without a chatbot or decision path", async () => {
    mount("/graph");
    await screen.findByRole("heading", { name: "知识图谱" });
    expect(
      screen.getByText(/活动 → 场馆 → 位置语境/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "业务查询问题" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("switch", { name: "决策路径" }),
    ).not.toBeInTheDocument();
  });
  it("preserves conflicting candidates as needs review without automatic selection", async () => {
    mount("/evidence?event=demo-02");
    expect(
      (await screen.findAllByText("核验状态：待复核")).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("活动日期：2026-10-12")).toBeInTheDocument();
    expect(screen.getByText("活动日期：2026-10-15")).toBeInTheDocument();
    expect(screen.getByText("候选 1：演示组织方 A")).toBeInTheDocument();
    expect(screen.getByText("候选 2：演示组织方 B")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "运行 DEMO 冲突复核" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/95%|AI decision/)).not.toBeInTheDocument();
  });
  it("shows external event signals and real source status beside hotel distances", async () => {
    mount("/hotels");
    await screen.findByRole("heading", { name: "酒店活动情报" });
    expect(screen.getByText(/按酒店位置与日期查看附近活动/)).toBeInTheDocument();
    expect(
      screen.getAllByText("活动来源：暂无已核验活动来源").length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByText(
        /Decision Support|Revenue Manager 建议|Recommended Action/,
      ),
    ).not.toBeInTheDocument();
  });
  it("offers the venue's full event list from the field table", async () => {
    // A theatre programmes many events, so a venue row must lead to all of them.
    mount("/evidence?event=demo-02");
    const openers = await screen.findAllByRole("button", {
      name: "查看该场馆全部活动",
    });
    expect(openers.length).toBeGreaterThan(0);
    // The venue's own list is not on screen until it is asked for.
    expect(screen.queryByLabelText(/场馆活动/)).not.toBeInTheDocument();

    fireEvent.click(openers[0]);
    const panel = await screen.findByLabelText(/场馆活动/);
    expect(panel).toBeInTheDocument();
    // It lists the venue's events and says how many, rather than opening one.
    expect(within(panel).getByText(/\d+ 个活动/)).toBeInTheDocument();
  });
  it("compares city resources without forecast or opportunity score panels", async () => {
    mount("/insights");
    await screen.findByRole("heading", { name: "商圈资源比较" });
    expect(
      screen.getAllByText("活动场馆集中度").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("酒店资源").length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByText(/Demand potential|样本机会分/),
    ).not.toBeInTheDocument();
  });
});
