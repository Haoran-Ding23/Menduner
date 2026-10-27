import { useEffect, useRef } from "react";
import { loadAMapSDK } from "../Map";

/**
 * 商圈地图：把「中心点 + 半径」画出来，不画假边界。
 *
 * 为什么只画选中中心的圆：53 个 800 米圆同时画会大量重叠，用户会误以为那是真实商圈边界。
 * 所以默认只给点，选中后才显示它的范围圆（GPT Round 20 的方案②）。
 */
export type AreaPoint = {
  id: string;
  name: string;
  status: "official" | "candidate";
  lng: number;
  lat: number;
  radiusMeters: number;
};

export default function MarketAreaMap({
  areas,
  selectedId,
  onSelect,
  height = 420,
}: {
  areas: AreaPoint[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  height?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const map = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const overlays = useRef<any[]>([]);
  const selectedRef = useRef<string | null>(null);

  useEffect(() => {
    let disposed = false;
    loadAMapSDK()
      .then((AMap) => {
        if (disposed || !container.current || map.current) return;
        map.current = new AMap.Map(container.current, {
          zoom: 10,
          center: [120.62, 31.31],
          mapStyle: "amap://styles/whitesmoke",
        });
        map.current.on("complete", () => draw());
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
      if (map.current) {
        map.current.destroy();
        map.current = null;
      }
    };
    // 只在挂载时建图；绘制由下面的 effect 负责
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function draw() {
    const AMap = (window as unknown as { AMap?: any }).AMap;
    if (!AMap || !map.current) return;
    overlays.current.forEach((item) => item.setMap && item.setMap(null));
    overlays.current = [];

    areas.forEach((area) => {
      const active = area.id === selectedId;
      const color = area.status === "official" ? "#2563EB" : "#0F766E";
      const size = active ? 18 : 12;
      const dot = document.createElement("div");
      dot.className = "market-area-dot";
      dot.style.width = dot.style.height = size + "px";
      dot.style.borderRadius = "50%";
      dot.style.cursor = "pointer";
      dot.style.boxSizing = "border-box";
      dot.style.background = area.status === "official" ? color : "#fff";
      dot.style.border = "2px solid " + color;
      if (active) dot.style.boxShadow = "0 0 0 6px rgba(37,99,235,0.18)";
      dot.title = area.name + (area.status === "candidate" ? "（参考地点）" : "");
      dot.addEventListener("click", () => onSelect(area.id));

      const marker = new AMap.Marker({
        position: [area.lng, area.lat],
        content: dot,
        offset: new AMap.Pixel(-size / 2, -size / 2),
        zIndex: active ? 200 : 100,
      });
      marker.setMap(map.current);
      overlays.current.push(marker);
    });

    const active = areas.find((area) => area.id === selectedId);
    if (active) {
      const circle = new AMap.Circle({
        center: [active.lng, active.lat],
        radius: active.radiusMeters,
        strokeColor: "#2563EB",
        strokeOpacity: 0.6,
        strokeWeight: 1,
        fillColor: "#2563EB",
        fillOpacity: 0.08,
        zIndex: 50,
      });
      circle.setMap(map.current);
      overlays.current.push(circle);
      map.current.setZoomAndCenter(13, [active.lng, active.lat]);
    } else if (areas.length) {
      const bounds = new AMap.Bounds();
      areas.forEach((area) => bounds.extend([area.lng, area.lat]));
      map.current.setBounds(bounds, true);
    }
  }

  useEffect(() => {
    // 选中变化时只重绘覆盖物，不重建地图（避免闪烁与状态丢失）
    if (map.current && selectedRef.current !== selectedId) {
      selectedRef.current = selectedId;
      draw();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, areas]);

  return <div ref={container} className="market-area-map" style={{ height }} role="img" aria-label="商圈中心点地图" />;
}
