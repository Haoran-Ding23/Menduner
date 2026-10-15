# 实际到场人数记录表（2026-10-15 设计）

表名 `attendance_records`，模块 `crawler/attendance.py`。

**这张表的目的不是展示，是攒训练数据。** 这个区别决定了下面四个设计决定 ——
如果按"给页面显示一个数字"来做，四个都会做错。

---

## 一、四个关键决定

### 决定 ① 一场活动允许多条记录，不合并成一个数字

同一场活动会有多个人数，而**它们的分歧本身是信息**：

```
活动 X   官方通报   5000 人    票务系统口径
活动 X   新闻报道   3000 人    记者目测
活动 X   酒店访谈    800 间夜   酒店自己的口径
```

**如果只存一个数字，就必须选一个 —— 等于把判断强行塞进数据里，而后来的人看不到这个选择。**

存多条，让模型看到方差。**分歧不是需要清理的噪音，是需要学习的信号。**

### 决定 ② `event_id` 可以为空

**这是最容易被忽略、但最关键的一条。**

如果强制关联到 `events` 表，就**只能记录我们抓到的那 345 场** —— 而**训练数据需要的是历史活动，我们库里只有未来活动。**

结果会是：训练集**天然偏向"我们抓到的活动"**，而那恰恰是有偏的样本。

所以记录可以只靠**活动名 + 日期**标识，**有匹配的活动时才挂上 id**。

**这意味着今天就能开始记 2019 年的数据。**

### 决定 ③ 必须记录数字的"口径"（`measure`）

同一个「5000」可以是：

| 口径 | 含义 |
|---|---|
| `single_day` | 某一天到场 |
| `full_run` | 整个展期累计 |
| `peak_day` | 最忙的一天 |
| `tickets_sold` | 卖出票数（**不等于来了人**） |
| `rooms_booked` | 酒店间夜（探访者提到的口径） |

**口径不同的数字不能放在一个训练集里。** 所以这是**必填字段**，不接受推断。

### 决定 ④ 区分"实测"与"估计"

`method` 字段，从强到弱：

| method | 含义 |
|---|---|
| `official` | 主办方/场馆/政府发布 |
| `ticketing` | 票务平台发布（通常是售票数） |
| `news` | 新闻报道（常引述官方） |
| `field_observation` | 有人在现场数 |
| `capacity_estimate` | **按场馆容量推算的** |
| `inference` | **由其他信号推的** |

**后两种不是"测到的"，是"估的"。** 表里保留它们（可以用），但**标记出来**（可以排除）。

**并且强制：`capacity_estimate` / `inference` 不允许标 `high` 置信度** —— 估算不能被记成实测。

---

## 二、字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | `att:<sha256前32位>`，由 活动名+日期+人数+方法+来源URL 算得 |
| `event_id` | TEXT NULL | 关联到我们库里的活动；**可为空**（历史数据） |
| `subject_name` | TEXT NOT NULL | 活动名（**不依赖 event_id**） |
| `observed_on` | TEXT NOT NULL | 观测日期 `YYYY-MM-DD` |
| `measure` | TEXT NOT NULL | 口径，见上 |
| `count` | INTEGER NOT NULL | 人数/票数/间夜 |
| `method` | TEXT NOT NULL | 获取方式，见上 |
| `confidence` | TEXT NOT NULL | `high` / `medium` / `low` |
| `source_type` | TEXT NOT NULL | `official_site` / `ticketing_platform` / `news_media` / `social_media` / `venue_staff` / `person_on_site` / `internal_estimate` |
| `source_name` | TEXT | 来源名称（如"某酒店店长"） |
| `source_url` | TEXT | 来源链接；**可空，但要配合 source_name** |
| `source_text` | TEXT | 原文片段 —— 保留原话，便于核验 |
| `venue_capacity` | INTEGER | 当时的场馆容量，用于算上座率 |
| `collected_by` | TEXT NOT NULL | 谁收集的 |
| `collected_at` | TEXT NOT NULL | 什么时候收集的（**不是活动日期**） |
| `note` | TEXT | 备注 |

### 为什么 `collected_at` 和 `observed_on` 是两件事

**一个 2019 年的活动，今天才被记录。** 两者不同，而且都要有 ——
`observed_on` 进训练特征，`collected_at` 用来说明数据是什么时候攒的。

### 为什么保留 `source_text` 原文

**数字可以是对的，而理解是错的。** 保留原话，后来的人能判断口径有没有被误读。

---

## 三、这张表拒绝什么

**一张训练数据表的价值在于它拒绝什么。** 坏行会变成坏训练样本，而且下游无法分辨。

