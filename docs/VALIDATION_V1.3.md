# V1.3 验证记录

在 V1.2 `4006606` 上增量开发，分支 `feature/frontend-v1.3`。

| 检查 | 结果 |
|---|---|
| 后端 pytest | 8项通过；见 backend-test-results.txt |
| 前端 npm test | 48项 / 6文件通过；见 ../frontend/test-results.txt |
| npm run build | TypeScript及Vite构建通过；见 ../frontend/build-results.txt |
| 实际 HTTP 冒烟 | CLI → 临时SQLite → FastAPI → Vite /api；全部接口及六个路由shell通过；见 pipeline-smoke-results.txt |

后端覆盖：空库、404、字段契约、持久化、幂等、单来源更新/撤回、跨源保留、适配器失败、外键失败事务回滚、非法日期拒绝、模拟数据不能升级已核验。

前端保留原42项检查，新增6项覆盖API归一化、失败/无效响应、空库时间、刷新更新/过期快照、首次失败不自动替代样例及显式导入与在途请求竞争。

浏览器页面测试使用jsdom；地图SDK和ECharts为mock。HTTP冒烟仅验证路由HTML壳和真实代理/API数据，不等于浏览器渲染、AMap联网鉴权或视觉验收。没有新截图。既有大分包提示仍存在；Python TestClient使用httpx有上游弃用提示，测试通过。

未添加生产部署、认证系统、云资源或Neo4j。真实外部来源采集、API容量、并发负载和生产运维不在原型验证范围。旧V1.1/V1.2日志和说明只作历史记录。
