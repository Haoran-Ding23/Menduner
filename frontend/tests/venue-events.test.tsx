import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PlatformProvider } from "../src/hooks/usePlatform";
import { sampleDataset } from "../src/services/repository";
import VenueEvents from "../src/components/VenueEvents";

/**
 * A venue's own event list.
 *
 * A theatre programmes many events, so clicking a venue must list all of them rather than
 * opening one arbitrary event, and the list must stay scoped to that venue.
 */
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("VenueEvents", () => {
  it("lists every event held at one venue, and nothing from other venues", async () => {
    const venueId = sampleDataset.events[0].venueId!;
    const expected = sampleDataset.events.filter((e) => e.venueId === venueId);
    expect(expected.length).toBeGreaterThan(1);
    const venueName = sampleDataset.venues.find((v) => v.id === venueId)!.name;

    render(
      <MemoryRouter initialEntries={["/map"]}>
        <PlatformProvider initialDataset={sampleDataset}>
          <VenueEvents venueId={venueId} />
        </PlatformProvider>
      </MemoryRouter>,
    );

    await screen.findByLabelText(`场馆活动 ${venueName}`);
    await waitFor(() =>
      expect(screen.queryAllByText(`${expected.length} 个活动`).length).toBeGreaterThan(0),
    );
    for (const event of expected) {
      expect(screen.queryAllByText(event.name).length).toBeGreaterThan(0);
    }
    const other = sampleDataset.events.find((e) => e.venueId !== venueId);
    if (other) expect(screen.queryAllByText(other.name)).toHaveLength(0);
  });
});
