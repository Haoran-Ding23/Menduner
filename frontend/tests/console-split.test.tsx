import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PlatformProvider } from "../src/hooks/usePlatform";
import { IdentityProvider } from "../src/hooks/useIdentity";
import { ANONYMOUS, type Identity } from "../src/services/api";
import { sampleDataset } from "../src/services/repository";
import DataQuality from "../src/pages/DataQuality";
import ReviewConsole from "../src/pages/ReviewConsole";

/**
 * The public data-quality page and the internal review console are two audiences.
 *
 * The split exists because sources and verification status are the trust argument and must be
 * readable by anyone (including a paying customer before they buy), while approving claims,
 * merging venues and reading the frontend error log are internal operations. The server
 * enforces the role on those endpoints; this file pins the UI half: the public page never
 * calls an internal endpoint, and the console refuses to render for anyone who is not a
 * reviewer.
 */
const REVIEWER: Identity = {
  authenticated: true,
  login: "test-reviewer",
  role: "reviewer",
  name: null,
};
const VIEWER: Identity = {
  authenticated: true,
  login: "hotel-a",
  role: "viewer",
  name: "客户只读",
};

function stubApi(identity: Identity = ANONYMOUS) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const target = String(url);
      calls.push(`${init?.method ?? "GET"} ${target}`);
      if (target.includes("/api/auth/me")) {
        return Promise.resolve(
          new Response(JSON.stringify(identity), { status: 200 }),
        );
      }
      if (target.includes("/api/crawl/health")) {
        return Promise.resolve(
          new Response(JSON.stringify({ sources: [], alerts: [] }), { status: 200 }),
        );
      }
      return Promise.resolve(new Response("[]", { status: 200 }));
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("public data quality page", () => {
  it("shows sources and status without any review controls and without internal calls", async () => {
    const calls = stubApi();
    render(
      <MemoryRouter initialEntries={["/evidence?event=demo-02"]}>
        <PlatformProvider initialDataset={sampleDataset}>
          <IdentityProvider initialIdentity={ANONYMOUS}>
            <DataQuality />
          </IdentityProvider>
        </PlatformProvider>
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { name: "数据质量与来源" });
    // Read-only: no reviewer identity field, no action column, no internal panels.
    expect(screen.queryByLabelText("审核人")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("审核操作");
    expect(document.body.textContent).not.toContain("前端错误");
    // Source links are the point of the page, so they must be present.
    await waitFor(() =>
      expect(screen.getAllByRole("link", { name: "原始来源 ↗" }).length).toBeGreaterThan(0),
    );
    // The claimed boundary warning is visible too.
    expect(document.body.textContent).toContain("不做收入预测");
    const internal = calls.filter((call) =>
      /\/(api\/review|api\/client-errors|api\/venues\/edits|api\/venues\/duplicates)/.test(
        call,
      ),
    );
    expect(internal).toEqual([]);
  });
});

describe("review console gate", () => {
  it("refuses an anonymous visitor instead of rendering a page of buttons", async () => {
    stubApi();
    render(
      <MemoryRouter initialEntries={["/review"]}>
        <PlatformProvider initialDataset={sampleDataset}>
          <IdentityProvider initialIdentity={ANONYMOUS}>
            <ReviewConsole />
          </IdentityProvider>
        </PlatformProvider>
      </MemoryRouter>,
    );
    await screen.findByText("审核台需要审核员权限");
    expect(document.body.textContent).toContain("未登录");
    expect(screen.queryByRole("button", { name: /通\s*过/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("审核人")).not.toBeInTheDocument();
  });

  it("refuses a customer (viewer) account and says which role is needed", async () => {
    stubApi(VIEWER);
    render(
      <MemoryRouter initialEntries={["/review"]}>
        <PlatformProvider initialDataset={sampleDataset}>
          <IdentityProvider initialIdentity={VIEWER}>
            <ReviewConsole />
          </IdentityProvider>
        </PlatformProvider>
      </MemoryRouter>,
    );
    await screen.findByText("审核台需要审核员权限");
    expect(document.body.textContent).toContain("viewer");
    expect(document.body.textContent).toContain("只能浏览数据");
    expect(screen.queryByRole("button", { name: /通\s*过/ })).not.toBeInTheDocument();
  });

  it("renders the review workflow for a reviewer", async () => {
    stubApi(REVIEWER);
    render(
      <MemoryRouter initialEntries={["/review"]}>
        <PlatformProvider initialDataset={sampleDataset}>
          <IdentityProvider initialIdentity={REVIEWER}>
            <ReviewConsole />
          </IdentityProvider>
        </PlatformProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByLabelText("审核人")).toBeInTheDocument();
    // The decision log and the internal lists are fetched once the role allows it.
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /通\s*过/ }).length).toBeGreaterThan(0),
    );
    expect(document.body.textContent).toContain("已记录审核");
  });
});