| 拒绝的情况 | 原因 |
|---|---|
| 没有来源 URL **且**没有具名来源 | 数字无法追溯 |
| 没有 `collected_by` | 不知道谁收集的 |
| `measure` 缺失或非法 | 口径不明，不能进数据集 |
| `method` 缺失或非法 | 分不清实测和估计 |
| `capacity_estimate` / `inference` 标 `high` | **估算不能被记成实测** |
| 人数为负数 / 小数 / 布尔值 | 不是有效计数 |
| 日期不是 `YYYY-MM-DD` | 训练需要真实日期 |
| `event_id` 指向不存在的活动 | 静默失联比报错更糟 |
| 同一测量重复写入 | 重复样本会放大权重 |
| `venue_capacity` 为 0 或非整数 | 上座率会算出无意义的值 |

**合法的例外：** 一个来自酒店店长、没有网页的数字 —— **可以记，但必须写清 `source_name`。**

---

## 四、导出训练行的样子

`export_training_rows(con)` 把记录连上活动与场馆：

```
id · event_id · subject_name · observed_on · measure · count
method · confidence · source_type · source_name · source_url
venue_capacity · collected_by · collected_at · note
event_name · event_category · event_start · event_end
venue_id · venue_name
utilisation        ← count / venue_capacity，只在两者都有时计算
```

**`measured_only=True` 会剔除 `capacity_estimate` 和 `inference`。**

**默认保留全部** —— 因为"模型能学什么"是模型的判断，不是这张表的。但这个开关存在，
所以那个选择是**明确做的，不是默认发生的**。

---

## 五、表里刻意没有的东西

**没有 `price`、没有 `revenue`、没有 `prediction`、没有 `recommended`。**

**这张表只存观测。** 从它算出来的任何东西都在别处算，**不写回这里** ——
这样推导值永远不会被误认为观测值。

**有一条测试专门守着这件事：** 字段名里出现 `price` / `revenue` / `prediction` / `forecast` / `recommended` 就失败。

---

## 六、数据集现在是什么状态

**空的。** `summary()` 如实报告：

```json
{
  "total": 0,
  "linked_to_event": 0,
  "unlinked": 0,
  "with_source_url": 0,
  "estimated": 0,
  "first_observed_on": null,
  "last_observed_on": null,
  "by_method": {},
  "by_measure": {},
  "status": "empty"
}
```

**`status` 是 `"empty"` 而不是报 0 覆盖率** —— 空数据集是诚实的起始状态，
读者不该从一堆 0 里去猜。

收集开始日期由 `dataset_start()` 记录为 **2026-10-15**，这样以后能说清数据攒了多久。

---

## 七、现在能做什么

**已经可用：**

```python
from crawler import attendance
from backend.database import connect

with connect(db) as con:
    attendance.record(
        con,
        subject_name="2026 苏州某音乐节",
        observed_on="2026-10-05",
        count=12000,
        measure="full_run",
        method="news",
        source_type="news_media",
        collected_by="组员B",
        source_url="https://...",
        source_text="据主办方介绍，两天共吸引观众约1.2万人次",
    )
```

**还没做（等你定）：**

| 项 | 说明 |
|---|---|
| **API 接口** | `POST /attendance`、`GET /attendance`、`GET /attendance/summary` |
| **录入页面** | 组员怎么方便地录 —— 现在只能用 Python |
| **导出脚本** | 把训练行导成 CSV/JSON 给建模用 |
| **录入规范文档** | 什么算 `single_day`、什么算 `full_run` 的判定指南 |

**录入界面是最影响数据量的** —— 如果组员要写 Python 才能录，数据就攒不起来。

---

## 八、测试

**519 个后端测试通过**，其中 `crawler/tests/test_attendance.py` 新增 **24 个**，
大部分测的是**拒绝**：

| 测试 | 覆盖 |
|---|---|
| `test_many_measurements_of_one_event_are_all_kept` | 决定 ① |
| `test_a_measurement_can_be_recorded_for_an_event_we_never_crawled` | **决定 ②** |
| `test_the_measure_is_required_because_scopes_are_not_comparable` | 决定 ③ |
| `test_the_method_is_required_so_an_estimate_is_never_read_as_a_measurement` | 决定 ④ |
| `test_an_estimate_may_not_be_recorded_as_high_confidence` | 估算不能冒充实测 |
| `test_a_number_with_no_source_and_no_named_source_is_refused` | 可追溯性 |
| `test_a_named_source_is_enough_when_there_is_no_page` | 合法例外 |
| `test_the_same_measurement_twice_is_refused_but_a_different_one_is_not` | 重复样本 |
| `test_summary_reports_an_empty_dataset_as_empty_not_as_zero_coverage` | 不夸大覆盖 |
| `test_summary_separates_estimates_from_measurements` | 可分离 |
| `test_export_computes_utilisation_only_when_both_halves_exist` | 上座率 |
| `test_export_keeps_estimates_by_default_and_drops_them_on_request` | 明确而非默认 |
| `test_the_table_has_no_column_that_could_hold_a_price_or_a_prediction` | 边界 |
