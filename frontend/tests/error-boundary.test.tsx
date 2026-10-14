import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import ErrorBoundary from "../src/components/ErrorBoundary";

/**
 * A crash must be readable, not blank.
 *
 * This is the fix for a real report: the knowledge-graph page "would not open" on a phone, and
 * all that could be said was that. With no error boundary, an exception in a lazily-loaded page
 * unmounted the whole tree and left an empty white screen — no message, no stack, and no
 * console available on the device that crashed.
 */
function Boom(): never {
  throw new Error("boom from a child");
}

const reports: Record<string, unknown>[] = [];

function stubFetch() {
  reports.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn((_url: string, init?: RequestInit) => {
      reports.push(JSON.parse(String(init?.body ?? "{}")));
      return Promise.resolve(new Response("{}", { status: 200 }));
    }),
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ErrorBoundary", () => {
  it("shows the error and the stack instead of unmounting the page", async () => {
    stubFetch();
    // React logs the caught error; silence it so the test output stays readable.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary where="知识图谱">
        <Boom />
      </ErrorBoundary>,
    );
    spy.mockRestore();

    expect(screen.getByRole("alert")).toBeTruthy();
    expect(document.body.textContent).toContain("知识图谱");
    expect(document.body.textContent).toContain("boom from a child");
    // The stack is the part that makes the failure diagnosable.
    expect(document.body.textContent).toContain("技术细节");
    // Escape routes must exist, because the failing page may crash again on re-render.
    // antd inserts a space between two CJK characters, so the accessible name is "重 试".
    expect(screen.getByRole("button", { name: /重\s*试/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /返回地图/ })).toBeTruthy();
  });

  it("reports the crash to the server so it can be read from a desktop", async () => {
    stubFetch();
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary where="知识图谱">
        <Boom />
      </ErrorBoundary>,
    );
    spy.mockRestore();

    // React commits the error state before componentDidCatch runs, so the report is queued in a
    // microtask rather than synchronously.
    await vi.waitFor(() => expect(reports).toHaveLength(1));
    expect(reports[0].message).toBe("boom from a child");
    expect(reports[0].source).toBe("知识图谱");
    expect(String(reports[0].stack)).toContain("boom from a child");
    expect(reports[0].viewport).toMatch(/^\d+x\d+$/);
  });

  it("renders its children when nothing throws", () => {
    stubFetch();
    render(
      <ErrorBoundary where="地图">
        <p>正常内容</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("正常内容")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
