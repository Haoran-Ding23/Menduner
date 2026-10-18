import { useEffect, useState, useRef } from "react";
import { useLocation } from "react-router-dom";
import { Button, Tag, Modal, Alert, Space, message, Descriptions } from "antd";
import {
  EnvironmentOutlined,
  CalendarOutlined,
  ApartmentOutlined,
  HomeOutlined,
  BarChartOutlined,
  SafetyCertificateOutlined,
  CrownOutlined,
  LockOutlined,
  ToolOutlined,
  SettingOutlined,
  UploadOutlined,
  ReloadOutlined,
  UnorderedListOutlined,
  ShopOutlined,
} from "@ant-design/icons";
import { usePlatform } from "../../hooks/usePlatform";
import { canReview, useIdentity } from "../../hooks/useIdentity";
import { useAccount, useEntitlements } from "../../hooks/useEntitlements";
import { PLAN_LABELS, type PlanId } from "../../services/plans";
import { FILING_MODE, SITE_SHORT, SITE_TAGLINE, SITE_TITLE } from "../../config";
export interface NavPage {
  path: string;
  title: string;
  label: string;
  icon: React.ReactNode;
  /** Paid workflow: the item stays visible but shows a lock until the plan reaches this tier. */
  minPlan?: PlanId;
}
export const pages: NavPage[] = [
  {
    path: "/map",
    title: "城市活动地图",
    label: "城市活动地图",
    icon: <EnvironmentOutlined />,
  },
  {
    path: "/calendar",
    title: "活动日历",
    label: "活动日历",
    icon: <CalendarOutlined />,
  },
  {
    path: "/agenda",
    title: "活动清单",
    label: "活动清单",
    icon: <UnorderedListOutlined />,
  },
  {
    path: "/venues",
    title: "场馆活动清单",
    label: "场馆活动清单",
    icon: <ShopOutlined />,
  },
  {
    path: "/graph",
    title: "知识图谱",
    label: "知识图谱",
    icon: <ApartmentOutlined />,
  },
  {
    path: "/hotels",
    title: "酒店活动情报",
    label: "酒店活动情报",
    icon: <HomeOutlined />,
    minPlan: "pro",
  },
  {
    path: "/insights",
    title: "商圈洞察",
    label: "商圈洞察",
    icon: <BarChartOutlined />,
    minPlan: "pro",
  },
  {
    path: "/evidence",
    title: "数据质量与来源",
    label: "数据质量与来源",
    icon: <SafetyCertificateOutlined />,
  },
];

// The customer's upgrade entry. Visible to everyone: a customer must be able to see what a paid
// plan would unlock before deciding anything.
export const plansPage: NavPage = {
  path: "/plans",
  title: "套餐与升级",
  label: "套餐与升级",
  icon: <CrownOutlined />,
};

// Internal operations. Not a public page: shown only to a reviewer/admin, and its endpoints
// are server-side role-checked regardless of what the navigation renders.
export const consolePage: NavPage = {
  path: "/review",
  title: "审核台",
  label: "审核台",
  icon: <ToolOutlined />,
};
export default function PlatformLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const location = useLocation();
  const { dataset, filters, go, importData, resetData, dataMode, reloadData } =
    usePlatform();
  const { identity } = useIdentity();
  const { plan, canUse, label } = useEntitlements();
  const { state: accountState } = useAccount();
  // Filing review must see a non-commercial information site: the paid workflow, the plan page and
  // the account entry disappear (their routes also redirect, see App.tsx). Nothing is deleted.
  const visiblePages = FILING_MODE ? pages.filter((item) => !item.minPlan) : pages;
  // Paid workflow stays visible but locked: a customer must be able to see what exists and what
  // an upgrade would unlock. The lock is product communication, not enforcement.
  const navPages: NavPage[] = [
    ...visiblePages,
    ...(FILING_MODE ? [] : [plansPage]),
    ...(canReview(identity) ? [consolePage] : []),
  ];
  const page = navPages.find((p) => p.path === location.pathname);
  const [settings, setSettings] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const [api, holder] = message.useMessage();
  useEffect(() => {
    document.title = SITE_TITLE;
  }, []);
  return (
    <div className="platform">
      {holder}
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-symbol">M</span>
          <div>
            Menduner<small>{SITE_TAGLINE}</small>
          </div>
        </div>
        <div className="nav-section">工作空间</div>
        <nav>
          {navPages.map((p) => {
            const locked = p.minPlan ? !canUse(p.minPlan) : false;
            return (
              <button
                key={p.path}
                className={
                  "nav-item " + (p.path === location.pathname ? "active" : "")
                }
                onClick={() => go(p.path)}
                title={locked ? `需要${PLAN_LABELS[p.minPlan as PlanId]}` : undefined}
              >
                {p.icon}
                <span>{p.label}</span>
                {locked && <LockOutlined className="nav-lock" />}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          <Tag color="cyan">ENT303TC · 第 14 组</Tag>
          <p>苏州 · 城市活动知识图谱</p>
          <small>V1.3 / 采集管线原型</small>
          <div className="gap-top">
            {FILING_MODE ? (
              <Tag>公开活动信息展示</Tag>
            ) : accountState.authenticated ? (
              <Tag color={plan === "free" ? "default" : "gold"}>
                {accountState.account?.login} · {label}
              </Tag>
            ) : (
              <Button size="small" onClick={() => go("/login")}>
                登录 / 注册
              </Button>
            )}
          </div>
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
            <Tag color="blue">
             {SITE_SHORT} · {dataset.events.length} 条
            </Tag>
            {/* The status strip was removed from the page body, but a refresh control must
                stay reachable, and a connection failure has to be visible because it
                changes what the numbers mean. */}
            {dataMode !== "api" && dataMode !== "demo" && (
              <Tag color={dataMode === "error" ? "red" : "orange"}>
                {
                  {
                    loading: "读取中",
                    error: "API 不可用",
                    stale: "API 已断开 · 上次快照",
                    import: "手动导入 · 当前会话",
                    demo: "",
                    api: "",
                  }[dataMode]
                }
              </Tag>
            )}
            <Button
              aria-label="刷新 API 数据"
              title="刷新 API 数据"
              icon={<ReloadOutlined />}
              loading={dataMode === "loading"}
              onClick={() => void reloadData()}
            />
            <Button
              aria-label="设置与数据导入"
              icon={<SettingOutlined />}
              onClick={() => setSettings(true)}
            />
          </Space>
        </header>
        <main>
          {children}
        </main>
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
          message="六页共享同一份数据快照"
          description="导入完整数据集或活动数组。只有具有来源 URL 的已核验 GCJ-02 坐标会显示在地图上。手动导入仅保留于当前会话，不写入数据库；刷新页面重新读取 API。"
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
              children: import.meta.env.VITE_AMAP_KEY
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
              api.success("已切换到本地 DEMO；未修改数据库");
            }}
          >
            使用本地 DEMO
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
