import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PlatformProvider } from "../src/hooks/usePlatform";
import { normalizeDataset } from "../src/services/adapter";
import { IdentityProvider } from "../src/hooks/useIdentity";
import ReviewConsole from "../src/pages/ReviewConsole";

const REVIEWER_IDENTITY = {
  authenticated: true,
  login: "test-reviewer",
  role: "reviewer" as const,
  name: null,
};

/**
 * A reviewer's name is remembered.
 *
 * Reported symptom: the 通过 button "did nothing". The handler returned early when the
 * reviewer field was empty, so every action was a silent no-op. The name is now persisted, and
 * the actions are disabled with a visible explanation until it is supplied. This file pins the
 * persisted half; `review-ui.test.tsx` pins the disabled/attribution half.
 *
 * It is its own file because antd's module-level responsiveObserver survives `cleanup()`, so a
 * second mount in the same file is unreliable. The dataset is passed in directly rather than
 * fetched, so the test does not depend on the API envelope being reimplemented here.
 */
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  try {
    window.localStorage.clear();
  } catch {
    /* storage unavailable */
  }
});

const EVENT_ID = "evt-memory-01";

const dataset = normalizeDataset({
  events: [
    {
      id: EVENT_ID,
      name: "记忆审核人测试活动",
      category: "culture",
      startDate: "2026-11-01",
      endDate: "2026-11-02",
      venueId: "venue-memory",
      districtId: null,
      sourceUrl: "https://example.invalid/memory",
      demo: false,
    },
  ],
  venues: [
    {
      id: "venue-memory",
      name: "记忆测试场馆",
      address: null,
      districtId: null,
      coordinates: null,
      districtDemo: false,
    },
  ],
  hotels: [],
  districts: [],
  evidence: [
    {
      id: "ev-memory-1",
      entityId: EVENT_ID,
      field: "startDate",
      value: "2026-11-01",
      status: "Needs Review",
      method: "explicit_source_field",
      confidence: 0.9,
      sourceUrl: "https://example.invalid/memory",
      updatedAt: "2026-10-14T00:00:00+00:00",
    },
    {
      id: "ev-memory-2",
      entityId: EVENT_ID,
      field: "organizer",
      value: null,
      status: "Missing",
      method: "explicit_source_field",
      confidence: 0.5,
      sourceUrl: "https://example.invalid/memory",
      updatedAt: "2026-10-14T00:00:00+00:00",
    },
  ],
  updatedAt: "2026-10-14T00:00:00+00:00",
});

describe("remembered reviewer", () => {
  it("prefills the reviewer name and leaves the review actions usable", async () => {
    window.localStorage.setItem("menduner.reviewer", "revenue-manager");

    render(
      <MemoryRouter initialEntries={[`/review?event=${EVENT_ID}`]}>
        <PlatformProvider initialDataset={dataset}>
          <IdentityProvider initialIdentity={REVIEWER_IDENTITY}>
            <ReviewConsole />
          </IdentityProvider>
        </PlatformProvider>
      </MemoryRouter>,
    );

    const field = await screen.findByLabelText("审核人");
    await waitFor(() => expect(field).toHaveValue("revenue-manager"));

    // The "name required" warning is absent and the actions are enabled.
    expect(document.body.textContent).not.toContain("请先填写审核人姓名");
    const approveButtons = await screen.findAllByRole("button", { name: /通\s*过/ });
    expect(approveButtons.length).toBeGreaterThan(0);
    expect(approveButtons.every((button) => !(button as HTMLButtonElement).disabled)).toBe(
      true,
    );
  });
});
