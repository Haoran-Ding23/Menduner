import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PlatformProvider } from "../src/hooks/usePlatform";
import { EntitlementsProvider } from "../src/hooks/useEntitlements";
import { sampleDataset } from "../src/services/repository";
import { PLAN_STORAGE_KEY } from "../src/services/plans";
import PlansPage from "../src/pages/Plans";
import App from "../src/App";

/**
 * The customer-facing paid surface.
 *
 * Pins the two commitments the tier design rests on: public data (activities, sources, evidence,
 * quality) stays free, and the paid tiers sell the workflow — hotel-centric filtering, area
 * comparison and (later) the weekly report. The upgrade switch is a labelled demo, so the page
 * must never imply that a payment happened.
 */
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

beforeEach(() => {
  // Every case starts on the free plan unless it seeds another one explicitly.
  try {
    window.localStorage.removeItem(PLAN_STORAGE_KEY);
  } catch {
    /* storage unavailable */
  }
});
afterEach(() => {
  cleanup();
  try {
    window.localStorage.removeItem(PLAN_STORAGE_KEY);
  } catch {
    /* storage unavailable */
  }
});

function mountApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <PlatformProvider initialDataset={sampleDataset}>
        <App />
      </PlatformProvider>
    </MemoryRouter>,
  );
}

describe("plans page", () => {
  it("shows the three tiers, the prices and the free-data promise", async () => {
    render(
      <MemoryRouter initialEntries={["/plans"]}>
        <EntitlementsProvider initialPlan="free">
          <PlansPage />
        </EntitlementsProvider>
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { name: "套餐与升级" });
    expect(screen.getAllByText("免费版").length).toBeGreaterThan(0);
    expect(screen.getAllByText("专业版").length).toBeGreaterThan(0);
    expect(screen.getAllByText("企业版").length).toBeGreaterThan(0);
    expect(screen.getByText("¥980")).toBeInTheDocument();
    expect(document.body.textContent).toContain("公开的活动、来源与证据永久免费");
    expect(document.body.textContent).toContain("演示版");
    expect(document.body.textContent).toContain("能力对照");
  });

  it("unlocks a plan through the labelled demo switch and persists the choice", async () => {
    render(
      <MemoryRouter initialEntries={["/plans"]}>
        <EntitlementsProvider initialPlan="free">
          <PlansPage />
        </EntitlementsProvider>
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { name: "套餐与升级" });
    fireEvent.click(screen.getByRole("button", { name: "演示解锁专业版" }));
    await waitFor(() =>
      expect(window.localStorage.getItem(PLAN_STORAGE_KEY)).toBe("pro"),
    );
    expect(document.body.textContent).toContain("当前套餐:专业版");
    // The paid workflow is reachable from the page's own CTA.
    fireEvent.click(screen.getByRole("button", { name: "去看看酒店活动情报" }));
  });
});

describe("paid workflow gate", () => {
  it("locks the hotel intelligence page on the free plan and unlocks it from the plans page", async () => {
    mountApp("/hotels");
    // Gated feature explains what it belongs to and why it is paid.
    await screen.findByText(/属于专业版/);
    expect(document.body.textContent).toContain("公开的活动、来源与证据数据保持免费");

    fireEvent.click(screen.getByRole("button", { name: "查看套餐并解锁" }));
    await screen.findByRole("heading", { name: "套餐与升级" });
    fireEvent.click(screen.getByRole("button", { name: "演示解锁专业版" }));
    fireEvent.click(await screen.findByRole("button", { name: "去看看酒店活动情报" }));
    expect(
      await screen.findByRole("heading", { name: "酒店活动情报" }),
    ).toBeInTheDocument();
    // Professional plan is one hotel; the multi-hotel portfolio is an enterprise feature.
    expect(document.body.textContent).toContain("专业版 · 当前 1 家酒店");
  });

  it("gives the enterprise plan the multi-hotel comparison", async () => {
    window.localStorage.setItem(PLAN_STORAGE_KEY, "enterprise");
    mountApp("/hotels");
    await screen.findByRole("heading", { name: "酒店活动情报" });
    expect(screen.getByText("酒店组合")).toBeInTheDocument();
    expect(screen.getByText(/全选 \d+ 家/)).toBeInTheDocument();
  });
});
