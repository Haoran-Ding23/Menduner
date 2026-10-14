import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PlatformProvider } from "../src/hooks/usePlatform";
import { sampleDataset } from "../src/services/repository";
import EvidenceQuality from "../src/pages/EvidenceQuality";

/**
 * The human review workflow on the Evidence & Data Quality page.
 *
 * Pins the rule: a reviewer approves / rejects / corrects ONE field of ONE event, the
 * decision is POSTed to the API, and the dataset is reloaded so the new status is visible.
 * A reviewer name is mandatory because a review decision must be attributable.
 *
 * Why this is ONE test with sequential scenarios: antd registers a module-level
 * responsiveObserver against window.matchMedia, and that registration survives
 * `cleanup()`. A second mount in the same file therefore subscribes with a stale
 * MediaQueryList and fails inside the React commit, for reasons unrelated to review logic.
 * Asserting the behaviours on a single mount keeps the test honest and deterministic.
 *
 * Note: antd renders two-character Chinese button labels with a space ("通 过"), so the
 * accessible-name matchers are regexes rather than exact strings.
 */
const APPROVE = /通\s*过/;
const REJECT = /驳\s*回/;

const snapshot = () => ({
  ...sampleDataset,
  events: [sampleDataset.events[0]],
  evidence: sampleDataset.evidence.filter(
    (e) => e.entityId === sampleDataset.events[0].id,
  ),
  status: {
    sourceCount: 1,
    mockSourceCount: 0,
    eventCount: 1,
    demoEventCount: 0,
    verificationCounts: {
      Verified: 0,
      Unverified: 1,
      Missing: 0,
      Conflicting: 0,
      "Needs Review": 0,
    },
    lastUpdated: sampleDataset.updatedAt,
    revision: 2,
    sources: [
      { id: "s", name: "Real source", kind: "venue", mock: 0, source_url: null },
    ],
  },
});

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

interface Traffic {
  posts: Record<string, unknown>[];
  urls: string[];
  datasets: number;
  failNext: boolean;
}

function stubApi(): Traffic {
  const traffic: Traffic = { posts: [], urls: [], datasets: 0, failNext: false };
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const target = String(url);
      if (target.includes("/api/crawl/health")) {
        // The evidence page also shows crawl-source health; it is unrelated to this test.
        return Promise.resolve(jsonResponse({ sources: [], alerts: [] }));
      }
      if (target.includes("/api/review")) {
        const body = JSON.parse(String(init?.body ?? "{}"));
        traffic.posts.push(body);
        traffic.urls.push(target);
        if (traffic.failNext) return Promise.resolve(new Response("nope", { status: 500 }));
        return Promise.resolve(jsonResponse({ decision: body.decision }));
      }
      traffic.datasets += 1;
      return Promise.resolve(jsonResponse(snapshot()));
    }),
  );
  return traffic;
}

function nameReviewer(value: string) {
  fireEvent.change(screen.getByLabelText("审核人"), { target: { value } });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  // The page remembers the reviewer, so clear it between tests.
  try {
    window.localStorage.clear();
  } catch {
    /* storage unavailable */
  }
});

describe("Evidence page human review", () => {
  // This file mounts the whole Evidence page once and drives four sequential decisions through
  // it, waiting for a real reload between each. It needs ~40s alone, and with eleven files
  // running in parallel the CPU contention pushes it past the 30s global timeout — which showed
  // up as an intermittent "expected 2 to be 3" only in a full run. The budget is raised here
  // rather than splitting the scenarios, because the single mount is deliberate: antd's
  // module-level responsiveObserver survives cleanup(), so a second mount in one file breaks
  // inside the React commit for reasons unrelated to review logic.
  it(
    "records an attributable decision for one field and reloads the dataset",
    { timeout: 150000 },
    async () => {
    const traffic = stubApi();
    render(
      <MemoryRouter initialEntries={["/evidence"]}>
        <PlatformProvider>
          <EvidenceQuality />
        </PlatformProvider>
      </MemoryRouter>,
    );
    await screen.findByLabelText("审核人");
    await waitFor(() =>
      expect(screen.queryAllByRole("button", { name: APPROVE }).length).toBeGreaterThan(0),
    );
    const loadCount = () => traffic.datasets;

    // 1. No reviewer yet => the actions are visibly unavailable, and the page says why.
    // This is the fix for a real report: the buttons used to look clickable and then do
    // nothing, because the handler returned early on an empty reviewer name.
    expect(document.body.textContent).toContain("请先填写审核人姓名");
    for (const button of screen.queryAllByRole("button", { name: APPROVE })) {
      expect(button).toBeDisabled();
    }
    for (const button of screen.queryAllByRole("button", { name: REJECT })) {
      expect(button).toBeDisabled();
    }
    // A disabled button cannot fire the handler even if it is clicked.
    const disabledProbe = (await screen.findAllByRole("button", { name: APPROVE }))[0];
    await act(async () => {
      fireEvent.click(disabledProbe);
    });
    await waitFor(() => expect(traffic.posts).toHaveLength(0));

    // 2. An approval is attributable and names exactly one field of one event.
    // Buttons are re-queried because a submission replaces their label with a spinner, so
    // the accessible name is unavailable while a request is in flight. Each click is
    // wrapped in act() so React has flushed the resulting state before the next query.
    nameReviewer("  revenue-manager  ");
    const before = loadCount();
    const approve1 = (await screen.findAllByRole("button", { name: APPROVE }))[0];
    await act(async () => {
      fireEvent.click(approve1);
    });
    await waitFor(() => expect(traffic.posts.length).toBe(1));
    expect(traffic.urls[0]).toContain("/api/review");
    expect(traffic.posts[0].decision).toBe("Verified");
    expect(traffic.posts[0].reviewer).toBe("revenue-manager");
    expect(traffic.posts[0].event_id).toBe(sampleDataset.events[0].id);
    expect(typeof traffic.posts[0].field).toBe("string");
    await waitFor(() => expect(loadCount()).toBeGreaterThan(before));

    // 3. A rejection carries the reviewed value and a reason.
    const reject1 = (await screen.findAllByRole("button", { name: REJECT }))[0];
    await act(async () => {
      fireEvent.click(reject1);
    });
    await waitFor(() => expect(traffic.posts.length).toBe(2));
    expect(traffic.posts[1].decision).toBe("Rejected");
    expect(traffic.posts[1].note).toBeTruthy();
    expect("value" in traffic.posts[1]).toBe(true);
    expect(traffic.posts[1].reviewer).toBe("revenue-manager");

    // 4. When the API refuses, the page must not reload as if it had been recorded.
    traffic.failNext = true;
    const beforeFailure = loadCount();
    // Pick the first ENABLED 通过 button. By this point two fields have been decided and the
    // table has re-rendered, so the first matching button is not necessarily actionable —
    // a row whose value was decided automatically renders a permanently disabled 通过.
    const approveTarget = (await screen.findAllByRole("button", { name: APPROVE })).find(
      (button) => !(button as HTMLButtonElement).disabled,
    );
    expect(approveTarget, "an actionable 通过 button must exist").toBeTruthy();
    await act(async () => {
      fireEvent.click(approveTarget!);
    });
    await waitFor(() => expect(traffic.posts.length).toBe(3), { timeout: 20000 });
    await new Promise((resolve) => setTimeout(resolve, 120));
    expect(loadCount()).toBe(beforeFailure);
  });
});
