import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PlatformProvider } from "../src/hooks/usePlatform";
import App from "../src/App";
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
      <PlatformProvider>
        <App />
      </PlatformProvider>
    </MemoryRouter>,
  );
describe("V1.2 traceable city event intelligence", () => {
  it("explains event attention without exposed scores, pricing advice or an empty layer switch", async () => {
    mount("/map");
    await screen.findByRole("heading", { name: "Menduner City Event Map" });
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
    await screen.findByRole("heading", { name: /Knowledge Graph Explorer/ });
    expect(
      screen.getByText(/Event → Venue → Location Context/),
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
      (await screen.findAllByText("Resolution status: Needs review")).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("Event Date：2026-10-12")).toBeInTheDocument();
    expect(screen.getByText("Event Date：2026-10-15")).toBeInTheDocument();
    expect(screen.getByText("候选 1：演示组织方 A")).toBeInTheDocument();
    expect(screen.getByText("候选 2：演示组织方 B")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "运行 DEMO 冲突复核" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/95%|AI decision/)).not.toBeInTheDocument();
  });
  it("shows external event signals and real source status beside hotel distances", async () => {
    mount("/hotels");
    await screen.findByRole("heading", { name: /Hotel Event Intelligence/ });
    expect(screen.getByText(/External Demand Signals/)).toBeInTheDocument();
    expect(
      screen.getAllByText("活动来源：暂无已核验活动来源").length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByText(
        /Decision Support|Revenue Manager 建议|Recommended Action/,
      ),
    ).not.toBeInTheDocument();
  });
  it("compares city resources without forecast or opportunity score panels", async () => {
    mount("/insights");
    await screen.findByRole("heading", { name: /District Comparison/ });
    expect(
      screen.getAllByText("Venue concentration · 活动场馆集中度").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("Hotel resources · 酒店资源").length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByText(/Demand potential|样本机会分/),
    ).not.toBeInTheDocument();
  });
});
