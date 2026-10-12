import { assessDemand } from "../../services/intelligence";
import { useEffect, useRef, useState } from "react";
import { Alert, Button, Spin, Modal } from "antd";
import AMapLoader from "@amap/amap-jsapi-loader";
import type { Event, Hotel } from "../../types";
import { usePlatform } from "../../hooks/usePlatform";
import { verifiedCoords, categories, eventCoordinates } from "../../utils/data";
// SDK has no bundled TypeScript declarations; keep dynamic types at this boundary only.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SDK = any;
declare global {
  interface Window {
    _AMapSecurityConfig?: {
      serviceHost: string;
    };
  }
}
let loading: Promise<SDK> | null = null;
function loadSDK() {
  const key = import.meta.env.VITE_AMAP_KEY;
  const host = import.meta.env.VITE_AMAP_SERVICE_HOST;
  if (!key || !host || !host.endsWith("/_AMapService"))
    return Promise.reject(new Error("configuration"));
  if (!loading) {
    window._AMapSecurityConfig = {
      serviceHost: new URL(host, window.location.origin).href,
    };
    loading = AMapLoader.load({
      key,
      version: "2.0",
      plugins: ["AMap.Scale", "AMap.ToolBar"],
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
}: {
  events: Event[];
  hotel?: Hotel;
  demandLayer?: boolean;
}) {
  const { dataset, repository, selected, openEvent, go } = usePlatform();
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<SDK>(null);
  const sdk = useRef<SDK>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [group, setGroup] = useState<Event[] | null>(null);
  const [groupName, setGroupName] = useState("");
  useEffect(() => {
    let cancelled = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    setReady(false);
    setError("");
    timeout = setTimeout(() => {
      if (!cancelled)
        setError("地图加载超时，请检查网络、Key 域名限制和本地代理。");
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
              ? "地图待配置：设置 Web JSAPI Key 与安全代理。"
              : "地图暂不可用：请检查网络、域名白名单和安全代理。",
          );
        }
      });
    return () => {
      cancelled = true;
      clearTimeout(timeout);
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
      };
      g.events.push(e);
      grouped.set(key, g);
    }
    const markers: SDK[] = [];
    grouped.forEach((g) => {
      const first = g.events[0];
      const el = document.createElement("button");
      el.className = "map-marker";
      el.style.background = categories[first.category].color;
      el.textContent =
        g.events.length > 1 ? String(g.events.length) : first.demo ? "D" : "•";
      el.setAttribute("aria-label", `${g.name}，${g.events.length} 个活动`);
      const marker = new A.Marker({
        position: [g.lng, g.lat],
        content: el,
        anchor: "center",
        title: g.name,
      });
      marker.on("click", () => {
        if (g.events.length === 1) openEvent(first.id);
        else {
          setGroup(g.events);
          setGroupName(g.name);
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
    }
    map.current.add(markers);
    if (markers.length)
      map.current.setFitView(markers, false, [70, 70, 70, 70], 14);
    const event = events.find((e) => e.id === selected);
    const c = event ? eventCoordinates(event, dataset) : null;
    if (c) map.current.setZoomAndCenter(14, [c.lng, c.lat]);
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
  ]);
  return (
    <div className="map-shell">
      <div
        className="amap-container"
        ref={container}
        aria-label="苏州高德地图"
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
          <h2>苏州城市活动地图</h2>
          <Alert type="warning" message={error} />
          <p>活动列表、日历、图谱和证据仍可使用。</p>
          <Button onClick={() => setAttempt((v) => v + 1)}>重新连接</Button>
        </div>
      )}
      <div className="map-caption">
        AMap 2.0 · 仅核验坐标上图 · D = DEMO · H = 酒店
      </div>
      <Modal
        title={groupName + " · 同址活动"}
        open={!!group}
        onCancel={() => setGroup(null)}
        footer={null}
      >
        {group?.map((e) => (
          <Button
            block
            className="gap-bottom"
            key={e.id}
            onClick={() => {
              openEvent(e.id);
              setGroup(null);
            }}
          >
            {e.name}
            {e.demo ? " · DEMO" : ""}
          </Button>
        ))}
      </Modal>
    </div>
  );
}
