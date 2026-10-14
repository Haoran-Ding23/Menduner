import { Alert, Button, Table, Tag } from "antd";
import type { Event } from "../../types";
import { usePlatform } from "../../hooks/usePlatform";
import { districtMetrics } from "../../services/intelligence";
import { categories } from "../../utils/data";
export default function OpportunityAnalysis({ events }: { events: Event[] }) {
  const { dataset, filters, update } = usePlatform();
  const allDistricts = districtMetrics(events, dataset);
  // A district that only holds hotels cannot answer a demand question for these events, and
  // listing it would pad the table with rows that are always zero — but the omission is
  // reported below, so it is visible rather than silent.
  const comparison = allDistricts.filter((d) => d.events > 0);
  const hotelsOnly = allDistricts.filter((d) => d.events === 0 && d.hotels > 0);
  // How the district was derived matters: a verified venue coordinate is checked geography,
  // while a name-matched venue is an inference and should be labelled as the weaker signal.
  const coordinateSplit = (() => {
    const venues = new Map(dataset.venues.map((v) => [v.id, v]));
    let verified = 0;
    let inferred = 0;
    for (const event of events) {
      const venue = venues.get(event.venueId ?? "");
      if (!venue) continue;
      if (venue.coordinates?.lng && venue.coordinates?.lat) verified += 1;
      else inferred += 1;
    }
    return { verified, inferred };
  })();
  return (
    <section className="panel gap-bottom">
      <div className="panel-heading">
        <h3>商圈资源比较</h3>
        <Tag>
          {filters.year}年{filters.month}月 · 比较不受单商圈筛选影响
        </Tag>
      </div>
      <div className="opportunity-content">
        <Alert
          type="info"
          message="仅统计当前配置样本。商圈取自高德逆地理编码：优先用其返回的商圈（如湖东、南门），无商圈时退到所在街道（如松陵街道、周庄镇）。场馆集中度按活动归属统计，酒店资源不代表完整市场分布。"
          description={
            <>
              「未归入商圈」是场馆名无法匹配到高德地点、尚未定位的活动。当前有
              坐标核验的场馆 {coordinateSplit.verified} 条活动、场馆无坐标而按名称反推商圈的
              {coordinateSplit.inferred} 条——后者置信度较低，补上场馆坐标后会更可靠。
              {hotelsOnly.length > 0 && (
                <>
                  {" "}
                  另有 {hotelsOnly.length} 个商圈在当前筛选下没有活动、只有酒店（
                  {hotelsOnly
                    .map((d) => `${d.name} ${d.hotels} 家`)
                    .join("、")}
                  ），未列入下表。
                </>
              )}
            </>
          }
        />
        <Table
          rowKey="id"
          className="gap-top"
          dataSource={comparison}
          pagination={false}
          scroll={{ x: 1050 }}
          columns={[
            {
              title: "商圈",
              render: (_, d) => (
                <>
                  <Button
                    type="link"
                    onClick={() => update({ district: d.id })}
                  >
                    {d.name}
                  </Button>
                  {d.id === "district-unassigned" ? (
                    <Tag color="default">场馆待定位</Tag>
                  ) : (
                    d.demo && <Tag color="blue">DEMO</Tag>
                  )}
                </>
              ),
            },
            { title: "活动量", dataIndex: "events" },
            { title: "类别", dataIndex: "categories" },
            { title: "已配置场馆", dataIndex: "venues" },
            {
              title: "活动场馆集中度",
              dataIndex: "concentration",
            },
            {
              title: "酒店资源",
              render: (_, d) =>
                `${d.hotels} 家配置 / ${d.configuredHotels} 家坐标已核验`,
            },
          ]}
        />
        <h3 className="gap-top">活动类别分布</h3>
        <div className="industry-grid gap-top">
          {Object.entries(categories).map(([key, value]) => (
            <Button
              key={key}
              onClick={() => update({ category: key, district: "" })}
            >
              {value.label}
              <strong>{events.filter((e) => e.category === key).length}</strong>
            </Button>
          ))}
        </div>
      </div>
    </section>
  );
}
