import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PlatformProvider } from "../src/hooks/usePlatform";
import { IdentityProvider } from "../src/hooks/useIdentity";
import { sampleDataset } from "../src/services/repository";
import {
  DEFAULT_PLAN,
  annualRevenue,
  blendedPrice,
  breakEvenHotels,
  mergePlan,
  monthlyCost,
  projectedPayers,
} from "../src/services/businessPlan";
import BusinessPlanPage from "../src/pages/BusinessPlan";

/**
 * The commercial planning panel.
 *
 * It contains price assumptions and customer names, so the API is admin-only; the page refuses
 * to fetch for anyone else. The panel is the owner's working document: edits are local until
 * saved, and the save writes the whole document with the writer recorded.
 */
const ADMIN = {
  authenticated: true,
  login: "test-admin",
  role: "admin" as const,
  name: "管理员",
};
const REVIEWER = {
  authenticated: true,
  login: "test-reviewer",
  role: "reviewer" as const,
  name: null,
};

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function stubApi(saved: unknown = null) {
  const calls: { method: string; url: string; body?: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      calls.push({
        method: init?.method ?? "GET",
        url: String(url),
        body: init?.body ? String(init.body) : undefined,
      });
      if (init?.method === "PUT") {
        const parsed = JSON.parse(String(init.body));
        return Promise.resolve(
          jsonResponse({
            document: parsed.document,
            updatedAt: "2026-10-18T03:00:00+00:00",
            updatedBy: "test-admin",
          }),
        );
      }
      return Promise.resolve(
        jsonResponse({
          document: saved,
          updatedAt: saved ? "2026-10-18T02:00:00+00:00" : null,
          updatedBy: saved ? "test-admin" : null,
        }),
      );
    }),
  );
  return calls;
}

function mount(identity: typeof ADMIN | typeof REVIEWER) {
  return render(
    <MemoryRouter initialEntries={["/plan"]}>
      <PlatformProvider initialDataset={sampleDataset}>
        <IdentityProvider initialIdentity={identity}>
          <BusinessPlanPage />
        </IdentityProvider>
      </PlatformProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("business plan panel", () => {
  it("shows the plan, the live market evidence, and saves an edited assumption", async () => {
    const calls = stubApi(null);
    mount(ADMIN);
    await screen.findByRole("heading", { name: "商业规划" });
    expect(document.body.textContent).toContain("商业假设与验证状态");
    expect(document.body.textContent).toContain("试点管道");
    expect(document.body.textContent).toContain("里程碑");
    expect(document.body.textContent).toContain("市场证据(实时)");
    // Candidates come from the defaults; nobody has been contacted yet.
    expect(document.body.textContent).toContain("试点候选");
    expect(document.body.textContent).toContain("未接触");

    const hypothesis = (await screen.findAllByPlaceholderText("一句话假设"))[0];
    fireEvent.change(hypothesis, { target: { value: "测试:酒店愿意为周报付费" } });
    const save = await screen.findByRole("button", { name: "保存修改" });
    fireEvent.click(save);
    await waitFor(() => {
      const put = calls.find((call) => call.method === "PUT");
      expect(put).toBeTruthy();
      expect(put?.url).toContain("/api/plan");
      expect(put?.body).toContain("测试:酒店愿意为周报付费");
      expect(put?.body).toContain("proMonthly");
    });
    // Saved state is acknowledged with the writer from the server response.
    expect(await screen.findByText(/上次保存/)).toBeInTheDocument();
  });

  it("refuses a reviewer and never requests the plan", async () => {
    const calls = stubApi(null);
    mount(REVIEWER);
    await screen.findByText("商业规划仅管理员可见");
    expect(document.body.textContent).toContain("reviewer");
    expect(calls.filter((call) => call.url.includes("/api/plan"))).toHaveLength(0);
  });
});

describe("plan assumptions", () => {
  it("merges a stored document over the defaults without losing new fields", () => {
    const merged = mergePlan({ pricing: { proMonthly: 1200 } });
    expect(merged.pricing.proMonthly).toBe(1200);
    expect(merged.pricing.enterpriseMonthly).toBe(DEFAULT_PLAN.pricing.enterpriseMonthly);
    expect(merged.hypotheses.length).toBe(DEFAULT_PLAN.hypotheses.length);
    // Arrays are owned by the document: an emptied pipeline must stay empty.
    expect(mergePlan({ pipeline: [] }).pipeline).toEqual([]);
    expect(mergePlan(null).pipeline.length).toBe(DEFAULT_PLAN.pipeline.length);
  });

  it("derives the scenario arithmetic from the assumptions", () => {
    // 980 * 0.8 + 780 * 0.2 = 940 per hotel
    expect(blendedPrice(DEFAULT_PLAN)).toBeCloseTo(940, 6);
    expect(monthlyCost(DEFAULT_PLAN)).toBe(6500);
    // 6500 / 940 -> 6.9 -> 7 hotels to cover a month
    expect(breakEvenHotels(DEFAULT_PLAN)).toBe(7);
    expect(annualRevenue(DEFAULT_PLAN)).toBe(940 * 5 * 12);
    expect(projectedPayers(DEFAULT_PLAN)).toBe(2); // 5 candidates * 40%
  });
});
