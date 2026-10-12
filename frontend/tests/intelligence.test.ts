import { describe, it, expect } from "vitest";
import { sampleDataset } from "../src/services/repository";
import {
  assessDemand,
  nearbyHotels,
  evidenceSummary,
  businessToday,
} from "../src/services/intelligence";
import type { Dataset } from "../src/types";
describe("V1.2 event attention", () => {
  it("derives DEMO HIGH from declared inputs and configured hotels only", () => {
    const result = assessDemand(sampleDataset.events[0], sampleDataset);
    expect(result).toMatchObject({ level: "HIGH", score: 75, basis: "DEMO" });
    expect(result.nearbyHotels).toHaveLength(1);
    expect(result.nearestDistance).toBeCloseTo(0.56, 2);
    expect(result.reasons.join(" ")).toContain("持续 4 天");
    expect(result.reasons.join(" ")).not.toMatch(/分（|阈值|≥|房价/);
    expect(
      nearbyHotels(sampleDataset.events[0], sampleDataset, 0.1),
    ).toHaveLength(0);
  });
  it("does not classify real records with missing evidence or contradictory date evidence", () => {
    const event = { ...sampleDataset.events[0], id: "real", demo: false };
    const data: Dataset = { ...sampleDataset, events: [event], evidence: [] };
    expect(assessDemand(event, data).level).toBe("UNKNOWN");
    data.evidence = ["venueId", "category", "startDate", "endDate"].map(
      (field) => ({
        id: field,
        entityId: "real",
        field,
        value: event[field as keyof typeof event],
        status: "Verified",
        method: "direct_web",
        sourceName: "Organizer",
        sourceUrl: "https://example.org/event",
        updatedAt: "2026-10-12",
      }),
    );
    expect(assessDemand(event, data).basis).toBe("RULE_BASED");
    data.evidence.push({
      ...data.evidence[2],
      id: "conflict",
      status: "Conflicting",
      value: "2026-10-15",
    });
    expect(assessDemand(event, data).level).toBe("UNKNOWN");
  });
  it("withholds priority for missing dates and unknown event locations", () => {
    expect(assessDemand(sampleDataset.events[9], sampleDataset).score).toBe(
      null,
    );
    expect(assessDemand(sampleDataset.events[7], sampleDataset).level).toBe(
      "UNKNOWN",
    );
  });
  it("keeps venue sources separate from event proof", () => {
    const evidence = evidenceSummary(sampleDataset.events[0], sampleDataset);
    expect(evidence.eventUrls).toHaveLength(0);
    expect(evidence.venueUrls).toHaveLength(1);
  });
  it("anchors business date in Asia/Shanghai", () => {
    expect(businessToday(new Date("2026-10-11T17:00:00Z"))).toBe("2026-10-12");
  });
});

describe("V1.2 calendar and district intelligence", () => {
  it("shows exact reasons for overlapping and multi-day activity, clipped at month boundary", async () => {
    const { importantEventPeriods } = await import(
      "../src/services/intelligence"
    );
    const periods = importantEventPeriods(sampleDataset.events, 2026, 10);
    expect(periods.find((p) => p.start === "2026-10-14")).toMatchObject({
      end: "2026-10-15",
      reasons: ["多个活动重叠", "包含持续三天及以上的活动"],
      eventIds: ["demo-01", "demo-02"],
      demo: true,
    });
    expect(periods.find((p) => p.start === "2026-10-28")?.end).toBe(
      "2026-10-31",
    );
    expect(
      importantEventPeriods(sampleDataset.events, 2026, 11)[0],
    ).toMatchObject({ start: "2026-11-01", end: "2026-11-02" });
    expect(importantEventPeriods([], 2026, 10)).toEqual([]);
  });
  it("does not invent long-duration periods from missing or reversed end dates", async () => {
    const { importantEventPeriods } = await import(
      "../src/services/intelligence"
    );
    for (const endDate of [null, "2026-10-01"])
      expect(
        importantEventPeriods(
          [{ ...sampleDataset.events[0], endDate }],
          2026,
          10,
        ),
      ).toEqual([]);
  });
  it("includes ongoing events in the next 30 dates but excludes day 31", async () => {
    const { upcomingHighEvents } = await import("../src/services/intelligence");
    const edge = {
      ...sampleDataset.events[0],
      id: "edge",
      startDate: "2026-11-11",
      endDate: "2026-11-12",
    };
    expect(
      upcomingHighEvents(
        [...sampleDataset.events, edge],
        sampleDataset,
        "2026-10-12",
      ).map((e) => e.id),
    ).toEqual(["demo-01"]);
  });
  it("compares observed categories, venue concentration and configured hotel resources without opportunity scores", async () => {
    const { districtMetrics } = await import("../src/services/intelligence");
    const events = sampleDataset.events.filter((e) =>
      e.startDate?.startsWith("2026-10"),
    );
    const metrics = districtMetrics(events, sampleDataset);
    expect(metrics[0]).toMatchObject({
      events: 2,
      venues: 1,
      hotels: 1,
      configuredHotels: 1,
      demo: true,
    });
    expect(metrics[0].concentration).toContain("2/2");
    expect(metrics[0]).not.toHaveProperty("score");
    expect(metrics[1]).toMatchObject({ events: 3, configuredHotels: 0 });
    expect(districtMetrics([], sampleDataset)[0].concentration).toBe(
      "无可用活动场馆关系",
    );
  });
});
describe("V1.2 graph provenance", () => {
  it("connects venue to nearby hotels using verified coordinates, without decision nodes", async () => {
    const { createRepository } = await import("../src/services/repository");
    const graph = createRepository(sampleDataset).getGraphData("demo-01");
    expect(graph.nodes.map((n) => n.kind)).toEqual([
      "Event",
      "Venue",
      "District",
      "Hotel",
    ]);
    expect(graph.edges.find((e) => e.label.startsWith("NEAR"))).toMatchObject({
      source: "v-expo",
      target: "h-inter",
      label: "NEAR · 0.56 km",
      demo: false,
    });
    const noCoordinates = {
      ...sampleDataset,
      hotels: sampleDataset.hotels.map((h) => ({ ...h, coordinates: null })),
    };
    expect(
      createRepository(noCoordinates)
        .getGraphData("demo-01")
        .edges.some((e) => e.label.startsWith("NEAR")),
    ).toBe(false);
  });
  it("preserves confidence metadata without promoting it to verified evidence", async () => {
    const { normalizeDataset } = await import("../src/services/adapter");
    const data = normalizeDataset({
      events: [{ id: "e", name: "A" }],
      evidence: [
        {
          id: "field",
          entityId: "e",
          field: "name",
          value: "A",
          confidence: 0.95,
          sourceRole: "official_organizer",
          status: "Unverified",
        },
      ],
    });
    expect(data.evidence[0]).toMatchObject({
      confidence: 0.95,
      status: "Unverified",
    });
  });
});
it("does not invent duration when end date is missing", () => {
  const assessment = assessDemand(
    { ...sampleDataset.events[0], endDate: null },
    sampleDataset,
  );
  expect(assessment.reasons.join(" ")).toContain("结束日期未知");
});
