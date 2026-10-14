import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import VenueMaintenance from "../src/components/VenueMaintenance";

/**
 * Duplicate venue resolution and coordinate entry.
 *
 * The tool must only ever PROPOSE a duplicate — one building can hold several venues — so
 * nothing merges without a named reviewer, a stated reason, and an explicitly chosen
 * direction. Coordinate entry must refuse a value with no provenance.
 *
 * Written as ONE mount with sequential scenarios: antd registers a module-level
 * responsiveObserver against matchMedia that survives `cleanup()`, so a second mount in the
 * same file can fail inside the React commit for reasons unrelated to this component.
 * Text is counted with `queryAllByText` because antd's Table also renders hidden
 * measurement rows.
 */
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

const DUPLICATE = {
  alias_id: "dup",
  alias_name: "开明大戏院",
  alias_events: 1,
  canonical_id: "keep",
  canonical_name: "苏州开明大戏院",
  canonical_events: 2,
  canonical_has_coordinates: true,
  signal: "containment" as const,
  distance_km: null,
  alias_looks_like_address: false,
  notes: ["one of these rows records a whole address line as its venue name"],
};

const NEEDS_COORDINATES = {
  id: "no-coords",
  name: "长歌演艺空间",
  address: null,
  events: 1,
  has_coordinates: false,
  coordinates: null,
};

describe("VenueMaintenance", () => {
  it("proposes duplicates, refuses an unjustified merge, then records a justified one", async () => {
    const merges: Record<string, unknown>[] = [];
    const coordinates: Record<string, unknown>[] = [];
    // The stub models the real backend: once a pair is merged it stops being a candidate,
    // so the proposal table legitimately empties afterwards.
    let merged = false;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        const target = String(url);
        if (target.includes("/api/venues/duplicates"))
          return Promise.resolve(json(merged ? [] : [DUPLICATE]));
        if (target.includes("/api/venues/coordinates/needed"))
          return Promise.resolve(json([NEEDS_COORDINATES]));
        if (target.includes("/api/venues/merge")) {
          merges.push(JSON.parse(String(init?.body ?? "{}")));
          merged = true;
          return Promise.resolve(json({ events_moved: 1 }));
        }
        if (target.includes("/api/venues/coordinates")) {
          coordinates.push(JSON.parse(String(init?.body ?? "{}")));
          return Promise.resolve(json({ coordinates: {} }));
        }
        return Promise.resolve(json({}));
      }),
    );

    render(<VenueMaintenance reviewer="rm" onChanged={() => {}} />);
    await waitFor(() => expect(document.body.textContent).toContain("重复场馆候选"));
    await waitFor(() =>
      expect(screen.queryAllByText("苏州开明大戏院").length).toBeGreaterThan(0),
    );

    // 1. It states that it only proposes, shows the signal, and carries the caveat note.
    expect(document.body.textContent).toContain("只提出候选，不自动合并");
    expect(screen.queryAllByText("一方名称包含另一方").length).toBeGreaterThan(0);
    expect(document.body.textContent).toContain(DUPLICATE.notes[0]);
    // Both directions are offered before any decision is taken.
    expect(screen.getAllByRole("button", { name: "反向合并" }).length).toBe(1);

    // 2. A merge with no stated reason is refused before any request is made.
    const approve = screen.getAllByRole("button", { name: /合并到「苏州开明大戏/ })[0];
    fireEvent.click(approve);
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(merges).toHaveLength(0);

    // 3. With a reason, "合并到 B" keeps B: B is canonical and A becomes the alias.
    fireEvent.change(screen.getByLabelText("合并依据 开明大戏院"), {
      target: { value: "官方页面地址一致" },
    });
    fireEvent.click(approve);
    await waitFor(() => expect(merges).toHaveLength(1));
    expect(merges[0]).toMatchObject({
      alias_id: "dup",
      canonical_id: "keep",
      reviewer: "rm",
      reason: "官方页面地址一致",
    });
    await waitFor(() =>
      expect(screen.queryAllByText("一方名称包含另一方")).toHaveLength(0),
    );

    // 4. A coordinate is saved from ONE field, filled the way AMap's 坐标拾取 copies it.
    // There is no source-URL field: AMap's web UI has no stable per-place URL to copy, so
    // demanding one blocked every entry. The API resolves the AMap place from the coordinate.
    fireEvent.change(screen.getByLabelText("坐标 长歌演艺空间"), {
      target: { value: "120.620000,31.310000" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "保存坐标" })[0]);
    await waitFor(() => expect(coordinates).toHaveLength(1));
    expect(coordinates[0]).toMatchObject({
      venue_id: "no-coords",
      coordinates: "120.620000,31.310000",
      reviewer: "rm",
    });

    // 5. An empty coordinate is refused before any request is made.
    fireEvent.change(screen.getByLabelText("坐标 长歌演艺空间"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "保存坐标" })[0]);
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(coordinates).toHaveLength(1);
  });
});
