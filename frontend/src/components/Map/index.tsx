import { assessDemand } from "../../services/intelligence";
import { useEffect, useRef, useState } from "react";
import { Alert, Button, Spin, Modal, Empty, Table } from "antd";
import AMapLoader from "@amap/amap-jsapi-loader";
import type { Event, Hotel } from "../../types";
import { usePlatform } from "../../hooks/usePlatform";
import VenueEvents from "../VenueEvents";
import {
  verifiedCoords,
  categories,
  eventCoordinates,
  eventLocation,
  HOTSPOT_MIN,
} from "../../utils/data";
// SDK has no bundled TypeScript declarations; keep dynamic types at this boundary only.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SDK = any;
declare global {
  interface Window {
    // AMap accepts either a proxy host for its REST calls or the console-issued security code.
    // Production uses the proxy so the code stays server-side; a local build with no proxy can
    // fall back to the code.
    _AMapSecurityConfig?: {
      serviceHost?: string;
      securityJsCode?: string;
    };
  }
}
let loading: Promise<SDK> | null = null;
/**
 * Where the AMap JS API should send its REST calls, or null when there is no usable proxy.
 *
 * The security key must not ship in the bundle, so AMap wants those calls proxied (the dev
 * server provides `/_AMapService` in vite.config.ts). That relative path is meaningless once the
 * app is served by nginx: the SPA fallback answers it with index.html, and the SDK — which asks
 * for JSON and JSONP — receives HTML and dies with `SyntaxError: Unexpected token '<'` on every
 * page that shows a map. That is not hypothetical: it was the whole of the recorded frontend
 * error log until this guard existed.
 *
 * So a relative host is accepted in development only. A production build accepts the setting
 * only when it points at a different origin, i.e. a real deployed proxy. Returning null leaves
 * the SDK calling AMap directly: the map body, markers and circles work, custom map styles fall
 * back to the default (documented in deploy/DEPLOY.md).
 */
