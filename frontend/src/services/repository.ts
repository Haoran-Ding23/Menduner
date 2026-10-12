import { nearbyHotels } from "./intelligence";
import events from "../data/events.json";
import venues from "../data/venues.json";
import hotels from "../data/hotels.json";
import districts from "../data/districts.json";
import evidence from "../data/evidence.json";
import meta from "../data/meta.json";
import { normalizeDataset } from "./adapter";
import type { Dataset, GraphNode, GraphEdge } from "../types";
import { effectiveStatus } from "../utils/data";
export const sampleDataset = normalizeDataset({
  events,
  venues,
  hotels,
  districts,
  evidence,
  ...meta,
});
export function createRepository(dataset: Dataset) {
  return {
    getEvents: () => dataset.events,
    getEventById: (id: string) => dataset.events.find((e) => e.id === id),
    getVenues: () => dataset.venues,
    getHotels: () => dataset.hotels,
    getDistricts: () => dataset.districts,
    getEvidence: (id: string) =>
      dataset.evidence.filter((e) => e.entityId === id),
    getGraphData: (id: string) => {
      const event = dataset.events.find((e) => e.id === id);
      const nodes: GraphNode[] = [],
        edges: GraphEdge[] = [];
      if (!event) return { nodes, edges };
      const add = (
        entityId: string,
        label: string,
        kind: GraphNode["kind"],
        demo: boolean,
      ) => {
        if (!nodes.some((n) => n.id === entityId))
          nodes.push({ id: entityId, label, kind, demo, entityId });
      };
      const supported = (entityId: string, field: string, value: unknown) =>
        !dataset.evidence.some(
          (e) =>
            e.entityId === entityId &&
            e.field === field &&
            ["Conflicting", "Needs Review"].includes(effectiveStatus(e)),
        ) &&
        dataset.evidence.some(
          (e) =>
            e.entityId === entityId &&
            e.field === field &&
            e.value === value &&
            effectiveStatus(e) === "Verified",
        );
      add(event.id, event.name, "Event", event.demo);
      const venue = dataset.venues.find((v) => v.id === event.venueId);
      if (
        venue &&
        (event.demo || supported(event.id, "venueId", event.venueId))
      ) {
        add(venue.id, venue.name, "Venue", false);
        edges.push({
          id: "held-" + id,
          source: id,
          target: venue.id,
          label: "HELD_AT",
          demo: event.demo,
        });
        const district = dataset.districts.find(
          (d) => d.id === venue.districtId,
        );
        if (
          district &&
          (venue.districtDemo ||
            supported(venue.id, "districtId", venue.districtId))
        ) {
          add(district.id, district.name, "District", district.demo);
          edges.push({
            id: "located-" + venue.id,
            source: venue.id,
            target: district.id,
            label: "LOCATED_IN",
            demo: venue.districtDemo,
          });
          dataset.hotels
            .filter(
              (h) =>
                h.districtId === district.id &&
                (h.districtDemo || supported(h.id, "districtId", h.districtId)),
            )
            .forEach((h) => {
              add(h.id, h.name, "Hotel", false);
              edges.push({
                id: "hotel-" + h.id,
                source: h.id,
                target: district.id,
                label: "LOCATED_IN",
                demo: h.districtDemo,
              });
            });
        }
      }
      // Coordinate-derived proximity connects resources without asserting economic impact.
      if (venue && nodes.some((n) => n.id === venue.id)) {
        nearbyHotels(event, dataset).forEach(({ hotel, distance }) => {
          add(hotel.id, hotel.name, "Hotel", false);
          edges.push({
            id: `near-${venue.id}-${hotel.id}`,
            source: venue.id,
            target: hotel.id,
            label: `NEAR · ${distance.toFixed(2)} km`,
            demo: false,
          });
        });
      }
      return { nodes, edges };
    },
  };
}
export type Repository = ReturnType<typeof createRepository>;
