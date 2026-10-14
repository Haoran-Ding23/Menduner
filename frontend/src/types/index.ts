export type Status =
  | "Verified"
  | "Unverified"
  | "Missing"
  | "Conflicting"
  | "Needs Review";
export type Category =
  | "government"
  | "business"
  | "culture"
  | "education"
  | "sports"
  | "folk"
  | "others";
export interface Coordinates {
  lng: number;
  lat: number;
  system: "GCJ-02";
  status: Status;
  sourceUrl: string | null;
}
export interface Evidence {
  id: string;
  entityId: string;
  field: string;
  value: unknown;
  status: Status;
  method: string;
  sourceName: string | null;
  sourceUrl: string | null;
  updatedAt: string;
  note?: string;
  sourceRole?: "official_organizer" | "government" | "venue" | "other";
  confidence?: number;
  confidenceMethod?: string;
  /** Why this field has its current status: an automatic rule or a human decision. */
  origin?: string;
  /** "automatic" for the auto-verification rule, otherwise the reviewer's name. */
  decidedBy?: string;
  decidedReason?: string;
  decidedAt?: string;
}
export interface Event {
  id: string;
  name: string;
  category: Category;
  startDate: string | null;
  endDate: string | null;
  venueId: string | null;
  districtId: string | null;
  organizer: string | null;
  attendance: number | null;
  sponsor: string | null;
  demo: boolean;
  raw?: Record<string, unknown>;
}
export interface Venue {
  id: string;
  name: string;
  address: string | null;
  districtId: string | null;
  coordinates: Coordinates | null;
  districtDemo: boolean;
}
export interface Hotel {
  id: string;
  name: string;
  address: string | null;
  districtId: string | null;
  coordinates: Coordinates | null;
  districtDemo: boolean;
  /** Portfolio tier. The grade comes from the source's own classification, not from judgement. */
  tier?: "high" | "mid" | "comfort";
  tierLabel?: string | null;
  tierSource?: string | null;
  tierEvidence?: string | null;
}
export interface District {
  id: string;
  name: string;
  demo: boolean;
  description: string;
}
export interface GraphNode {
  id: string;
  label: string;
  kind: "Event" | "Venue" | "District" | "Hotel";
  explanation?: string;
  analytical?: boolean;
  demo: boolean;
  entityId: string;
}
export interface GraphEdge {
  analytical?: boolean;
  id: string;
  source: string;
  target: string;
  label: string;
  demo: boolean;
}
export interface Dataset {
  events: Event[];
  venues: Venue[];
  hotels: Hotel[];
  districts: District[];
  evidence: Evidence[];
  updatedAt: string;
}
export interface Filters {
  year: number;
  month: number;
  district: string;
  category: string;
  includeDemo: boolean;
  /** Show events that finished more than 30 days ago; hidden from the working view by default. */
  includePast: boolean;
}
