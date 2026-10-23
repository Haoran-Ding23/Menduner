"""用苏州市文旅局的星级饭店名录校验并补全酒店星级。

## 为什么值得做

现在的星级取自高德的分类串（「五星级宾馆」）。那是地图服务对 POI 的分类，不是评定机构的名录。
苏州市旅游咨询中心发布的《苏州星级酒店名录》是**官方名录**（表格：序号/饭店名称/地址/星级），
把它接进来有两个作用：

  * 对得上的酒店，星级从「地图分类」升级为「官方名录」，来源更硬；
  * 两个来源不一致时能发现——现在 12 家里没有一条不一致，这本身就是交叉验证。

**未出现在名录里的酒店（例如苏州洲际酒店），不补星级。** 洲际是高端品牌，但名录里没有它，
就说明在这个城市的官方星级序列里没有它的位置（可能未参评）。按品牌补写才是编造。

## 用法

    python -X utf8 scripts/import_official_stars.py            # 只报告
    python -X utf8 scripts/import_official_stars.py --apply    # 写入 payload.officialStar
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect, database_path

SOURCE_URL = "https://visitsz.wglj.suzhou.com.cn/news-detail.aspx?id=1662"
SOURCE_NAME = "苏州市旅游咨询中心《苏州星级酒店名录》"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Menduner/0.1; academic project)",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def fetch_rows() -> tuple[list[dict], str]:
    """Read the published table: 序号 / 饭店名称 / 地址 / 星级."""
    with httpx.Client(timeout=30, follow_redirects=True, headers=HEADERS) as client:
        response = client.get(SOURCE_URL)
    response.raise_for_status()
    html = response.text
    table = re.search(r"<table.*?</table>", html, re.S)
    if not table:
        raise RuntimeError("名录页面结构变化：找不到表格")
    rows: list[dict] = []
    for row in re.findall(r"<tr.*?</tr>", table.group(0), re.S):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < 4 or not cells[3].isdigit():
            continue
        rows.append({"name": cells[1], "address": cells[2], "star": int(cells[3])})
    published = re.search(r"20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}", html)
    return rows, (published.group(0) if published else "")


CITY_PREFIXES = ("苏州市", "苏州", "太仓市", "太仓", "昆山市", "昆山", "常熟市",
                 "常熟", "张家港市", "张家港", "吴中区", "吴中", "姑苏区", "姑苏",
                 "相城区", "相城", "吴江区", "吴江", "虎丘区", "虎丘")
# 我们的酒店名来自地图 POI，常带楼栋/入口/门店后缀（「1号楼」「大堂」「石路广济南路地铁站店」），
# 官方名录用的是饭店注册名。不处理这些，正确的酒店会被判成「名录未收录」。
SUFFIX = re.compile(r"(\d+号楼|\d+区|大堂|分店|店|酒店|宾馆|饭店)$")


def normalise(value: str) -> str:
    text = re.sub(r"[\s（）()·\-—]", "", value or "")
    text = re.sub(r"\(.*?\)", "", text)
    for prefix in CITY_PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix) + 3:
            text = text[len(prefix):]
            break
    return text


def core(value: str) -> str:
    """Name without the branch suffix, for the containment pass."""
    return SUFFIX.sub("", normalise(value))


def match(hotel_name: str, rows: list[dict]) -> dict | None:
    """Normalised equality first, then containment on the branch-stripped core name."""
    target = normalise(hotel_name)
    for row in rows:
        if normalise(row["name"]) == target:
            return row
    target_core = core(hotel_name)
    for row in rows:
        official = normalise(row["name"])
        official_core = core(row["name"])
        if len(official_core) >= 4 and (official in target or target_core == official_core
                                        or target_core in official_core
                                        or official_core in target_core):
            return row
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows, published = fetch_rows()
    print(f"  名录行数: {len(rows)}  发布/更新日期: {published or '未标注'}")

    db = database_path()
    matched = 0
    agree = 0
    disagree: list[str] = []
    unmatched: list[str] = []
    stamp = datetime.now(timezone.utc).isoformat()

    with connect(db) as con:
        hotels = list(con.execute("SELECT id, payload FROM hotels"))
        for row in hotels:
            payload = json.loads(row["payload"])
            name = payload.get("name") or ""
            official = match(name, rows)
            if official is None:
                unmatched.append(name)
                continue
            matched += 1
            current = (payload.get("star") or {}).get("level")
            if current == official["star"]:
                agree += 1
            else:
                disagree.append(f"{name}: 地图分类 {current} vs 官方 {official['star']}")

            if args.apply:
                payload["officialStar"] = {
                    "level": official["star"],
                    "label": f"{official['star']}星级",
                    "name": official["name"],
                    "address": official["address"],
                    "source": SOURCE_NAME,
                    "sourceUrl": SOURCE_URL,
                    "publishedAt": published,
                    "importedAt": stamp,
                }
                con.execute(
                    "UPDATE hotels SET payload=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), row["id"]),
                )

    print(f"  名录匹配上: {matched}/{len(hotels)}")
    print(f"  与地图分类一致: {agree}")
    print(f"  不一致: {len(disagree)}")
    for line in disagree:
        print(f"    ! {line}")
    print(f"  名录未收录（不补星级）: {len(unmatched)}")
    for name in unmatched:
        print(f"    · {name}")
    print(f"  模式: {'写入' if args.apply else '只报告（加 --apply 写入）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
