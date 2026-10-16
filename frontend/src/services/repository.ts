import events from "../data/events.json";
import venues from "../data/venues.json";
import hotels from "../data/hotels.json";
import districts from "../data/districts.json";
import places from "../data/places.json";
import evidence from "../data/evidence.json";
import meta from "../data/meta.json";
import { normalizeDataset } from "./adapter";
import type { Dataset } from "../types";
import { buildKnowledgeGraph } from "./knowledgeGraph";
export const sampleDataset = normalizeDataset({
  events,
  venues,
  hotels,
  districts,
  places,
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
    getGraphData: (id: string, options: { related?: boolean } = {}) => {
      const { nodes, edges } = buildKnowledgeGraph(
        dataset.events.find((e) => e.id === id),
        dataset,
        options,
      );
      return { nodes, edges };
    },
    /**
     * The full generated graph for one event: nodes, edges and the rules that fired.
     *
     * Regenerated on every call from the event's own fields and the records around its venue, so
     * a newly ingested event has a graph without anyone editing the graph code.
     */
    getGraph: (
      id: string,
      options: { related?: boolean; places?: boolean; audience?: boolean } = {},
    ) => buildKnowledgeGraph(dataset.events.find((e) => e.id === id), dataset, options),
    getPlaceById: (id: string) => dataset.places.find((p) => p.id === id),
  };
}
export type Repository = ReturnType<typeof createRepository>;
