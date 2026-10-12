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
describe("V1.1 Revenue Manager workflows", () => {
  it("opens a demand explanation with truthful nearby hotel and source counts", async () => {
    mount("/map");
    await screen.findByRole("heading", { name: "Menduner City Event Map" });
    fireEvent.click(screen.getByRole("switch", { name: "酒店需求层" }));
    expect(screen.getByRole("switch", { name: "酒店需求层" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: /城市商业交流会/ }));
    expect(await screen.findByText("1 家（非全市场数量）")).toBeInTheDocument();
    expect(screen.getByText("活动官网 待核验")).toBeInTheDocument();
    expect(screen.getByText("政府来源 待核验")).toBeInTheDocument();
    expect(screen.getByText("场馆来源 ✓")).toBeInTheDocument();
  });
  it("highlights the calculated review period in the risk calendar", async () => {
    mount("/calendar");
    const period = await screen.findByRole("button", {
      name: "2026-10-12 → 2026-10-15",
    });
    fireEvent.click(period);
    expect(document.querySelectorAll(".peak-day")).toHaveLength(4);
    fireEvent.click(screen.getByRole("button", { name: "清除时段高亮" }));
    expect(document.querySelectorAll(".peak-day")).toHaveLength(0);
  });
  it("calculates a DEMO graph query and refuses an unsupported revenue question", async () => {
    mount("/graph");
    await screen.findByRole("button", { name: "查询 DEMO" });
    fireEvent.click(screen.getByRole("button", { name: "查询 DEMO" }));
    expect(
      await screen.findByText(/已配置酒店附近有 1 个 HIGH/),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "业务查询问题" }), {
      target: { value: "Predict hotel revenue" },
    });
    fireEvent.click(screen.getByRole("button", { name: "查询 DEMO" }));
    expect(
      await screen.findByText(/无法回答收益预测或任意问题/),
    ).toBeInTheDocument();
  });
  it("demonstrates conflict selection without overwriting existing conflicting evidence", async () => {
    mount("/evidence?event=demo-02");
    await screen.findByRole("button", { name: "运行 DEMO 冲突复核" });
    const conflicts = screen.getAllByText("冲突").length;
    fireEvent.click(screen.getByRole("button", { name: "运行 DEMO 冲突复核" }));
    expect(
      await screen.findByText("AI decision · DEMO规则：建议选择 2026-10-12"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("冲突")).toHaveLength(conflicts);
    expect(screen.getAllByText("未提供 · 不自动赋分").length).toBeGreaterThan(
      0,
    );
  });
});
