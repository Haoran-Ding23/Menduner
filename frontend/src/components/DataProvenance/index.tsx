import { Tooltip } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import { beijingToday } from "../../utils/caliber";
import { provenanceOf } from "../../utils/provenance";

/**
 * 页脚的数据来源条（F12）：更新时间、批次、口径版本。
 *
 * 三个字段都来自后端数据集，不在前端编造；缺失就显示「未知」。数据过期时给出明确提示，
 * 因为一个三天前的数字看起来和刚抓的数字一模一样，这是最容易误导人的地方。
 */
export default function DataProvenance() {
  const { dataset } = usePlatform();
  const provenance = provenanceOf({ updatedAt: dataset.updatedAt, today: beijingToday() });

  return (
    <footer className="data-provenance" aria-label="数据来源与版本">
      <span>
        数据更新：
        <Tooltip title="按北京时间展示；来自后端数据集更新时间">
          <strong>{provenance.updatedLabel}</strong>
        </Tooltip>
      </span>
      <span>批次：{provenance.batchId}</span>
      <span>口径版本：{provenance.caliberVersion}</span>
      {provenance.note && <span className="data-provenance-warn">{provenance.note}</span>}
    </footer>
  );
}
