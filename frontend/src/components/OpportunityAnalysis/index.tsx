import { Alert, Button, Table, Tag } from "antd";
import type { Event } from "../../types";
import { usePlatform } from "../../hooks/usePlatform";
import { districtMetrics } from "../../services/intelligence";
import { categories } from "../../utils/data";

/**
 * 地区资源比较（审核 F05）。
 *
 * 线上原来的问题：这张表叫「商圈资源比较」，但里面的行是太仓市、常熟市、姑苏区这些**行政
 * 单元**，酒店页又把太仓市放在商圈的位置上。读表格的人无法判断「按区」和「按商圈」是两种不同
 * 口径，城市汇总也可能因此重复计数。
 *
 * 数据实情（本地生产副本实测）：活动几乎全挂在行政区（区 244、市 117、县级市 69），
 * 酒店挂在商业商圈（13 家）；商圈与街道的父级此前缺失，现已由高德逆地理补齐 20 条。
 *
 * 因此这里把两类分表展示，并各自注明口径：
 *   * 行政区表：地级市 / 县级市 / 市辖区，回答「这个区有多少活动」；
 *   * 商业商圈表：回答「这个商圈有多少酒店和活动」，没有商圈的归入未归属。
 * 两张表都标出层级，避免同名不同级（如「常熟市」是县级市，「常熟」是商圈）被读成同一件事。
 */

const LEVEL_LABELS: Record<string, string> = {
  city: "地级市",
  county_city: "县级市",
  district: "市辖区",
  functional_zone: "功能区",
  subdistrict: "街道/镇",
  business_area: "商业商圈",
  unassigned: "未归属",
};

const ADMIN_KINDS = new Set(["city", "county_city", "district"]);
const COMMERCIAL_KINDS = new Set(["business_area", "subdistrict"]);

export default function OpportunityAnalysis({ events }: { events: Event[] }) {
  const { dataset, filters, update } = usePlatform();
  const allDistricts = districtMetrics(events, dataset);
  const kindOf = new Map(dataset.districts.map((d) => [d.id, d.kind ?? "unassigned"]));
  const levelOf = (id: string) => {
    const kind = kindOf.get(id) ?? "unassigned";
    return LEVEL_LABELS[kind] ?? "未归属";
  };

  // 有活动的行才有解释价值；只有酒店的行在下方说明里点名，不占表格位置。
  const admin = allDistricts.filter(
    (d) => d.events > 0 && ADMIN_KINDS.has(kindOf.get(d.id) ?? ""),
  );
  const commercial = allDistricts.filter(
    (d) => d.events > 0 && COMMERCIAL_KINDS.has(kindOf.get(d.id) ?? ""),
  );
  const unassigned = allDistricts.filter(
    (d) => d.events > 0 && !ADMIN_KINDS.has(kindOf.get(d.id) ?? "") && !COMMERCIAL_KINDS.has(kindOf.get(d.id) ?? ""),
  );
  const hotelsOnly = allDistricts.filter((d) => d.events === 0 && d.hotels > 0);

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

  const columns = [
    {
      title: "名称",
      render: (_: unknown, d: { id: string; name: string; demo?: boolean }) => (
        <>
          <Button type="link" onClick={() => update({ district: d.id })}>
            {d.name}
          </Button>
          <Tag>{levelOf(d.id)}</Tag>
          {d.demo && <Tag color="blue">DEMO</Tag>}
        </>
      ),
    },
    { title: "活动数", dataIndex: "events" },
    { title: "类别", dataIndex: "categories" },
    { title: "已配置场馆", dataIndex: "venues" },
    { title: "活动场馆集中度", dataIndex: "concentration" },
    {
      title: "酒店资源",
      render: (_: unknown, d: { hotels: number; configuredHotels: number }) =>
        `${d.hotels} 家配置 / ${d.configuredHotels} 家坐标已核验`,
    },
  ];

  return (
    <section className="panel gap-bottom">
      <div className="panel-heading">
        <h3>地区资源比较</h3>
        <Tag>
          {filters.year}年{filters.month}月 · 比较不受单地区筛选影响
        </Tag>
      </div>
      <div className="opportunity-content">
        <Alert
          type="info"
          message="行政区与商业商圈分开统计，两者不能直接相加"
          description={
            <>
              活动按行政归属挂载（区、县级市、市；实测 {events.length} 场），
              酒店按商业商圈挂载（{hotelsOnly.length + commercial.length} 个商圈）。
              地级市（苏州市）是县级市与市辖区的父级，不要把父级和子级相加。
              {hotelsOnly.length > 0 && (
                <>
                  {" "}
                  以下商圈本期没有活动、只有酒店：
                  {hotelsOnly.map((d) => `${d.name} ${d.hotels} 家`).join("、")}。
                </>
              )}
              {unassigned.length > 0 && <> 未归属地区 {unassigned.length} 行单列在下方。</>}
              {" "}摊位坐标核验情况：已核验 {coordinateSplit.verified} 场、按名称反推
              {coordinateSplit.inferred} 场（后者置信度较低）。
            </>
          }
        />

        <h3 className="gap-top">行政区（地级市 / 县级市 / 市辖区）</h3>
        {admin.length === 0 ? (
          <Alert type="warning" showIcon message="当前筛选下没有按行政归属的活动" />
        ) : (
          <Table
            rowKey="id"
            size="small"
            dataSource={admin}
            pagination={false}
            scroll={{ x: 1050 }}
            columns={columns}
          />
        )}

        <h3 className="gap-top">商业商圈 / 街道</h3>
        {commercial.length === 0 ? (
          <Alert
            type="info"
            showIcon
            message="当前筛选下没有挂在商业商圈上的活动"
            description="活动目前按行政归属采集；商圈维度主要承载酒店分布。补齐场馆商圈归属后这里会出现数据。"
          />
        ) : (
          <Table
            rowKey="id"
            size="small"
            dataSource={commercial}
            pagination={false}
            scroll={{ x: 1050 }}
            columns={columns}
          />
        )}

        {unassigned.length > 0 && (
          <>
            <h3 className="gap-top">未归属</h3>
            <Table
              rowKey="id"
              size="small"
              dataSource={unassigned}
              pagination={false}
              scroll={{ x: 1050 }}
              columns={columns}
            />
          </>
        )}

        <h3 className="gap-top">活动类别分布</h3>
        <div className="industry-grid gap-top">
          {Object.entries(categories).map(([key, value]) => (
            <Button key={key} onClick={() => update({ category: key, district: "" })}>
              {value.label}
              <strong>{events.filter((e) => e.category === key).length}</strong>
            </Button>
          ))}
        </div>
      </div>
    </section>
  );
}
