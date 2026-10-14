import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { loadApiDataset } from "../src/services/api";
import { sampleDataset } from "../src/services/repository";
import { PlatformProvider, usePlatform } from "../src/hooks/usePlatform";
const snapshot = () => ({
  ...sampleDataset,
  events: [{ ...sampleDataset.events[0], name: "API-only event" }],
  status: {
    sourceCount: 2,
    mockSourceCount: 2,
    eventCount: 1,
    demoEventCount: 1,
    verificationCounts: {
      Verified: 0,
      Unverified: 1,
      Missing: 0,
      Conflicting: 0,
      "Needs Review": 0,
    },
    lastUpdated: sampleDataset.updatedAt,
    revision: 1,
    sources: [
      {
        id: "a",
        name: "Venue MOCK",
        kind: "official_venue",
        mock: 1,
        source_url: null,
      },
      {
        id: "b",
        name: "Government MOCK",
        kind: "government",
        mock: 1,
        source_url: null,
      },
    ],
  },
});
const response = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
/**
 * The provider's observable surface. The data-status strip was removed from the UI at the
 * product owner's request, so this probe reads the provider state directly instead of
 * asserting on a component that no longer exists. The status vocabulary asserted below is
 * the same one the page header now shows.
 */
function Probe() {
  const { dataset, resetData, importData, dataMode, reloadData } = usePlatform();
  const label = {
    loading: "读取中",
    api: "后端 API · SQLite",
    error: "API 不可用",
    stale: "API 已断开 · 上次快照",
    demo: "本地 DEMO",
    import: "手动导入 · 当前会话",
  }[dataMode];
  return (
    <>
      <span data-testid="data-mode">{label}</span>
      <button onClick={() => void reloadData()}>刷新 API 数据</button>
      <div data-testid="event-names">
        {dataset.events.map((e) => e.name).join(",")}
      </div>
      <button onClick={resetData}>Explicit demo</button>
      <button
        onClick={() => importData([{ id: "manual", name: "Manual event" }])}
      >
        Import
      </button>
    </>
  );
}
function mount() {
  return render(
    <MemoryRouter>
      <PlatformProvider>
        <Probe />
      </PlatformProvider>
    </MemoryRouter>,
  );
}
describe("API adapter", () => {
  it("normalizes a single database snapshot through the existing adapter", async () => {
    const fetcher = vi.fn().mockResolvedValue(response(snapshot()));
    vi.stubGlobal("fetch", fetcher);
    const data = await loadApiDataset();
    expect(data.dataset.events[0].name).toBe("API-only event");
    expect(data.status.sourceCount).toBe(2);
    expect(fetcher.mock.calls[0][0]).toBe("/api/dataset");
  });
  it("rejects HTTP failures and incomplete datasets", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response("", { status: 503 }))
        .mockResolvedValueOnce(response({ events: [] })),
    );
    await expect(loadApiDataset()).rejects.toThrow("503");
    await expect(loadApiDataset()).rejects.toThrow("数据结构不完整");
  });
  it("preserves an empty database without an invented update timestamp", async () => {
    const empty = {
      ...snapshot(),
      events: [],
      venues: [],
      hotels: [],
      districts: [],
      evidence: [],
      updatedAt: null,
    };
    empty.status = { ...empty.status, eventCount: 0, demoEventCount: 0 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(empty)));
    expect((await loadApiDataset()).dataset.updatedAt).toBe("");
  });
});
describe("API provider lifecycle", () => {
  it("loads API records, refreshes changed records and labels stale snapshots on failure", async () => {
    const updated = snapshot();
    updated.events[0].name = "Updated API event";
    updated.status.revision = 2;
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(response(snapshot()))
        .mockResolvedValueOnce(response(updated))
        .mockRejectedValueOnce(new Error("offline")),
    );
    mount();
    expect(await screen.findByText("API-only event")).toBeInTheDocument();
    // The source-count strip was removed from the UI at the product owner's request, so the
    // loaded state is asserted on the provider mode rather than on a removed component.
    expect(screen.getByTestId("data-mode")).toHaveTextContent("后端 API · SQLite");
    fireEvent.click(screen.getByRole("button", { name: "刷新 API 数据" }));
    expect(await screen.findByText("Updated API event")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "刷新 API 数据" }));
    expect(
      await screen.findByText("API 已断开 · 上次快照"),
    ).toBeInTheDocument();
    expect(screen.getByText("Updated API event")).toBeInTheDocument();
  });
  it("does not silently substitute local JSON when the API is unavailable, and retries successfully", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockRejectedValueOnce(new Error("offline"))
        .mockResolvedValueOnce(response(snapshot())),
    );
    mount();
    await screen.findByText("API 不可用");
    expect(screen.getByTestId("event-names")).toBeEmptyDOMElement();
    fireEvent.click(screen.getByRole("button", { name: "刷新 API 数据" }));
    expect(await screen.findByText("API-only event")).toBeInTheDocument();
  });
  it("does not let an outstanding API response overwrite explicit local import", async () => {
    let resolve!: (r: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((r) => {
            resolve = r;
          }),
      ),
    );
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    resolve(response(snapshot()));
    await waitFor(() =>
      expect(screen.getByTestId("event-names")).toHaveTextContent(
        "Manual event",
      ),
    );
    expect(screen.getByText("手动导入 · 当前会话")).toBeInTheDocument();
  });
});
