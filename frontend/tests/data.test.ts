import { describe, it, expect } from "vitest";
import { normalizeDataset, normalizeEvent } from "../src/services/adapter";
import {
  filterEvents,
  monthRange,
  overlaps,
  verifiedCoords,
  distanceKm,
  effectiveStatus,
  safeUrl,
  eventCoordinates,
} from "../src/utils/data";
import { sampleDataset, createRepository } from "../src/services/repository";
const filters = {
  year: 2026,
  month: 10,
  district: "",
  category: "",
  includeDemo: true,
};
describe("Dates and shared filters", () => {
  it("filters month, category, district and excludes DEMO", () => {
    expect(filterEvents(sampleDataset.events, filters)).toHaveLength(6);
    expect(
      filterEvents(sampleDataset.events, { ...filters, district: "d-jinji" }),
    ).toHaveLength(2);
    expect(
      filterEvents(sampleDataset.events, { ...filters, category: "education" }),
    ).toHaveLength(1);
    expect(
      filterEvents(sampleDataset.events, { ...filters, includeDemo: false }),
    ).toHaveLength(0);
    expect(
      filterEvents(sampleDataset.events, { ...filters, month: 11 }),
    ).toHaveLength(2);
  });
  it("includes cross month and cross year events on every covered date", () => {
    expect(overlaps(sampleDataset.events[4], "2026-11-02", "2026-11-02")).toBe(
      true,
    );
    expect(overlaps(sampleDataset.events[4], "2026-11-03", "2026-11-03")).toBe(
      false,
    );
    expect(overlaps(sampleDataset.events[8], "2027-01-01", "2027-01-01")).toBe(
      true,
    );
    expect(monthRange(2024, 2)[1]).toBe("2024-02-29");
  });
  it("rejects impossible dates and reversed intervals", () => {
    const e = normalizeEvent({ startDate: "2026-02-30" }, 0);
    expect(e.startDate).toBe(null);
    expect(
      overlaps(
        { ...e, startDate: "2026-10-20", endDate: "2026-10-10" },
        "2026-10-01",
        "2026-10-31",
      ),
    ).toBe(false);
  });
});
describe("Evidence and import boundary", () => {
  it("preserves original crawler columns, nulls, stable ID and no inferred verification", () => {
    const d = normalizeDataset([
      {
        event_id: "e1",
        "Event Name": "A",
        "Start Date": "2026-10-10",
        attendance: null,
        unknown_column: 123,
      },
    ]);
    expect(d.events[0].raw?.unknown_column).toBe(123);
    expect(d.events[0].attendance).toBe(null);
    expect(d.events[0].id).toBe("e1");
    expect(d.evidence.find((e) => e.field === "name")?.status).toBe(
      "Unverified",
    );
  });
  it("downgrades verified values lacking URL and ignores unsafe URLs", () => {
    const d = normalizeDataset({
      events: [{ id: "e", name: "A" }],
      evidence: [
        {
          id: "x",
          entityId: "e",
          field: "name",
          value: "A",
          status: "Verified",
          sourceUrl: "javascript:alert(1)",
        },
      ],
    });
    expect(d.evidence[0].status).toBe("Needs Review");
    expect(safeUrl("data:text/html,x")).toBe(null);
    expect(effectiveStatus({ ...d.evidence[0], value: null })).toBe("Missing");
  });
  it("rejects duplicate identities and invalid dataset structures", () => {
    expect(() => normalizeDataset([{ id: "e" }, { id: "e" }])).toThrow(/重复/);
    expect(() => normalizeDataset({})).toThrow();
    expect(() => normalizeDataset([null])).toThrow();
  });
  it("does not guess coordinate systems or map unverified values", () => {
    const d = normalizeDataset({
      events: [],
      venues: [
        {
          id: "v",
          coordinates: {
            lng: 120.7,
            lat: 31.3,
            status: "Verified",
            sourceUrl: "https://amap.com",
          },
        },
      ],
    });
    expect(d.venues[0].coordinates).toBe(null);
    expect(
      verifiedCoords({
        lng: 120,
        lat: 31,
        system: "GCJ-02",
        status: "Unverified",
        sourceUrl: "https://amap.com",
      }),
    ).toBe(false);
  });
});
describe("Proximity and graph", () => {
  it("uses checked GCJ coordinates, computes distance and refuses unverified locations", () => {
    const a = sampleDataset.hotels[0].coordinates!;
    const b = sampleDataset.venues[0].coordinates!;
    expect(distanceKm(a, a)).toBe(0);
    expect(distanceKm(a, b)).toBeGreaterThan(0.4);
    expect(distanceKm(a, b)).toBeLessThan(0.7);
    expect(distanceKm(a, { ...b, status: "Unverified" })).toBe(null);
  });
  it("creates demo supported topology without direct Event-Hotel impact edges", () => {
    const g = createRepository(sampleDataset).getGraphData("demo-01");
    expect(g.nodes.map((n) => n.kind)).toEqual([
      "Event",
      "Venue",
      "District",
      "Hotel",
    ]);
    expect(g.edges).toHaveLength(4);
    expect(g.edges.filter((e) => e.demo)).toHaveLength(3);
    expect(g.edges.find((e) => e.label.startsWith("NEAR"))?.demo).toBe(false);
    expect(
      g.edges.some((e) => e.source === "demo-01" && e.target.startsWith("h-")),
    ).toBe(false);
  });
  it("does not locate a real event from venue coordinates alone", () => {
    const data: typeof sampleDataset = {
      ...sampleDataset,
      events: [{ ...sampleDataset.events[0], id: "real", demo: false }],
      evidence: [],
    };
    expect(eventCoordinates(data.events[0], data)).toBe(null);
    data.evidence = [
      {
        ...sampleDataset.evidence[0],
        id: "verified-held",
        entityId: "real",
        field: "venueId",
        value: "v-expo",
        status: "Verified",
        sourceUrl: "https://example.org/event",
      },
    ] as typeof data.evidence;
    expect(eventCoordinates(data.events[0], data)?.lng).toBe(120.707374);
  });
  it("marks an unverified held-at relationship as a candidate instead of hiding it", () => {
    // 规则变化（第 28 轮）：未核验的场馆不再整条隐藏——图谱会因为核验率低而空成两三个点，
    // 用户会以为图坏了。现在画出来但**明确标成候选**（analytical + 标签带「待核验」），
    // 绝不把未核验说成已核验。
    const d = normalizeDataset({
      events: [{ id: "e", name: "A", venueId: "v" }],
      venues: [{ id: "v", name: "V" }],
    });
    const graph = createRepository(d).getGraphData("e");
    expect(graph.nodes).toHaveLength(2);
    const venue = graph.nodes.find((node) => node.id === "v");
    expect(venue?.analytical).toBe(true);
    const edge = graph.edges.find((item) => item.target === "v");
    expect(edge?.label).toContain("待核验");
  });
});
