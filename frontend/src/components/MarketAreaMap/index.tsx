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
        const exposeView = () => {
          try {
            const zoom = map.current.getZoom();
            const center = map.current.getCenter();
            (window as unknown as Record<string, unknown>).__mapView = {
              zoom, lng: center.lng, lat: center.lat, at: Date.now(),
            };
          } catch {
            /* 未就绪 */
          }
        };
        map.current.on("zoomend", exposeView);
        map.current.on("moveend", exposeView);
        map.current.on("complete", () => {
          // 缩放与比例尺：地图能自己操作，不依赖外部按钮
          const AMapNS = (window as unknown as { AMap?: any }).AMap;
          if (AMapNS) {
            if (AMapNS.Scale) map.current.addControl(new AMapNS.Scale());
            if (AMapNS.ToolBar) map.current.addControl(new AMapNS.ToolBar({ position: "RB" }));
          }
          draw();
        });
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

    const hasSelection = Boolean(selectedId);
    areas.forEach((area) => {
      const active = area.id === selectedId;
      const color = area.status === "official" ? "#2563EB" : "#0F766E";
      const size = active ? 20 : hasSelection ? 9 : 12;
      const dot = document.createElement("div");
      dot.className = "market-area-dot";
      dot.style.width = dot.style.height = size + "px";
      dot.style.borderRadius = "50%";
      dot.style.cursor = "pointer";
      dot.style.boxSizing = "border-box";
      dot.style.background = area.status === "official" ? color : "#fff";
      dot.style.border = "2px solid " + color;
      if (active) dot.style.boxShadow = "0 0 0 7px rgba(37,99,235,0.20)";
      if (!active && hasSelection) dot.style.opacity = "0.45";
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
      // 不改变用户当前的缩放与中心：只画范围圆，避免"点一下就变大变位"（用户反馈过）
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

  return (
    <div className="market-area-wrap">
      <div ref={container} className="market-area-map" style={{ height }} role="img" aria-label="商圈中心点地图" />
      <ul className="market-area-legend" aria-label="地图图例">
        <li>
          <span className="legend-dot official" /> 官方商圈
        </li>
        <li>
          <span className="legend-dot candidate" /> 参考地点（非官方商圈）
        </li>
        <li>
          <span className="legend-dot selected" /> 选中后显示该地点范围（估算，不是边界）
        </li>
      </ul>
    </div>
  );
}
