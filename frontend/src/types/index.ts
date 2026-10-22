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
  /**
   * What kind of region this is, so the interface can group them the way Suzhou is actually
   * organised: 市辖区 (districts) and 代管县级市 (county-level cities) sit side by side under
   * 苏州市. Older rows carry business-area kinds and are not offered as regions at all.
   */
  kind?: "city" | "district" | "county_city" | "business_area" | "subdistrict";
  parentId?: string | null;
  level?: number;
}
/**
 * A restaurant or a public-transport stop around a venue, taken from the source's own POI record.
 *
 * The row keeps the AMap place URL and the declared type string it was classified from, because
 * the knowledge graph draws a relation to it: "0.42 km from this venue" is only checkable when
 * the coordinate behind it is.
 */
export interface Place {
  id: string;
  kind: "restaurant" | "transport";
  /** The source's own middle category: 中餐厅 / 咖啡厅 / 地铁站 / 公交车站 / 火车站 / 机场 … */
  subtype: string;
  name: string;
  address: string | null;
  city: string | null;
  district: string | null;
  coordinates: Coordinates | null;
  declaredType: string | null;
  /** The venue this row was sampled around, and the radius that defined the sample. */
  sampledNearVenueId: string | null;
  sampledRadiusM: number | null;
  distanceToVenueKm: number | null;
}
export type GraphNodeKind =
  | "Event"
  | "Venue"
  | "District"
  | "Hotel"
  | "Restaurant"
  | "Transport"
  | "Audience";
export interface GraphNode {
  id: string;
  label: string;
  kind: GraphNodeKind;
  explanation?: string;
  analytical?: boolean;
  demo: boolean;
  entityId: string;
  /** The rule that put this node in the graph, and why it applies to this event. */
  rule?: string;
  reason?: string;
  /** The record behind the node, when it has one (AMap place, source page, …). */
  sourceUrl?: string | null;
}
export interface GraphEdge {
  analytical?: boolean;
  id: string;
  source: string;
  target: string;
  label: string;
  demo: boolean;
  /** Same contract as on the node: which rule drew this relation. */
  rule?: string;
  reason?: string;
}
/** One rule that fired for the selected event, with how many relations it produced. */
export interface FiredRule {
  id: string;
  label: string;
  detail: string;
  relations: number;
  analytical: boolean;
}
export interface Dataset {
  events: Event[];
  venues: Venue[];
  hotels: Hotel[];
  districts: District[];
  places: Place[];
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
