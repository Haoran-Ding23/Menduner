import { Alert, Button, Table, Tag } from "antd";
import type { Event } from "../../types";
import { usePlatform } from "../../hooks/usePlatform";
import { districtMetrics } from "../../services/intelligence";
import { categories } from "../../utils/data";
export default function OpportunityAnalysis({ events }: { events: Event[] }) {
  const { dataset, filters, update } = usePlatform();
  const comparison = districtMetrics(events, dataset);
  return (
    <section className="panel gap-bottom">
      <div className="panel-heading">
        <h3>District Comparison · 商圈资源比较</h3>
        <Tag>
          {filters.year}年{filters.month}月 · 比较不受单商圈筛选影响
        </Tag>
      </div>
      <div className="opportunity-content">
        <Alert
          type="info"
          message="仅统计当前配置样本；DEMO 商圈归属为演示分组。场馆集中度按活动归属统计，酒店资源不代表完整市场分布。"
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
                  {d.demo && <Tag color="blue">DEMO</Tag>}
                </>
              ),
            },
            { title: "Event volume · 活动量", dataIndex: "events" },
            { title: "Event categories · 类别", dataIndex: "categories" },
            { title: "已配置场馆", dataIndex: "venues" },
            {
              title: "Venue concentration · 活动场馆集中度",
              dataIndex: "concentration",
            },
            {
              title: "Hotel resources · 酒店资源",
              render: (_, d) =>
                `${d.hotels} 家配置 / ${d.configuredHotels} 家坐标已核验`,
            },
          ]}
        />
        <h3 className="gap-top">Event Categories · 活动类别分布</h3>
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