export function amapServiceHost(
  configured: string | undefined,
  { dev, origin }: { dev: boolean; origin: string },
): string | null {
  if (!configured) return null;
  let url: URL;
  try {
    url = new URL(configured, origin);
  } catch {
    return null;
  }
  if (!url.pathname.replace(/\/+$/, "").endsWith("/_AMapService")) return null;
  if (!dev && url.origin === origin) return null;
  return url.href;
}
function loadSDK() {
  const key = import.meta.env.VITE_AMAP_KEY;
  // AMap JS API v2 refuses to render without either a proxy host (production) or the security
  // code (a local build where no proxy exists). Only the code path is offered as a fallback, and
  // it is read from an optional env var that is not present in the production build, so the
  // secret never ships there.
  const securityCode = import.meta.env.VITE_AMAP_SECURITY_CODE;
  const host = amapServiceHost(import.meta.env.VITE_AMAP_SERVICE_HOST, {
    dev: import.meta.env.DEV,
    origin: window.location.origin,
  });
  if (!key) return Promise.reject(new Error("configuration"));
  if (!loading) {
    if (host) window._AMapSecurityConfig = { serviceHost: host };
    else if (securityCode) window._AMapSecurityConfig = { securityJsCode: securityCode };
    loading = AMapLoader.load({
      key,
      version: "2.0",
      plugins: ["AMap.Scale", "AMap.ToolBar", "AMap.Circle"],
    }).catch(() => {
      loading = null;
      throw new Error("load");
    });
  }
  return loading;
}
export default function EventMap({
  events,
  hotel,
  demandLayer = false,
  radiusKm,
}: {
  events: Event[];
  hotel?: Hotel;
  demandLayer?: boolean;
  /** Draw the reviewed demand radius around the selected hotel, in kilometres. */
  radiusKm?: number;
}) {
  const { dataset, repository, selected, openEvent, go } = usePlatform();
  // 只在聚焦目标变化时居中，避免用户手动拖动后被反复拉回
  const lastFocusedId = useRef<string | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<SDK>(null);
  const sdk = useRef<SDK>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [group, setGroup] = useState<Event[] | null>(null);
  const [groupName, setGroupName] = useState("");
  const [groupVenue, setGroupVenue] = useState<string | null>(null);
  const [showVenueAll, setShowVenueAll] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    // AMap reads the container size once, at construction, and keeps it. On a phone the
    // container changes size constantly — rotating the device, the browser chrome collapsing
    // as the address bar hides, and the CSS switching .map-shell to a viewport-relative height
    // all move it — and without a resize the map keeps drawing at its old dimensions, which
    // shows up as a grey band or a map that is the wrong shape. Nothing in CSS can fix that:
    // the library has to be told.
    let observer: ResizeObserver | undefined;
    setReady(false);
    setError("");
    timeout = setTimeout(() => {
      if (!cancelled)
        setError("地图加载超时，请检查网络、密钥域名限制和本地代理。");
    }, 20000);
    loadSDK()
      .then((A) => {
        if (cancelled || !container.current) return;
        sdk.current = A;
        map.current = new A.Map(container.current, {
          zoom: 12,
          center: [120.716, 31.293],
          viewMode: "2D",
        });
        map.current.addControl(new A.Scale());
        map.current.addControl(new A.ToolBar());
        if (typeof ResizeObserver !== "undefined") {
          observer = new ResizeObserver(() => {
            // Guarded: the observer fires once during construction, before the map is usable,
            // and resize() on a half-built map throws.
            if (!cancelled && map.current) map.current.resize();
          });
          observer.observe(container.current);
        }
        map.current.on("complete", () => {
          if (!cancelled) {
            clearTimeout(timeout);
            setError("");
            setReady(true);
          }
        });
        map.current.on("error", () => {
          if (!cancelled) setError("高德地图加载失败，请检查配置。");
        });
      })
      .catch((e) => {
        if (!cancelled) {
          clearTimeout(timeout);
          setError(
            e.message === "configuration"
              ? "地图待配置：请设置 Web JSAPI 密钥与安全代理。"
              : "地图暂不可用：请检查网络、域名白名单和安全代理。",
          );
        }
      });
    return () => {
      cancelled = true;
      clearTimeout(timeout);
      observer?.disconnect();
      map.current?.destroy();
      map.current = null;
    };
  }, [attempt]);
  useEffect(() => {
    if (!ready || !map.current) return;
    const A = sdk.current;
    map.current.clearMap();
    const grouped = new Map<
      string,
      {
        events: Event[];
        lng: number;
        lat: number;
        name: string;
        venueId: string;
      }
    >();
    for (const e of events) {
      const venue = repository.getVenues().find((v) => v.id === e.venueId);
      const c = eventCoordinates(e, dataset);
      if (!c || !venue) continue;
      const key = `${c.lng},${c.lat}`;
      const g = grouped.get(key) ?? {
        events: [],
        lng: c.lng,
        lat: c.lat,
        name: venue.name,
        venueId: venue.id,
      };
      g.events.push(e);
      grouped.set(key, g);
    }
    const markers: SDK[] = [];
    grouped.forEach((g) => {
      const first = g.events[0];
      const el = document.createElement("button");
      const isHotspot = g.events.length >= HOTSPOT_MIN;
      // A venue programming three or more events is where the city is heating up, so its marker
      // is bigger and ringed. The colour still encodes the dominant category.
      el.className = isHotspot ? "map-marker map-marker-hotspot" : "map-marker";
      el.style.background = categories[first.category].color;
      el.textContent =
        g.events.length > 1 ? String(g.events.length) : first.demo ? "D" : "•";
      el.setAttribute(
        "aria-label",
        `${g.name}，${g.events.length} 个活动${isHotspot ? "，热点场馆" : ""}`,
      );
      const marker = new A.Marker({
        position: [g.lng, g.lat],
        content: el,
        anchor: "center",
        title: g.name,
      });
      marker.on("click", () => {
        // A single event at a spot opens it directly. Where a venue programmes several
        // events, list them all instead of silently opening an arbitrary one.
        if (g.events.length === 1) openEvent(first.id);
        else {
          setGroup(g.events);
          setGroupName(g.name);
          setGroupVenue(g.venueId);
        }
      });
      markers.push(marker);
    });
    if (demandLayer) {
      const relevant = new Set(
        events.flatMap((event) =>
          assessDemand(event, dataset).nearbyHotels.map(
            (item) => item.hotel.id,
          ),
        ),
      );
      dataset.hotels
        .filter((h) => relevant.has(h.id) && h.id !== hotel?.id)
        .forEach((h) => {
          const el = document.createElement("button");
          el.className = "map-marker hotel-marker";
          el.textContent = "H";
          el.setAttribute("aria-label", h.name);
          el.addEventListener("click", () =>
            go("/hotels", undefined, { hotel: h.id }),
          );
          markers.push(
            new A.Marker({
              position: [h.coordinates!.lng, h.coordinates!.lat],
              content: el,
              anchor: "center",
              title: h.name,
            }),
          );
        });
      const event = events.find((e) => e.id === selected);
      const c = event ? eventCoordinates(event, dataset) : null;
      if (event && c)
        assessDemand(event, dataset).nearbyHotels.forEach(({ hotel: h }) => {
          const line = new A.Polyline({
            path: [
              [c.lng, c.lat],
              [h.coordinates!.lng, h.coordinates!.lat],
            ],
            strokeColor: "#13aaba",
            strokeWeight: 2,
            strokeStyle: "dashed",
          });
          map.current.add(line);
        });
    }
    if (hotel && verifiedCoords(hotel.coordinates)) {
      const el = document.createElement("div");
      el.className = "map-marker hotel-marker";
      el.textContent = "H";
      markers.push(
        new A.Marker({
          position: [hotel.coordinates.lng, hotel.coordinates.lat],
          content: el,
          anchor: "center",
          title: hotel.name,
        }),
      );
      // The demand radius is the one boundary this product can honestly draw: it is the
      // distance filter the page already applies, made visible. It is a straight-line
      // GCJ-02 radius, not a travel-time isochrone, so it is labelled as such.
      if (radiusKm && radiusKm > 0) {
        map.current.add(
          new A.Circle({
            center: [hotel.coordinates.lng, hotel.coordinates.lat],
            radius: radiusKm * 1000,
            strokeColor: "#1677ff",
            strokeWeight: 2,
            strokeStyle: "dashed",
            strokeOpacity: 0.9,
            fillColor: "#1677ff",
            fillOpacity: 0.06,
            zIndex: 5,
          }),
        );
      }
    }
    map.current.add(markers);
    if (markers.length)
      map.current.setFitView(markers, false, [70, 70, 70, 70], 14);
    // 关键：在全量数据集里找，避免该活动被当前筛选条件筛掉后无法定位；
    // 用 eventLocation 区分「坐标不可用」与「场馆关联未核验（给参考位置）」。
    const focusEvent =
      dataset.events.find((e) => e.id === selected) ?? events.find((e) => e.id === selected);
    const located = focusEvent ? eventLocation(focusEvent, dataset) : null;
    if (located?.coords && lastFocusedId.current !== selected) {
      lastFocusedId.current = selected;
      map.current.setZoomAndCenter(15, [located.coords.lng, located.coords.lat]);
      // 便于自动化核验：记录本次定位目标（只读，不改地图行为）
      (window as unknown as Record<string, unknown>).__mapFocus = {
        eventId: selected,
        lng: located.coords.lng,
        lat: located.coords.lat,
        verifiedLink: located.verifiedLink,
        focusedAt: Date.now(),
      };
    }
  }, [
    ready,
    events,
    hotel,
    dataset,
    repository,
    selected,
    openEvent,
    demandLayer,
    go,
    radiusKm,
  ]);
  return (
    <div className="map-shell">
      <div
        className="amap-container"
        ref={container}
        aria-label="活动地图"
      />
      {!ready && !error && (
        <div className="map-state">
          <Spin size="large" />
          <h3>正在连接高德地图</h3>
          <p>AMap JavaScript API 2.0</p>
        </div>
      )}
      {error && (
        <div className="map-state">
          <span className="map-symbol">⌖</span>
          <h2>城市活动地图</h2>
          <Alert type="warning" message={error} />
          <p>活动列表、日历、图谱和证据仍可使用。</p>
          <Button onClick={() => setAttempt((v) => v + 1)}>重新连接</Button>
        </div>
      )}
      <div className="map-caption">
        AMap 2.0 · 仅核验坐标上图 · D = DEMO · H = 酒店
        {radiusKm
          ? ` · 蓝色虚线为 \ km 直线半径（非出行时间）`
          : ""}
      </div>
      <Modal
        title={(showVenueAll && groupVenue ? groupName + " · 该场馆全部活动" : groupName + " · 同址活动")}
        open={!!group}
        onCancel={() => {
          setGroup(null);
          setShowVenueAll(false);
        }}
        width={showVenueAll ? 860 : 520}
        footer={null}
      >
        {showVenueAll && groupVenue ? (
          <VenueEvents
            venueId={groupVenue}
            onClose={() => setShowVenueAll(false)}
          />
        ) : (
          <>
            {group?.length ? (
              <Table<Event>
                rowKey="id"
                dataSource={group}
                size="small"
                pagination={false}
                columns={[
                  {
                    title: "日期",
                    width: 180,
                    render: (_, e) =>
                      e.startDate
                        ? e.endDate && e.endDate !== e.startDate
                          ? `${e.startDate} → ${e.endDate}`
                          : e.startDate
                        : "待确认",
                  },
                  {
                    title: "活动",
                    dataIndex: "name",
                    render: (_, e) => (
                      <Button
                        type="link"
                        size="small"
                        style={{ padding: 0, height: "auto", textAlign: "left" }}
                        onClick={() => {
                          openEvent(e.id);
                          setGroup(null);
                        }}
                      >
                        {e.name}
                      </Button>
                    ),
                  },
                ]}
              />
            ) : (
              <Empty description="无同址活动" />
            )}
            {groupVenue && (
              <Button
                className="gap-bottom"
                style={{ marginTop: 12 }}
                onClick={() => setShowVenueAll(true)}
              >
                查看该场馆全部活动
              </Button>
            )}
          </>
        )}
      </Modal>
    </div>
  );
}
