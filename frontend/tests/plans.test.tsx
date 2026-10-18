import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { PlatformProvider } from "../src/hooks/usePlatform";
import { AccountProvider } from "../src/hooks/useEntitlements";
import { sampleDataset } from "../src/services/repository";
import type { AccountState } from "../src/services/account";
import App from "../src/App";
import PlansPage from "../src/pages/Plans";
import RegisterPage from "../src/pages/Register";
import {
  ANONYMOUS_ACCOUNT_STATE,
  ENTERPRISE_ACCOUNT,
  EXPIRED_ACCOUNT,
  PENDING_ORDER,
  TRIAL_PRO_ACCOUNT,
} from "./fixtures";

/**
 * The customer-facing commercial surface, now backed by a real account and a real activation path.
 *
 * Two commitments are pinned here: public data stays free, and the paid workflow requires an
 * account whose plan the SERVER derives (invite trial -> subscription after an operator confirms
 * the offline payment). The page must also route each visitor state to the right next step:
 * anonymous -> invite registration, expired trial -> activation request.
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

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mountApp(path: string, account?: AccountState) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <PlatformProvider initialDataset={sampleDataset}>
        <App initialAccount={account} />
      </PlatformProvider>
    </MemoryRouter>,
  );
}

function mountPage(node: React.ReactNode, account: AccountState) {
  return render(
    <MemoryRouter initialEntries={["/plans"]}>
      <AccountProvider initialState={account}>{node}</AccountProvider>
    </MemoryRouter>,
  );
}

describe("plans page", () => {
  it("shows the tiers, prices and the free-data promise to an anonymous visitor", async () => {
    mountPage(<PlansPage />, ANONYMOUS_ACCOUNT_STATE);
    await screen.findByRole("heading", { name: "套餐与升级" });
    expect(screen.getAllByText("专业版").length).toBeGreaterThan(0);
    expect(screen.getAllByText("企业版").length).toBeGreaterThan(0);
    expect(screen.getByText("¥980")).toBeInTheDocument();
    expect(document.body.textContent).toContain("公开的活动、来源与证据永久免费");
    expect(document.body.textContent).toContain("邀请码");
    // The paid CTA leads to invite registration, not to a fake unlock.
    expect(screen.getByRole("button", { name: "用邀请码注册" })).toBeInTheDocument();
  });

  it("shows the trial state and the pending activation request to a customer", async () => {
    mountPage(<PlansPage />, { ...TRIAL_PRO_ACCOUNT, orders: [PENDING_ORDER] });
    await screen.findByRole("heading", { name: "套餐与升级" });
    expect(document.body.textContent).toContain("试用中");
    expect(document.body.textContent).toContain("待确认收款");
    expect(document.body.textContent).toContain("test-pro");
    expect(screen.getByRole("button", { name: "申请开通" })).toBeInTheDocument();
  });

  it("tells an expired customer the trial is over and offers activation", async () => {
    mountPage(<PlansPage />, EXPIRED_ACCOUNT);
    await screen.findByRole("heading", { name: "套餐与升级" });
    expect(document.body.textContent).toContain("试用已结束");
    expect(document.body.textContent).toContain("申请开通");
  });
});

describe("paid workflow gate", () => {
  it("sends an anonymous visitor to invite-code registration", async () => {
    mountApp("/hotels");
    await screen.findByText(/属于专业版/);
    expect(document.body.textContent).toContain("邀请制");
    fireEvent.click(screen.getByRole("button", { name: "用邀请码注册试用" }));
    expect(
      await screen.findByRole("heading", { name: "用邀请码注册" }),
    ).toBeInTheDocument();
  });

  it("refuses an account without a paid period and offers activation", async () => {
    mountApp("/hotels", EXPIRED_ACCOUNT);
    await screen.findByText(/属于专业版/);
    fireEvent.click(screen.getByRole("button", { name: "查看套餐并申请开通" }));
    await screen.findByRole("heading", { name: "套餐与升级" });
    expect(document.body.textContent).toContain("试用已结束");
  });

  it("unlocks the hotel intelligence page on a pro trial, one hotel at a time", async () => {
    mountApp("/hotels", TRIAL_PRO_ACCOUNT);
    await screen.findByRole("heading", { name: "酒店活动情报" });
    expect(document.body.textContent).toContain("专业版 · 当前 1 家酒店");
    expect(document.body.textContent).not.toContain("全选");
  });

  it("gives an active enterprise account the multi-hotel comparison", async () => {
    mountApp("/hotels", ENTERPRISE_ACCOUNT);
    await screen.findByRole("heading", { name: "酒店活动情报" });
    expect(screen.getByText("酒店组合")).toBeInTheDocument();
    expect(screen.getByText(/全选 \d+ 家/)).toBeInTheDocument();
  });
});

describe("invite registration", () => {
  it("registers with an invite code, signs in and lands on the plans page", async () => {
    const calls: { url: string; body?: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        calls.push({ url: String(url), body: init?.body ? String(init.body) : undefined });
        return Promise.resolve(jsonResponse(TRIAL_PRO_ACCOUNT));
      }),
    );
    render(
      <MemoryRouter initialEntries={["/register"]}>
        <AccountProvider initialState={ANONYMOUS_ACCOUNT_STATE}>
          <Routes>
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/plans" element={<PlansPage />} />
          </Routes>
        </AccountProvider>
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { name: "用邀请码注册" });
    fireEvent.change(screen.getByLabelText("邀请码"), { target: { value: "MND-ABCD-EFGH" } });
    fireEvent.change(screen.getByLabelText("登录名"), { target: { value: "hotel-a" } });
    fireEvent.change(screen.getByLabelText("称呼"), { target: { value: "王经理" } });
    fireEvent.change(screen.getByLabelText("酒店(可选)"), { target: { value: "苏州洲际酒店" } });
    fireEvent.change(screen.getByLabelText("密码(至少 8 位)"), { target: { value: "secret-pass-1" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "secret-pass-1" } });
    fireEvent.click(screen.getByRole("button", { name: "注册并开始试用" }));
    await waitFor(() => {
      expect(calls.some((call) => call.url.includes("/api/account/register"))).toBe(true);
    });
    expect(await screen.findByRole("heading", { name: "套餐与升级" })).toBeInTheDocument();
    const registerCall = calls.find((call) => call.url.includes("/api/account/register"));
    expect(registerCall?.body).toContain("MND-ABCD-EFGH");
    expect(registerCall?.body).toContain("hotel-a");
  });
});
