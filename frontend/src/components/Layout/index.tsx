import { useState, useRef } from "react";
import { useLocation } from "react-router-dom";
import { Button, Tag, Modal, Alert, Space, message, Descriptions } from "antd";
import {
  EnvironmentOutlined,
  CalendarOutlined,
  ApartmentOutlined,
  HomeOutlined,
  BarChartOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { usePlatform } from "../../hooks/usePlatform";
export const pages = [
  {
    path: "/map",
    title: "City Event Map",
    label: "城市活动地图",
    icon: <EnvironmentOutlined />,
  },
  {
    path: "/calendar",
    title: "Event Calendar",
    label: "活动日历",
    icon: <CalendarOutlined />,
  },
  {
    path: "/graph",
    title: "Knowledge Graph Explorer",
    label: "知识图谱",
    icon: <ApartmentOutlined />,
  },
  {
    path: "/hotels",
    title: "Hotel Event Intelligence",
    label: "酒店活动情报",
    icon: <HomeOutlined />,
  },
  {
    path: "/insights",
    title: "District Insights",
    label: "商圈洞察",
    icon: <BarChartOutlined />,
  },
  {
    path: "/evidence",
    title: "Evidence & Data Quality",
    label: "证据与数据质量",
    icon: <SafetyCertificateOutlined />,
  },
];
export default function PlatformLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const location = useLocation();
  const { dataset, filters, go, importData, resetData } = usePlatform();
  const page = pages.find((p) => p.path === location.pathname);
  const [settings, setSettings] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const [api, holder] = message.useMessage();
  return (
    <div className="platform">
      {holder}
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-symbol">M</span>
          <div>
            Menduner<small>CITY EVENT INTELLIGENCE</small>
          </div>
        </div>
        <div className="nav-section">工作空间 / WORKSPACE</div>
        <nav>
          {pages.map((p) => (
            <button
              key={p.path}
              className={
                "nav-item " + (p.path === location.pathname ? "active" : "")
              }
              onClick={() => go(p.path)}
            >
              {p.icon}
              <span>
                {p.label}
                <small>{p.title}</small>
              </span>
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <Tag color="cyan">ENT303TC · Group 14</Tag>
          <p>苏州 · 城市活动知识图谱</p>
          <small>Frontend V1.2 / 本地演示</small>
        </div>
      </aside>
      <div className="workspace">
        <header>
          <div>
            <span className="breadcrumb">工作空间 / </span>
            <strong>{page?.title}</strong>
          </div>
          <Space>
            <span className="header-year">{filters.year}</span>
            <Tag color="blue">本地 JSON · {dataset.events.length} 条</Tag>
            <Button
              aria-label="设置与数据导入"
              icon={<SettingOutlined />}
              onClick={() => setSettings(true)}
            />
          </Space>
        </header>
        <main>{children}</main>
      </div>
      <Modal
        title="设置与数据导入"
        open={settings}
        onCancel={() => setSettings(false)}
        footer={null}
      >
        <Alert
          type="info"
          showIcon
          message="六页共享同一套本地数据"
          description="导入完整 Dataset 或活动数组。只有具有来源 URL 的已核验 GCJ-02 坐标会显示在地图上。数据仅保留于当前会话，刷新恢复样例。"
        />
        <Descriptions
          className="gap-top"
          column={1}
          items={[
            {
              key: "count",
              label: "活动记录",
              children: dataset.events.length,
            },
            { key: "date", label: "更新时间", children: dataset.updatedAt },
            {
              key: "map",
              label: "地图配置",
              children:
                import.meta.env.VITE_AMAP_KEY &&
                import.meta.env.VITE_AMAP_SERVICE_HOST
                  ? "已提供配置；连接结果见地图"
                  : "尚未配置",
            },
          ]}
        />
        <Space className="gap-top">
          <Button
            icon={<UploadOutlined />}
            onClick={() => input.current?.click()}
          >
            导入 JSON
          </Button>
          <Button
            onClick={() => {
              resetData();
              api.success("已恢复 DEMO 样例");
            }}
          >
            恢复演示数据
          </Button>
        </Space>
        <input
          ref={input}
          type="file"
          accept=".json,application/json"
          hidden
          onChange={async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            try {
              if (file.size > 10 * 1024 * 1024)
                throw new Error("文件超过 10 MB");
              importData(JSON.parse(await file.text()));
              api.success("导入成功");
              setSettings(false);
            } catch (error) {
              api.error(error instanceof Error ? error.message : "导入失败");
            } finally {
              e.target.value = "";
            }
          }}
        />
        <p className="muted">
          地图安全密钥由服务器读取。修改 .env.local 后需重启 npm run dev。
        </p>
      </Modal>
    </div>
  );
}
