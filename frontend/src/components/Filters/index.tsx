import { Select, Switch, Space, Button, Tooltip } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import { categories } from "../../utils/data";

/**
 * The shared filter bar.
 *
 * @param months   show the month strip
 * @param regions  show the region select. Turned off on the map page, which has its own
 *                 region navigation; two controls for one URL parameter stay in sync but read
 *                 as a duplicate, and the map's version can also say 太仓 by default.
 */
export default function Filters({
  months = true,
  regions = true,
}: {
  months?: boolean;
  regions?: boolean;
}) {
  const { filters, update, dataset, archivedCount } = usePlatform();

  // The dataset is one year on purpose: the archive was trimmed to 2026 so every number on the
  // page describes the same period. Offering 2027 or a past year would just produce an empty
  // screen and look like a missing-data bug, so the list follows what the data actually holds.
  const years = [
    ...new Set([
      filters.year,
      ...dataset.events.flatMap((e) =>
        [e.startDate, e.endDate]
          .filter(Boolean)
          .map((d) => Number(d!.slice(0, 4))),
      ),
    ]),
  ].sort();

  // Only administrative divisions are offered. The table also holds business areas and
  // subdistricts left over from an earlier reverse-geocoding model, and offering 金鸡湖街道
  // beside 吴中区 would present two different kinds of thing as if they were alternatives.
  const regionOptions = [
    { label: "全部区域", value: "" },
    ...dataset.districts
      .filter((d) => d.kind === "district" || d.kind === "county_city")
      .map((d) => ({
        label: d.name + (d.demo ? " · DEMO" : ""),
        value: d.id,
      })),
  ];

  return (
    <div className="filterbar">
      <Space wrap>
        <Select
          aria-label="年份"
          value={filters.year}
          options={years.map((y) => ({ label: `${y} 年`, value: y }))}
          onChange={(year) => update({ year })}
        />
        {regions && (
          <Select
            aria-label="地区"
            style={{ width: 180 }}
            value={filters.district}
            options={regionOptions}
            onChange={(district) => update({ district })}
          />
        )}
        <Select
          aria-label="活动类别"
          style={{ width: 185 }}
          value={filters.category}
          options={[
            { label: "全部活动类别", value: "" },
            ...Object.entries(categories).map(([value, c]) => ({
              label: c.label,
              value,
            })),
          ]}
          onChange={(category) => update({ category })}
        />
        <Switch
          aria-label="包含演示数据"
          checked={filters.includeDemo}
          onChange={(v) => update({ demo: v ? 1 : 0 })}
        />
        <span className="muted">包含 DEMO</span>
        <Switch
          aria-label="显示已结束活动"
          checked={filters.includePast}
          onChange={(v) => update({ past: v ? 1 : 0 })}
        />
        <Tooltip title="默认隐藏已结束 30 天以上的活动；证据仍在库中，可随时切回查看">
          <span className="muted">
            显示已结束{archivedCount > 0 ? `（${archivedCount}）` : ""}
          </span>
        </Tooltip>
      </Space>
      {months && (
        <div className="months">
          {Array.from({ length: 12 }, (_, i) => (
            <Button
              key={i}
              type={filters.month === i + 1 ? "primary" : "default"}
              onClick={() => update({ month: i + 1 })}
            >
              {i + 1}月
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
