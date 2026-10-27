import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PlatformProvider } from "../src/hooks/usePlatform";
import EventMap from "../src/components/Map";
import { sampleDataset } from "../src/services/repository";
import { filterEvents } from "../src/utils/data";
const state = vi.hoisted(() => ({
  markers: [] as { position: number[]; title: string }[],
  lines: [] as { path: number[][] }[],
}));
vi.mock("@amap/amap-jsapi-loader", () => ({
  default: {
    load: vi.fn().mockResolvedValue({
      Map: class {
        addControl() {}
        add() {}
        clearMap() {}
        setFitView() {}
        setZoomAndCenter() {}
        destroy() {}
        on(name: string, callback: () => void) {
          if (name === "complete") queueMicrotask(callback);
        }
      },
      Marker: class {
        constructor(options: { position: number[]; title: string }) {
          state.markers.push(options);
        }
        on() {}
      },
      Polyline: class {
        constructor(options: { path: number[][] }) {
          state.lines.push(options);
        }
      },
      Scale: class {},
      ToolBar: class {},
    }),
  },
}));
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  state.markers = [];
  state.lines = [];
});
describe("Real map integration boundary with mocked SDK", () => {
  it("groups verified event locations, excludes unknown venue and adds real configured hotel layer", async () => {
    vi.stubEnv("VITE_AMAP_KEY", "test-key");
    vi.stubEnv("VITE_AMAP_SERVICE_HOST", "/_AMapService");
    const events = filterEvents(sampleDataset.events, {
      year: 2026,
      month: 10,
      district: "",
      category: "",
      includeDemo: true,
    });
    render(
      <MemoryRouter initialEntries={["/map?event=demo-01"]}>
        <PlatformProvider initialDataset={sampleDataset}>
          <EventMap events={events} demandLayer />
        </PlatformProvider>
      </MemoryRouter>,
    );
    // 新增了「活动在这里」的箭头标记（无标题、不参与分组），
    // 这里只断言有标题的实际点位标记。
    await waitFor(() => expect(state.markers.filter((m) => m.title)).toHaveLength(3));
    expect(state.markers.filter((m) => m.title).map((m) => m.title)).toEqual([
      "苏州国际博览中心",
      "独墅湖影剧院",
      "苏州洲际酒店",
    ]);
    expect(state.markers[0].position).toEqual([120.707374, 31.323727]);
    expect(state.lines[0].path).toEqual([
      [120.707374, 31.323727],
      [120.710226, 31.319292],
    ]);
    expect(screen.queryByText("正在连接高德地图")).not.toBeInTheDocument();
  });
});
