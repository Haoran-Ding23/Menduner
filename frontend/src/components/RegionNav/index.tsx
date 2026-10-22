import { useMemo } from "react";
import { Button, Space, Tag, Tooltip } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import type { District } from "../../types";

/**
 * Region navigation for the map: 苏州市, then each of its parts.
 *
 * The demand side in the interviews thinks hierarchically and locally - a hotel in 太仓 asked
 * about 太仓's calendar first, and only then about the rest of Suzhou. The previous map had one
 * global view and a flat dropdown, which made the county-level cities a footnote of a Suzhou
 * centred on the old town.
 *
 * The two groups are not a stylistic choice. Suzhou administers five 市辖区 directly and four
 * 代管县级市, and the distinction matters to the reader because the county-level cities are
 * separate places with their own event calendars. Grouping them this way says so.
 *
 * 苏州工业园区 is absent on purpose: it is a development zone, not an administrative division,
 * and AMap places its venues in 吴中区. Inventing a region for it would make this list disagree
 * with the authority it cites. The township is stored on the venue, so the finer geography is
 * still reachable.
 */
export const DEFAULT_REGION = "taicang";
const ALL = "all";

// Display order: 代管市 first because they are what the 太仓 entry point leads into, then the
// 市辖区 from the historic centre outwards.
const ORDER = [
  "taicang", "changshu", "kunshan", "zhangjiagang",
  "gusu", "huqiu", "wuzhong", "xiangcheng", "wujiang",
];

export default function RegionNav() {
  const { dataset, filters, update } = usePlatform();

  const regions = useMemo(() => {
    const byId = new Map<string, District>();
    for (const d of dataset.districts) {
      // business_area / subdistrict rows come from an older geocoding model and are not
      // regions a reader can navigate; only the administrative ones are offered.
      if (d.kind === "district" || d.kind === "county_city") byId.set(d.id, d);
    }
    return [...byId.values()].sort(
      (a, b) =>
        (ORDER.indexOf(a.id) + 1 || 99) - (ORDER.indexOf(b.id) + 1 || 99),
    );
  }, [dataset.districts]);

  const countyCities = regions.filter((r) => r.kind === "county_city");
  const districts = regions.filter((r) => r.kind === "district");

  // No ?district= means the default entry point, so a first visit lands on 太仓 rather than on
  // the whole of Suzhou. "全市" is an explicit choice and travels as district=all. The default
  // only applies when the region is really in the data, so a dataset without it opens on 全市
  // instead of showing no selected region and an empty map.
  const hasDefault = regions.some((r) => r.id === DEFAULT_REGION);
  const active = filters.district || (hasDefault ? DEFAULT_REGION : ALL);
  const activeRegion = regions.find((r) => r.id === active);

  // What each region holds, so a button never hides its own size.
  const counts = useMemo(() => {
    const byRegion = new Map<string, number>();
    const venueRegion = new Map<string, string>();
    for (const venue of dataset.venues) {
      if (venue.districtId) venueRegion.set(venue.id, venue.districtId);
    }
    for (const event of dataset.events) {
      if (event.demo && !filters.includeDemo) continue;
      const region = event.districtId ?? (event.venueId ? venueRegion.get(event.venueId) : null);
      if (!region) continue;
      byRegion.set(region, (byRegion.get(region) ?? 0) + 1);
    }
    return byRegion;
  }, [dataset.events, dataset.venues, filters.includeDemo]);

  const chip = (region: District) => (
    <Button
      key={region.id}
      size="small"
      type={active === region.id ? "primary" : "default"}
      onClick={() => update({ district: region.id })}
      aria-pressed={active === region.id}
    >
      {region.name}
      <span className="region-count">{counts.get(region.id) ?? 0}</span>
    </Button>
  );

  return (
    <section className="region-nav" aria-label="地区导航">
      <div className="region-nav-head">
        {/* Plain markup rather than antd's Breadcrumb: that renders its own <nav> landmark,
            and the workspace already has one for the sidebar, so the page ended up with two
            navigation landmarks and no way to name either. */}
        <span className="region-crumbs">
          <a onClick={() => update({ district: ALL })} role="button">
            苏州市
          </a>
          <span className="muted"> / </span>
          <strong>{activeRegion ? activeRegion.name : "全市"}</strong>
        </span>
        <Space size={6}>
          {activeRegion?.kind === "county_city" && (
            <Tag color="blue">代管县级市</Tag>
          )}
          {activeRegion?.kind === "district" && <Tag color="purple">市辖区</Tag>}
          {active === ALL && <Tag>全市</Tag>}
        </Space>
      </div>

      <div className="region-nav-row">
        <small className="muted region-nav-label">代管市</small>
        <Space wrap size={6}>
          {countyCities.map(chip)}
        </Space>
      </div>
      <div className="region-nav-row">
        <small className="muted region-nav-label">市辖区</small>
        <Space wrap size={6}>
          {districts.map(chip)}
          <Tooltip title="苏州工业园区是功能区，不是行政区；园区内的场馆在行政上属吴中区，因此没有单独列出">
            <Button
              size="small"
              type={active === ALL ? "primary" : "default"}
              onClick={() => update({ district: ALL })}
            >
              苏州全市
            </Button>
          </Tooltip>
        </Space>
      </div>
    </section>
  );
}
