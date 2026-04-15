"""市場分析報表產生器 — 完整交叉分析所有欄位，產生自包含 HTML 報表。

用法：
    python -m house_search_mcp.report
    python -m house_search_mcp.report --db data/20260331.db --cities Taipei
"""

import argparse
import json
import locale
import math
import re
import sqlite3
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path

# 設定中文排序 locale（筆畫/注音序）
try:
    locale.setlocale(locale.LC_COLLATE, "zh_TW.UTF-8")
except locale.Error:
    pass

from .api import TAG_NAMES, TYPE_NAMES
from .crawler import CITY_LABEL

# ── 常數 ──────────────────────────────────────────────────────────────

ACTIVE = "(is_off IS NULL OR is_off = 0)"

# 住宅 vs 商用分類（用於 SQL LIKE 匹配 type JSON）
RESIDENTIAL_TYPES = ("大樓", "公寓", "華廈", "別墅", "套房", "電梯大樓")
COMMERCIAL_TYPES = ("店面", "辦公", "廠房", "倉庫", "土地", "車位")

def _is_residential_where():
    """住宅 WHERE 條件（匹配 type JSON 欄位）。"""
    conds = " OR ".join(f'type LIKE \'%"{t}"%\'' for t in RESIDENTIAL_TYPES)
    return f"({conds})"

def _is_commercial_where():
    """商用 WHERE 條件。"""
    conds = " OR ".join(f'type LIKE \'%"{t}"%\'' for t in COMMERCIAL_TYPES)
    return f"({conds})"

PRICE_BUCKETS = [
    (500, "< 500萬"), (1000, "500–1000萬"), (2000, "1000–2000萬"),
    (3000, "2000–3000萬"), (5000, "3000–5000萬"),
    (10000, "5000萬–1億"), (float("inf"), "1億以上"),
]

COLORS = [
    "#c0392b", "#2563eb", "#0d9488", "#d97706", "#7c3aed",
    "#db2777", "#059669", "#ea580c", "#4f46e5", "#0891b2",
    "#be123c", "#65a30d", "#9333ea", "#ca8a04", "#dc2626",
]


# ══════════════════════════════════════════════════════════════════════
#  資料層
# ══════════════════════════════════════════════════════════════════════

class RD:
    """Report Data — 封裝所有查詢。"""

    def __init__(self, db_path, cities=None):
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        self.cities = cities
        self._zip_map = {}
        self._build_zip_map()
        # 檢測是否有 detail 資料
        try:
            r = self.conn.execute("SELECT COUNT(*) FROM houses WHERE has_detail=1").fetchone()
            self.has_detail = r[0] > 0
        except Exception:
            self.has_detail = False

    def _build_zip_map(self):
        rows = self.conn.execute(
            "SELECT zip_code, address FROM houses WHERE address IS NOT NULL GROUP BY zip_code"
        ).fetchall()
        for r in rows:
            m = re.search(r"(?:市|縣)(.+?[區鄉鎮市])", r["address"] or "")
            self._zip_map[r["zip_code"]] = m.group(1) if m else r["zip_code"]
        # 也用 detail 的 district 欄位補充
        try:
            rows2 = self.conn.execute(
                "SELECT zip_code, district FROM houses WHERE district IS NOT NULL GROUP BY zip_code"
            ).fetchall()
            for r in rows2:
                if r["district"]:
                    self._zip_map[r["zip_code"]] = r["district"]
        except Exception:
            pass

    def dn(self, zc): return self._zip_map.get(zc, zc)

    def _cw(self, pfx="AND"):
        if not self.cities: return ""
        return f"{pfx} city IN ({','.join(['?']*len(self.cities))})"

    def _cp(self): return list(self.cities) if self.cities else []

    def city_list(self):
        sql = f"SELECT city, COUNT(*) AS cnt FROM houses WHERE {ACTIVE} {self._cw()} GROUP BY city ORDER BY cnt DESC"
        return [r["city"] for r in self.conn.execute(sql, self._cp())]

    def kpis(self):
        sql = f"""SELECT COUNT(*) AS total,
            ROUND(AVG(unit_price),1) AS avg_up,
            ROUND(AVG(price),0) AS avg_price,
            ROUND(AVG(monthly_fee),0) AS avg_fee,
            MAX(watchers) AS max_w
            FROM houses WHERE {ACTIVE} {self._cw()}"""
        r = self.conn.execute(sql, self._cp()).fetchone()
        stats = {s["city"]: dict(s) for s in self.conn.execute("SELECT * FROM crawl_stats")}
        cf = self.cities or list(stats.keys())
        return {
            "total": r["total"], "avg_up": r["avg_up"], "avg_price": r["avg_price"],
            "avg_fee": r["avg_fee"], "max_w": r["max_w"],
            "newin": sum(stats.get(c,{}).get("newin_cnt",0) or 0 for c in cf),
            "newprice": sum(stats.get(c,{}).get("newprice_cnt",0) or 0 for c in cf),
            "has_detail": self.has_detail,
        }

    def crawl_stats(self):
        return {r["city"]: dict(r) for r in self.conn.execute("SELECT * FROM crawl_stats")}

    def national(self):
        sql = f"""SELECT city, COUNT(*) cnt, ROUND(AVG(price),0) avg_price,
            ROUND(AVG(unit_price),1) avg_up, ROUND(AVG(age),1) avg_age,
            SUM(CASE WHEN discount_pct>0 THEN 1 ELSE 0 END) reduced_cnt,
            ROUND(AVG(monthly_fee),0) avg_fee
            FROM houses WHERE {ACTIVE} {self._cw()} GROUP BY city ORDER BY cnt DESC"""
        return [dict(r) for r in self.conn.execute(sql, self._cp())]

    def districts(self, city):
        sql = f"""SELECT zip_code, COUNT(*) cnt,
            ROUND(AVG(price),0) avg_price, ROUND(AVG(unit_price),1) avg_up,
            ROUND(AVG(age),1) avg_age, ROUND(AVG(building_area),1) avg_area,
            SUM(CASE WHEN discount_pct>0 THEN 1 ELSE 0 END) reduced_cnt,
            ROUND(AVG(watchers),0) avg_w,
            ROUND(AVG(monthly_fee),0) avg_fee
            FROM houses WHERE {ACTIVE} AND city=? GROUP BY zip_code ORDER BY cnt DESC"""
        return [dict(r) for r in self.conn.execute(sql, [city])]

    def price_dist(self, city):
        cases = " ".join(f"WHEN price<{u} THEN '{l}'" if u!=float('inf') else f"ELSE '{l}'"
                         for u,l in PRICE_BUCKETS)
        sql = f"SELECT CASE {cases} END bk, COUNT(*) cnt FROM houses WHERE price IS NOT NULL AND {ACTIVE} AND city=? GROUP BY bk"
        m = {r["bk"]:r["cnt"] for r in self.conn.execute(sql,[city])}
        return [{"bk":l,"cnt":m.get(l,0)} for _,l in PRICE_BUCKETS]

    def type_dist(self, city=None):
        w = f"WHERE {ACTIVE}" + (f" AND city=?" if city else f" {self._cw()}")
        p = [city] if city else self._cp()
        sql = f"SELECT type t, COUNT(*) cnt, ROUND(AVG(price),0) ap, ROUND(AVG(unit_price),1) aup FROM houses {w} GROUP BY type ORDER BY cnt DESC"
        agg = {}
        for r in self.conn.execute(sql, p):
            try: label = ", ".join(json.loads(r["t"] or "[]")) or "未分類"
            except: label = str(r["t"])
            if label in agg: agg[label]["cnt"] += r["cnt"]
            else: agg[label] = {"type":label,"cnt":r["cnt"],"ap":r["ap"],"aup":r["aup"]}
        return sorted(agg.values(), key=lambda x:x["cnt"], reverse=True)

    def discount_by_dist(self, city):
        sql = f"""SELECT zip_code, COUNT(*) total,
            SUM(CASE WHEN discount_pct>0 THEN 1 ELSE 0 END) rcnt,
            ROUND(100.0*SUM(CASE WHEN discount_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) rpct,
            ROUND(AVG(CASE WHEN discount_pct>0 THEN discount_pct END),2) adsc,
            MAX(discount_pct) mdsc,
            ROUND(AVG(CASE WHEN price_original>0 AND price>0 THEN price_original-price END),0) gap
            FROM houses WHERE {ACTIVE} AND city=? GROUP BY zip_code ORDER BY rpct DESC"""
        return [dict(r) for r in self.conn.execute(sql,[city])]

    def heat_district(self, city):
        sql = f"""SELECT zip_code, COUNT(*) cnt,
            ROUND(AVG(watchers),0) avg_w, SUM(watchers) tot_w,
            ROUND(100.0*SUM(CASE WHEN has_3dvr=1 THEN 1 ELSE 0 END)/COUNT(*),1) vr_pct,
            ROUND(100.0*SUM(CASE WHEN has_video=1 THEN 1 ELSE 0 END)/COUNT(*),1) vid_pct,
            ROUND(100.0*SUM(has_parking)/COUNT(*),1) park_pct,
            ROUND(100.0*SUM(has_balcony)/COUNT(*),1) balc_pct,
            ROUND(100.0*SUM(has_view)/COUNT(*),1) view_pct
            FROM houses WHERE {ACTIVE} AND city=? GROUP BY zip_code ORDER BY avg_w DESC"""
        return [dict(r) for r in self.conn.execute(sql,[city])]

    def tag_pop(self, city=None, top=20):
        w = f"WHERE tags IS NOT NULL AND {ACTIVE}" + (f" AND city=?" if city else f" {self._cw()}")
        p = [city] if city else self._cp()
        c = Counter()
        for (t,) in self.conn.execute(f"SELECT tags FROM houses {w}", p):
            try:
                for tag in json.loads(t): c[tag] += 1
            except: pass
        return c.most_common(top)

    # ── Detail 交叉分析 ──────────────────────────────────────────────

    def direction_analysis(self, city):
        """座向 × 平均單價。"""
        sql = f"""SELECT building_front dir, COUNT(*) cnt,
            ROUND(AVG(unit_price),1) avg_up, ROUND(AVG(price),0) avg_price
            FROM houses WHERE {ACTIVE} AND city=? AND building_front IS NOT NULL
            AND building_front != '' GROUP BY building_front ORDER BY cnt DESC"""
        return [dict(r) for r in self.conn.execute(sql,[city])]

    def structure_analysis(self, city):
        """建築結構 × 均價。"""
        sql = f"""SELECT structure, COUNT(*) cnt,
            ROUND(AVG(unit_price),1) avg_up, ROUND(AVG(age),1) avg_age
            FROM houses WHERE {ACTIVE} AND city=? AND structure IS NOT NULL
            AND structure != '' GROUP BY structure ORDER BY cnt DESC"""
        return [dict(r) for r in self.conn.execute(sql,[city])]

    def mgmt_analysis(self, city):
        """管理方式分佈 + 管理費分析。"""
        sql = f"""SELECT management mgmt, COUNT(*) cnt,
            ROUND(AVG(monthly_fee),0) avg_fee,
            ROUND(AVG(unit_price),1) avg_up
            FROM houses WHERE {ACTIVE} AND city=? AND management IS NOT NULL
            AND management != '' GROUP BY management ORDER BY cnt DESC"""
        return [dict(r) for r in self.conn.execute(sql,[city])]

    def layout_analysis(self, city):
        """格局（房數）× 均價。"""
        sql = f"""SELECT roomplus rooms, COUNT(*) cnt,
            ROUND(AVG(price),0) avg_price, ROUND(AVG(unit_price),1) avg_up,
            ROUND(AVG(building_area),1) avg_area
            FROM houses WHERE {ACTIVE} AND city=? AND roomplus IS NOT NULL
            AND roomplus > 0 GROUP BY roomplus ORDER BY roomplus"""
        return [dict(r) for r in self.conn.execute(sql,[city])]

    def side_darkroom(self, city):
        """邊間 / 暗房分佈。"""
        sql = f"""SELECT
            SUM(CASE WHEN is_side_unit=1 THEN 1 ELSE 0 END) side_cnt,
            SUM(CASE WHEN has_darkroom=1 THEN 1 ELSE 0 END) dark_cnt,
            COUNT(*) total,
            ROUND(AVG(CASE WHEN is_side_unit=1 THEN unit_price END),1) side_up,
            ROUND(AVG(CASE WHEN is_side_unit=0 OR is_side_unit IS NULL THEN unit_price END),1) nonside_up
            FROM houses WHERE {ACTIVE} AND city=? AND has_detail=1"""
        return dict(self.conn.execute(sql,[city]).fetchone())

    def agent_store_ranking(self, city, top=10):
        """門市委售物件數排名（委售數降序）。"""
        sql = f"""SELECT agent_store store, COUNT(*) cnt,
            ROUND(AVG(price),0) avg_price, ROUND(AVG(unit_price),1) avg_up
            FROM houses WHERE {ACTIVE} AND city=? AND agent_store IS NOT NULL
            AND agent_store != '' GROUP BY agent_store ORDER BY cnt DESC LIMIT ?"""
        return [dict(r) for r in self.conn.execute(sql,[city,top])]

    def age_price_cross(self, city):
        """屋齡區間 × 均單價。"""
        sql = f"""SELECT
            CASE WHEN age<5 THEN '0-5年' WHEN age<10 THEN '5-10年'
                 WHEN age<20 THEN '10-20年' WHEN age<30 THEN '20-30年'
                 ELSE '30年+' END age_grp,
            COUNT(*) cnt, ROUND(AVG(unit_price),1) avg_up,
            ROUND(AVG(price),0) avg_price
            FROM houses WHERE {ACTIVE} AND city=? AND age IS NOT NULL
            GROUP BY age_grp ORDER BY MIN(age)"""
        return [dict(r) for r in self.conn.execute(sql,[city])]

    # ── Drill-down 查詢（單一 zip_code 層級）─────────────────────────

    @staticmethod
    def _extract_street(addr):
        """從地址擷取路街名（含段）。"""
        if not addr: return "未知"
        m = re.search(r"(?:市|鄉|鎮|區)(.+?(?:路|街|大道)(?:[一二三四五六七八九十\d]*段)?)", addr)
        return m.group(1) if m else "其他"

    def street_analysis(self, zc):
        """路街 × 均價/均單價/物件數/屋齡。"""
        rows = self.conn.execute(f"""
            SELECT address, price, unit_price, age, building_area, watchers,
                   discount_pct, monthly_fee
            FROM houses WHERE {ACTIVE} AND zip_code=?""", [zc]).fetchall()
        agg = {}
        for r in rows:
            st = self._extract_street(r["address"])
            if st not in agg:
                agg[st] = {"cnt":0,"prices":[],"ups":[],"ages":[],"areas":[],"ws":[],"disc":0,"fees":[]}
            d = agg[st]; d["cnt"] += 1
            if r["price"]: d["prices"].append(r["price"])
            if r["unit_price"]: d["ups"].append(r["unit_price"])
            if r["age"] is not None: d["ages"].append(r["age"])
            if r["building_area"]: d["areas"].append(r["building_area"])
            if r["watchers"]: d["ws"].append(r["watchers"])
            if r["discount_pct"] and r["discount_pct"] > 0: d["disc"] += 1
            if r["monthly_fee"]: d["fees"].append(r["monthly_fee"])
        result = []
        for st, d in agg.items():
            avg = lambda lst: round(sum(lst)/len(lst),1) if lst else None
            result.append({"street":st,"cnt":d["cnt"],
                "avg_price":avg(d["prices"]),"avg_up":avg(d["ups"]),
                "avg_age":avg(d["ages"]),"avg_area":avg(d["areas"]),
                "avg_w":avg(d["ws"]),"disc_cnt":d["disc"],
                "avg_fee":avg(d["fees"])})
        return sorted(result, key=lambda x: x["cnt"], reverse=True)

    def community_analysis(self, zc):
        """社區 × 均價/均單價/屋齡/管理費（依物件數降序）。"""
        sql = f"""SELECT community, COUNT(*) cnt,
            ROUND(AVG(price),0) avg_price, ROUND(AVG(unit_price),1) avg_up,
            ROUND(AVG(age),1) avg_age, ROUND(AVG(monthly_fee),0) avg_fee,
            ROUND(AVG(building_area),1) avg_area, ROUND(AVG(watchers),0) avg_w
            FROM houses WHERE {ACTIVE} AND zip_code=?
            AND community IS NOT NULL AND community != ''
            GROUP BY community ORDER BY cnt DESC"""
        return [dict(r) for r in self.conn.execute(sql,[zc])]

    def age_segment_analysis(self, zc):
        """新屋/舊屋分段：預售(age=0)、5年內、5-10、10-20、20-30、30+。"""
        sql = f"""SELECT
            CASE WHEN age IS NULL OR age=0 THEN '預售/新成屋'
                 WHEN age<=5 THEN '5年內' WHEN age<=10 THEN '5-10年'
                 WHEN age<=20 THEN '10-20年' WHEN age<=30 THEN '20-30年'
                 ELSE '30年以上' END seg,
            COUNT(*) cnt, ROUND(AVG(price),0) avg_price,
            ROUND(AVG(unit_price),1) avg_up, ROUND(AVG(building_area),1) avg_area,
            ROUND(AVG(monthly_fee),0) avg_fee,
            SUM(CASE WHEN discount_pct>0 THEN 1 ELSE 0 END) disc_cnt
            FROM houses WHERE {ACTIVE} AND zip_code=?
            GROUP BY seg ORDER BY MIN(COALESCE(age,0))"""
        return [dict(r) for r in self.conn.execute(sql,[zc])]

    def zip_type_dist(self, zc):
        """單一行政區物件類型分佈。"""
        return self.type_dist_by_where(f"AND zip_code=?", [zc])

    def type_dist_by_where(self, extra_where, params):
        sql = f"""SELECT type t, COUNT(*) cnt, ROUND(AVG(price),0) ap,
            ROUND(AVG(unit_price),1) aup
            FROM houses WHERE {ACTIVE} {extra_where}
            GROUP BY type ORDER BY cnt DESC"""
        agg = {}
        for r in self.conn.execute(sql, params):
            try: label = ", ".join(json.loads(r["t"] or "[]")) or "未分類"
            except: label = str(r["t"])
            if label in agg: agg[label]["cnt"] += r["cnt"]
            else: agg[label] = {"type":label,"cnt":r["cnt"],"ap":r["ap"],"aup":r["aup"]}
        return sorted(agg.values(), key=lambda x:x["cnt"], reverse=True)

    def zip_direction(self, zc):
        """單一行政區座向分析。"""
        sql = f"""SELECT building_front dir, COUNT(*) cnt,
            ROUND(AVG(unit_price),1) avg_up, ROUND(AVG(price),0) avg_price
            FROM houses WHERE {ACTIVE} AND zip_code=? AND building_front IS NOT NULL
            AND building_front!='' GROUP BY building_front ORDER BY cnt DESC"""
        return [dict(r) for r in self.conn.execute(sql,[zc])]

    def zip_layout(self, zc):
        """單一行政區格局分析。"""
        sql = f"""SELECT roomplus rooms, COUNT(*) cnt,
            ROUND(AVG(price),0) avg_price, ROUND(AVG(unit_price),1) avg_up,
            ROUND(AVG(building_area),1) avg_area
            FROM houses WHERE {ACTIVE} AND zip_code=? AND roomplus IS NOT NULL
            AND roomplus>0 GROUP BY roomplus ORDER BY roomplus"""
        return [dict(r) for r in self.conn.execute(sql,[zc])]

    def zip_store_ranking(self, zc, top=10):
        """單一行政區門市排名（委售數降序）。"""
        sql = f"""SELECT agent_store store, COUNT(*) cnt,
            ROUND(AVG(price),0) avg_price, ROUND(AVG(unit_price),1) avg_up
            FROM houses WHERE {ACTIVE} AND zip_code=? AND agent_store IS NOT NULL
            AND agent_store!='' GROUP BY agent_store ORDER BY cnt DESC LIMIT ?"""
        return [dict(r) for r in self.conn.execute(sql,[zc,top])]

    def zip_store_inventory(self, zc, top=9999):
        """門市庫存分析（委售數降序）。"""
        sql = f"""SELECT agent_store store, COUNT(*) cnt,
            ROUND(AVG(price),0) avg_price, ROUND(AVG(unit_price),1) avg_up,
            ROUND(AVG(age),1) avg_age, ROUND(AVG(building_area),1) avg_area,
            SUM(CASE WHEN discount_pct>0 THEN 1 ELSE 0 END) disc_cnt,
            ROUND(100.0*SUM(CASE WHEN discount_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) disc_pct,
            SUM(CASE WHEN age IS NULL OR age<=5 THEN 1 ELSE 0 END) new_cnt,
            SUM(CASE WHEN age>5 AND age<=15 THEN 1 ELSE 0 END) mid_cnt,
            SUM(CASE WHEN age>15 THEN 1 ELSE 0 END) old_cnt,
            ROUND(AVG(watchers),0) avg_w,
            ROUND(AVG(monthly_fee),0) avg_fee
            FROM houses WHERE {ACTIVE} AND zip_code=? AND agent_store IS NOT NULL
            AND agent_store!='' GROUP BY agent_store ORDER BY cnt DESC LIMIT ?"""
        return [dict(r) for r in self.conn.execute(sql,[zc,top])]

    def store_type_breakdown(self, zc, top=10):
        """各門市 × 物件類型數量。"""
        sql = f"""SELECT agent_store store, type t, COUNT(*) cnt
            FROM houses WHERE {ACTIVE} AND zip_code=? AND agent_store IS NOT NULL
            AND agent_store!='' GROUP BY agent_store, type ORDER BY agent_store, cnt DESC"""
        rows = self.conn.execute(sql, [zc]).fetchall()
        # 彙整成 {store: {type_label: cnt}}
        result = {}
        for r in rows:
            store = r["store"]
            try: label = ", ".join(json.loads(r["t"] or "[]")) or "未分類"
            except: label = str(r["t"])
            if store not in result: result[store] = {}
            result[store][label] = result[store].get(label, 0) + r["cnt"]
        return result

    @staticmethod
    def _is_residential_type(type_json):
        """判斷 type JSON 是否為住宅。"""
        if not type_json: return False
        for t in RESIDENTIAL_TYPES:
            if t in type_json:
                return True
        return False

    def listing_days_analysis(self, zc):
        """上架天數分析（分住宅/商用堆疊）。"""
        sql = f"""SELECT
            CAST(julianday('now') - julianday(first_listed) AS INTEGER) AS days,
            id, price, unit_price, type, name, discount_pct, agent_store
            FROM houses WHERE {ACTIVE} AND zip_code=?
            AND first_listed IS NOT NULL AND first_listed!=''"""
        rows = [dict(r) for r in self.conn.execute(sql, [zc])]
        if not rows:
            return {}
        SEG_ORDER = ["7天內", "8-30天", "1-3月", "3-6月", "6-12月", "1年+"]
        def _seg(d):
            if d <= 7: return "7天內"
            if d <= 30: return "8-30天"
            if d <= 90: return "1-3月"
            if d <= 180: return "3-6月"
            if d <= 365: return "6-12月"
            return "1年+"
        # 分住宅/商用計數
        res_bk = {s:0 for s in SEG_ORDER}
        com_bk = {s:0 for s in SEG_ORDER}
        days_list = []
        for r in rows:
            d = r["days"] or 0
            days_list.append(d)
            seg = _seg(d)
            if self._is_residential_type(r.get("type","")): res_bk[seg] += 1
            else: com_bk[seg] += 1
        total_bk = {s: res_bk[s] + com_bk[s] for s in SEG_ORDER}
        # 各區段物件清單
        seg_items = {s: [] for s in SEG_ORDER}
        for r in rows:
            seg_items[_seg(r["days"] or 0)].append(r)
        # 各區段內按天數降序
        for s in SEG_ORDER:
            seg_items[s].sort(key=lambda x: x["days"] or 0, reverse=True)
        # 滯銷
        stale_all = sorted([r for r in rows if (r["days"] or 0) > 180],
                           key=lambda x: x["days"] or 0, reverse=True)
        stale_res = [r for r in stale_all if self._is_residential_type(r.get("type",""))]
        stale_com = [r for r in stale_all if not self._is_residential_type(r.get("type",""))]
        return {"seg_order": SEG_ORDER, "total_bk": total_bk,
                "res_bk": res_bk, "com_bk": com_bk,
                "seg_items": seg_items,
                "total": len(rows),
                "avg_days": round(sum(days_list)/len(days_list),1) if days_list else 0,
                "stale_res": stale_res[:15], "stale_com": stale_com[:15]}

    def residential_vs_commercial(self, zc):
        """住宅 vs 商用對比。"""
        result = {}
        for label, where_fn in [("住宅", _is_residential_where), ("商用", _is_commercial_where)]:
            sql = f"""SELECT COUNT(*) cnt,
                ROUND(AVG(price),0) avg_price, ROUND(AVG(unit_price),1) avg_up,
                ROUND(AVG(age),1) avg_age, ROUND(AVG(building_area),1) avg_area,
                ROUND(AVG(monthly_fee),0) avg_fee, ROUND(AVG(watchers),0) avg_w,
                SUM(CASE WHEN discount_pct>0 THEN 1 ELSE 0 END) disc
                FROM houses WHERE {ACTIVE} AND zip_code=? AND {where_fn()}"""
            r = self.conn.execute(sql, [zc]).fetchone()
            result[label] = dict(r)
        return result

    def residential_streets(self, zc):
        """住宅物件路街分析。"""
        rows = self.conn.execute(f"""
            SELECT address, price, unit_price, age, building_area, watchers,
                   discount_pct, monthly_fee
            FROM houses WHERE {ACTIVE} AND zip_code=? AND {_is_residential_where()}""",
            [zc]).fetchall()
        return self._aggregate_streets(rows)

    def commercial_streets(self, zc):
        """商用物件路街分析。"""
        rows = self.conn.execute(f"""
            SELECT address, price, unit_price, age, building_area, watchers,
                   discount_pct, monthly_fee
            FROM houses WHERE {ACTIVE} AND zip_code=? AND {_is_commercial_where()}""",
            [zc]).fetchall()
        return self._aggregate_streets(rows)

    def _aggregate_streets(self, rows):
        agg = {}
        for r in rows:
            st = self._extract_street(r["address"])
            if st not in agg:
                agg[st] = {"cnt":0,"prices":[],"ups":[],"ages":[],"areas":[],"ws":[],"disc":0,"fees":[]}
            d = agg[st]; d["cnt"] += 1
            if r["price"]: d["prices"].append(r["price"])
            if r["unit_price"]: d["ups"].append(r["unit_price"])
            if r["age"] is not None: d["ages"].append(r["age"])
            if r["building_area"]: d["areas"].append(r["building_area"])
            if r["watchers"]: d["ws"].append(r["watchers"])
            if r["discount_pct"] and r["discount_pct"] > 0: d["disc"] += 1
            if r["monthly_fee"]: d["fees"].append(r["monthly_fee"])
        result = []
        avg = lambda lst: round(sum(lst)/len(lst),1) if lst else None
        for st, d in agg.items():
            result.append({"street":st,"cnt":d["cnt"],
                "avg_price":avg(d["prices"]),"avg_up":avg(d["ups"]),
                "avg_age":avg(d["ages"]),"avg_area":avg(d["areas"]),
                "avg_w":avg(d["ws"]),"disc_cnt":d["disc"],"avg_fee":avg(d["fees"])})
        return sorted(result, key=lambda x: x["cnt"], reverse=True)

    def zip_listing_table(self, zc, limit=200):
        """單一行政區物件清單（筆畫排序）。"""
        sql = f"""SELECT id, name, address, price, unit_price, age,
            layout, building_area, floor, total_floor,
            building_front, management, monthly_fee,
            watchers, discount_pct, community, agent_store,
            has_parking, has_balcony, has_view, detail_url
            FROM houses WHERE {ACTIVE} AND zip_code=?"""
        rows = [dict(r) for r in self.conn.execute(sql,[zc])]
        return sorted(rows, key=lambda x: _zh_key(x["name"] or ""))[:limit]

    def close(self):
        self.conn.close()


# ══════════════════════════════════════════════════════════════════════
#  SVG & helpers
# ══════════════════════════════════════════════════════════════════════

def _zh_key(s):
    """中文排序 key（注音/筆畫序）。"""
    try:
        return locale.strxfrm(s or "")
    except Exception:
        return s or ""


def _f(n, d=0):
    if n is None: return "–"
    return f"{int(n):,}" if d==0 else f"{n:,.{d}f}"

def _bar(labels, vals, w=620, bh=26, g=6, color="#c0392b", lw=120, fd=0):
    if not vals: return ""
    mx = max((v or 0) for v in vals) or 1
    ba = w-lw-80; th = len(labels)*(bh+g)+10
    o = [f'<svg width="{w}" height="{th}" xmlns="http://www.w3.org/2000/svg" style="font-family:sans-serif;font-size:12px;">']
    for i,(lb,v) in enumerate(zip(labels,vals)):
        y=i*(bh+g)+5; bw=max(2,(v or 0)/mx*ba)
        o.append(f'<text x="{lw-8}" y="{y+bh*.7}" text-anchor="end" fill="#374151">{escape(str(lb))}</text>')
        o.append(f'<rect x="{lw}" y="{y}" width="{bw:.0f}" height="{bh}" rx="4" fill="{color}" opacity="0.85"/>')
        o.append(f'<text x="{lw+bw+6}" y="{y+bh*.7}" fill="#6b7280">{_f(v,fd)}</text>')
    o.append("</svg>"); return "\n".join(o)

def _donut(slices, sz=220, cols=None):
    if not slices: return ""
    cols=cols or COLORS; tot=sum(v for _,v in slices)
    if tot==0: return ""
    cx,cy,r=sz//2,sz//2,sz//2-20; ci=2*math.pi*r
    o=[f'<svg width="{sz+180}" height="{max(sz,len(slices)*22+10)}" xmlns="http://www.w3.org/2000/svg" style="font-family:sans-serif;font-size:12px;">']
    off=0
    for i,(lb,v) in enumerate(slices):
        d=v/tot*ci; c=cols[i%len(cols)]
        o.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{c}" stroke-width="36" stroke-dasharray="{d:.2f} {ci:.2f}" stroke-dashoffset="{-off:.2f}" transform="rotate(-90 {cx} {cy})"/>')
        off+=d
    o.append(f'<circle cx="{cx}" cy="{cy}" r="{r-22}" fill="white"/>')
    o.append(f'<text x="{cx}" y="{cy-6}" text-anchor="middle" fill="#1a365d" font-size="18" font-weight="700">{_f(tot)}</text>')
    o.append(f'<text x="{cx}" y="{cy+14}" text-anchor="middle" fill="#6b7280" font-size="11">物件</text>')
    lx=sz+10
    for i,(lb,v) in enumerate(slices[:12]):
        ly=16+i*22; c=cols[i%len(cols)]
        o.append(f'<rect x="{lx}" y="{ly-10}" width="14" height="14" rx="3" fill="{c}"/>')
        o.append(f'<text x="{lx+20}" y="{ly}" fill="#374151">{escape(lb)} ({v/tot*100:.1f}%)</text>')
    o.append("</svg>"); return "\n".join(o)

def _pct_stacked_bar(labels, values, colors, total, w=900, bh=36):
    """單條 100% 橫向堆疊長條圖 — 各區段佔比。"""
    if not values or total == 0: return ""
    bar_w = w - 20
    cols = 3
    legend_rows = math.ceil(len(labels) / cols)
    th = bh + 12 + legend_rows * 20
    o = [f'<svg width="{w}" height="{th}" xmlns="http://www.w3.org/2000/svg" '
         f'style="font-family:sans-serif;font-size:12px;">']
    x = 10
    for i, (lb, v) in enumerate(zip(labels, values)):
        if v <= 0: continue
        pct = v / total
        bw = pct * bar_w
        c = colors[i % len(colors)]
        o.append(f'<rect x="{x}" y="4" width="{bw:.1f}" height="{bh}" fill="{c}" opacity="0.9"/>')
        if bw > 45:
            o.append(f'<text x="{x+bw/2}" y="{4+bh/2+5}" text-anchor="middle" '
                     f'fill="#fff" font-size="12" font-weight="700">{pct*100:.1f}%</text>')
        x += bw
    # legend 三欄
    col_w = w // cols
    for i, (lb, v) in enumerate(zip(labels, values)):
        c = colors[i % len(colors)]
        pct = v / total * 100
        col = i % cols; row = i // cols
        lx = 10 + col * col_w
        ly = bh + 12 + row * 20
        o.append(f'<rect x="{lx}" y="{ly}" width="12" height="12" rx="2" fill="{c}"/>')
        o.append(f'<text x="{lx+16}" y="{ly+10}" fill="#374151" font-size="11">'
                 f'{escape(lb)} {v}筆 ({pct:.1f}%)</text>')
    o.append("</svg>")
    return "\n".join(o)


def _stacked_bar(labels, series, colors, series_labels, w=650, bh=28, g=8, lw=80):
    """橫向堆疊長條圖 SVG。series = [[val_per_label], ...]"""
    if not labels: return ""
    max_t = max(sum(s[i] for s in series) for i in range(len(labels))) or 1
    ba = w - lw - 100
    th = len(labels)*(bh+g)+40
    o = [f'<svg width="{w}" height="{th}" xmlns="http://www.w3.org/2000/svg" '
         f'style="font-family:sans-serif;font-size:12px;">']
    for i, lb in enumerate(labels):
        y = i*(bh+g)+5
        o.append(f'<text x="{lw-8}" y="{y+bh*.7}" text-anchor="end" fill="#374151">{escape(str(lb))}</text>')
        x = lw; tot = sum(s[i] for s in series)
        for si, sv in enumerate(series):
            v = sv[i]
            if v <= 0: continue
            bw = max(1, v/max_t*ba)
            o.append(f'<rect x="{x}" y="{y}" width="{bw:.1f}" height="{bh}" fill="{colors[si]}" opacity="0.85"/>')
            if bw > 25:
                o.append(f'<text x="{x+bw/2}" y="{y+bh*.7}" text-anchor="middle" fill="#fff" font-size="11" font-weight="600">{v}</text>')
            x += bw
        o.append(f'<text x="{x+6}" y="{y+bh*.7}" fill="#6b7280">{tot}</text>')
    # legend
    ly = len(labels)*(bh+g)+12; lx = lw
    for si, sl in enumerate(series_labels):
        o.append(f'<rect x="{lx}" y="{ly}" width="14" height="14" rx="3" fill="{colors[si]}"/>')
        o.append(f'<text x="{lx+18}" y="{ly+11}" fill="#374151">{escape(sl)}</text>')
        lx += len(sl)*13+30
    o.append("</svg>"); return "\n".join(o)


def _hbg(v,lo,hi,base=(192,57,43)):
    if hi==lo: i=0.15
    else: i=0.08+0.55*((v or 0)-lo)/(hi-lo)
    return f"rgba({base[0]},{base[1]},{base[2]},{i:.2f})"

def _tbl(headers, rows_data, classes=None):
    """通用表格產生。rows_data = list of list of str。"""
    classes = classes or ["" for _ in headers]
    ths = "".join(f'<th>{h}</th>' for h in headers)
    trs = []
    for row in rows_data:
        tds = "".join(f'<td class="{cls}">{cell}</td>' for cell, cls in zip(row, classes))
        trs.append(f"<tr>{tds}</tr>")
    return f'<table><thead><tr>{ths}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


# ══════════════════════════════════════════════════════════════════════
#  CSS + JS
# ══════════════════════════════════════════════════════════════════════

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang TC","Noto Sans TC",sans-serif;background:#f8fafc;color:#1e293b;line-height:1.55}
header{background:linear-gradient(135deg,#1a365d 0%,#2563eb 100%);color:#fff;padding:32px 40px 26px}
header h1{font-size:1.8rem;font-weight:800} header p{font-size:.88rem;margin-top:6px;opacity:.8}
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;padding:24px 40px;max-width:1320px;margin:0 auto}
.kpi{background:#fff;border-radius:12px;padding:18px 20px;box-shadow:0 1px 6px rgba(0,0,0,.06);text-align:center}
.kpi .num{font-size:1.5rem;font-weight:800;color:#1a365d} .kpi .label{font-size:.78rem;color:#6b7280;margin-top:4px}
.s{max-width:1320px;margin:0 auto;padding:0 40px 28px}
.s h2{font-size:1.25rem;font-weight:700;color:#1a365d;border-bottom:3px solid #2563eb;padding-bottom:8px;margin:30px 0 16px}
.s h3{font-size:1rem;font-weight:600;color:#374151;margin:16px 0 8px}
table{width:100%;border-collapse:collapse;font-size:.83rem;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.05);margin:8px 0}
th{background:#1a365d;color:#fff;padding:9px 12px;text-align:left;font-weight:600;white-space:nowrap;cursor:pointer;user-select:none;position:sticky;top:0}
th:hover{background:#2563eb} td{padding:7px 12px;border-bottom:1px solid #f1f5f9} tr:hover td{background:#f0f9ff}
.n{text-align:right;font-variant-numeric:tabular-nums}
details{margin:8px 0} summary{font-size:1.02rem;font-weight:600;color:#1a365d;cursor:pointer;padding:8px 0;list-style:none}
summary::before{content:"▸ "} details[open] summary::before{content:"▾ "} summary::-webkit-details-marker{display:none}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:start}
@media(max-width:900px){.two-col{grid-template-columns:1fr}}
.cb{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,.05);margin:8px 0;overflow-x:auto}
.footer{text-align:center;padding:20px;font-size:.76rem;color:#94a3b8;border-top:1px solid #e2e8f0;margin-top:36px}
.pg{display:flex;gap:4px;align-items:center;margin:8px 0;flex-wrap:wrap}
.pg button{border:1px solid #d1d5db;background:#fff;border-radius:6px;padding:4px 12px;font-size:.82rem;cursor:pointer;color:#374151}
.pg button:hover{background:#f0f9ff;border-color:#2563eb}
.pg button.active{background:#2563eb;color:#fff;border-color:#2563eb}
.pg span{font-size:.8rem;color:#6b7280;margin:0 6px}
@media print{body{background:#fff}header{background:#1a365d!important;-webkit-print-color-adjust:exact}th{background:#1a365d!important;-webkit-print-color-adjust:exact}.kpi,table,.s{box-shadow:none}.pg{display:none}tr{display:table-row!important}}
"""

JS = """
(function(){
const PAGE=15;

/* 表格排序 */
document.querySelectorAll('th').forEach(th=>{th.addEventListener('click',function(){
const t=this.closest('table'),b=t.querySelector('tbody'),
i=Array.from(this.parentNode.children).indexOf(this),
rows=Array.from(b.querySelectorAll('tr')),asc=this.dataset.sort!=='asc';
rows.sort((a,c)=>{let va=a.children[i].textContent.replace(/[,%–]/g,'').trim(),
vb=c.children[i].textContent.replace(/[,%–]/g,'').trim();
const na=parseFloat(va),nb=parseFloat(vb);
if(!isNaN(na)&&!isNaN(nb))return asc?na-nb:nb-na;
return asc?va.localeCompare(vb,'zh-TW'):vb.localeCompare(va,'zh-TW')});
rows.forEach(r=>b.appendChild(r));
t.querySelectorAll('th').forEach(x=>delete x.dataset.sort);
this.dataset.sort=asc?'asc':'desc';
/* 排序後重設分頁 */
const pg=t.nextElementSibling;
if(pg&&pg.classList.contains('pg'))showPage(t,1);
})});

/* 分頁 */
function showPage(tbl,page){
const rows=Array.from(tbl.querySelector('tbody').querySelectorAll('tr'));
const total=rows.length, pages=Math.ceil(total/PAGE);
rows.forEach((r,i)=>{r.style.display=(i>=PAGE*(page-1)&&i<PAGE*page)?'':'none'});
const pg=tbl.nextElementSibling;
if(!pg||!pg.classList.contains('pg'))return;
pg.innerHTML='';
/* info */
const info=document.createElement('span');
info.textContent=page+'/'+pages+'頁 (共'+total+'筆)';
pg.appendChild(info);
/* buttons */
for(let p=1;p<=pages;p++){
const btn=document.createElement('button');
btn.textContent=p;
if(p===page)btn.classList.add('active');
btn.onclick=()=>showPage(tbl,p);
pg.appendChild(btn);
}
}

/* 初始化：對超過 PAGE 筆的表格加分頁 */
document.querySelectorAll('table').forEach(tbl=>{
const rows=tbl.querySelectorAll('tbody tr');
if(rows.length<=PAGE)return;
const pg=document.createElement('div');
pg.className='pg';
tbl.after(pg);
showPage(tbl,1);
});
})();
"""


# ══════════════════════════════════════════════════════════════════════
#  HTML 區塊
# ══════════════════════════════════════════════════════════════════════

def _header(d, db_path):
    now=datetime.now().strftime("%Y-%m-%d %H:%M"); dn=Path(db_path).name
    sc = f" — {', '.join(CITY_LABEL.get(c,c) for c in d.cities)}" if d.cities else ""
    det = "含完整明細" if d.has_detail else "僅搜尋列表"
    return f'<header><h1>房屋市場分析報表</h1><p>資料：{escape(dn)}{sc} ｜ {det} ｜ {now}</p></header>'

def _kpi(d):
    k=d.kpis()
    cards=[("委售物件",_f(k["total"]),"筆"),("平均單價",_f(k["avg_up"],1),"萬/坪"),
           ("平均總價",_f(k["avg_price"]),"萬"),("新上架",_f(k["newin"]),"筆"),
           ("新降價",_f(k["newprice"]),"筆"),("最高關注",_f(k["max_w"]),"人次")]
    if k.get("avg_fee"): cards.insert(3,("平均管理費",_f(k["avg_fee"]),"元/月"))
    items="".join(f'<div class="kpi"><div class="num">{v}</div><div class="label">{lb}（{u}）</div></div>' for lb,v,u in cards)
    return f'<div class="kpi-row">{items}</div>'

def _sec1(d):
    rows=d.national(); stats=d.crawl_stats(); N="n"
    trs=[]
    for r in rows:
        c=r["city"]; s=stats.get(c,{}); lb=CITY_LABEL.get(c,c)
        rp=r["reduced_cnt"]/r["cnt"]*100 if r["cnt"] else 0
        trs.append([lb,_f(r["cnt"]),_f(r["avg_price"]),_f(r["avg_up"],1),
                    _f(r["avg_age"],1),_f(r.get("avg_fee")),
                    _f(s.get("newin_cnt",0)),_f(s.get("newprice_cnt",0)),f"{rp:.1f}%"])
    hdrs=["城市","物件數","均總價(萬)","均單價(萬/坪)","均屋齡","均管理費(元)","新上架","新降價","降價比例"]
    cls=["",N,N,N,N,N,N,N,N]
    tbl=_tbl(hdrs,trs,cls)
    labels=[CITY_LABEL.get(r["city"],r["city"]) for r in rows]; vals=[r["cnt"] for r in rows]
    chart=_bar(labels,vals,color="#2563eb")
    return f'<div class="s"><h2>一、全台市場總覽</h2>{tbl}<div class="cb"><h3>各城市委售物件數量</h3>{chart}</div></div>'

def _sec2(d):
    parts=[]
    for city in d.city_list():
        lb=CITY_LABEL.get(city,city); ds=d.districts(city)
        if not ds: continue
        vup=[x["avg_up"] or 0 for x in ds]; vw=[x["avg_w"] or 0 for x in ds]
        lop,hip=min(vup),max(vup); low,hiw=min(vw),max(vw)
        trs=[]
        for x in ds:
            dn=d.dn(x["zip_code"]); rp=x["reduced_cnt"]/x["cnt"]*100 if x["cnt"] else 0
            bgp=_hbg(x["avg_up"] or 0,lop,hip); bgw=_hbg(x["avg_w"] or 0,low,hiw,(37,99,235))
            trs.append(f'<tr><td>{escape(dn)}</td><td class="n">{_f(x["cnt"])}</td>'
                f'<td class="n">{_f(x["avg_price"])}</td>'
                f'<td class="n" style="background:{bgp}">{_f(x["avg_up"],1)}</td>'
                f'<td class="n">{_f(x["avg_area"],1)}</td><td class="n">{_f(x["avg_age"],1)}</td>'
                f'<td class="n">{_f(x.get("avg_fee"))}</td><td class="n">{rp:.1f}%</td>'
                f'<td class="n" style="background:{bgw}">{_f(x["avg_w"])}</td></tr>')
        tbl=f'<table><thead><tr><th>行政區</th><th>物件數</th><th>均總價(萬)</th><th>均單價(萬/坪)</th><th>均坪數</th><th>均屋齡</th><th>均管理費</th><th>降價比例</th><th>均關注</th></tr></thead><tbody>{"".join(trs)}</tbody></table>'
        pd=d.price_dist(city); pc=_bar([x["bk"] for x in pd],[x["cnt"] for x in pd],color="#0d9488",lw=140)
        tot=sum(x["cnt"] for x in ds)
        parts.append(f'<details><summary>{escape(lb)}（{_f(tot)} 筆）</summary>{tbl}<div class="cb"><h3>價格分佈</h3>{pc}</div></details>')
    return f'<div class="s"><h2>二、行政區產銷分析</h2>{"".join(parts)}</div>'

def _sec3(d):
    parts=[]
    for city in d.city_list():
        lb=CITY_LABEL.get(city,city)
        # 類型環狀圖
        td=d.type_dist(city)
        donut=_donut([(x["type"],x["cnt"]) for x in td[:10]])
        # 類型表
        type_rows=[[escape(x["type"]),_f(x["cnt"]),_f(x["ap"]),_f(x["aup"],1)] for x in td[:12]]
        type_tbl=_tbl(["物件類型","數量","均總價(萬)","均單價(萬/坪)"],type_rows,["","n","n","n"])
        # 降價表
        disc=d.discount_by_dist(city)
        disc_rows=[[escape(d.dn(x["zip_code"])),_f(x["total"]),_f(x["rcnt"]),
                    f'{x["rpct"] or 0:.1f}%',f'{x["adsc"] or 0:.2f}%',
                    f'{x["mdsc"] or 0:.1f}%',_f(x["gap"])] for x in disc]
        disc_tbl=_tbl(["行政區","總筆數","降價筆數","降價比例","平均降幅","最大降幅","均價差(萬)"],
                      disc_rows,["","n","n","n","n","n","n"])
        parts.append(f'<details><summary>{escape(lb)}</summary>'
            f'<div class="two-col"><div class="cb">{donut}</div><div>{type_tbl}</div></div>'
            f'<h3>各行政區降價分析</h3>{disc_tbl}</details>')
    return f'<div class="s"><h2>三、委託售屋分析</h2>{"".join(parts)}</div>'

def _sec4(d):
    parts=[]
    for city in d.city_list():
        lb=CITY_LABEL.get(city,city); h=d.heat_district(city)
        if not h: continue
        chart=_bar([d.dn(x["zip_code"]) for x in h],[x["avg_w"] or 0 for x in h],color="#d97706",lw=100)
        rows=[[escape(d.dn(x["zip_code"])),_f(x["cnt"]),_f(x["avg_w"]),
               f'{x["vr_pct"] or 0:.1f}%',f'{x["vid_pct"] or 0:.1f}%',
               f'{x["park_pct"] or 0:.1f}%',f'{x["balc_pct"] or 0:.1f}%',
               f'{x["view_pct"] or 0:.1f}%'] for x in h]
        tbl=_tbl(["行政區","物件數","均關注","3DVR","影片","車位","陽台","景觀"],
                 rows,["","n","n","n","n","n","n","n"])
        parts.append(f'<details><summary>{escape(lb)}</summary>'
            f'<div class="cb"><h3>關注度排名</h3>{chart}</div>{tbl}</details>')
    return f'<div class="s"><h2>四、市場熱度 & 物件特徵</h2>{"".join(parts)}</div>'

def _sec5_detail(d):
    """五、Detail 交叉分析（座向×單價、結構×單價、管理費、格局、屋齡、門市、邊間）。"""
    if not d.has_detail:
        return '<div class="s"><h2>五、深度交叉分析</h2><p>⚠ 無 detail 資料，請用 <code>--enrich</code> 補抓後再產報表。</p></div>'
    parts=[]
    for city in d.city_list():
        lb=CITY_LABEL.get(city,city)
        inner=""
        # 座向 × 單價
        dirs=d.direction_analysis(city)
        if dirs:
            rows=[[escape(x["dir"] or "–"),_f(x["cnt"]),_f(x["avg_up"],1),_f(x["avg_price"])] for x in dirs]
            inner+=f'<h3>座向 × 均單價</h3>{_tbl(["座向","物件數","均單價(萬/坪)","均總價(萬)"],rows,["","n","n","n"])}'
        # 建築結構
        stru=d.structure_analysis(city)
        if stru:
            rows=[[escape(x["structure"] or "–"),_f(x["cnt"]),_f(x["avg_up"],1),_f(x["avg_age"],1)] for x in stru]
            inner+=f'<h3>建築結構 × 均單價</h3>{_tbl(["結構","物件數","均單價(萬/坪)","均屋齡"],rows,["","n","n","n"])}'
        # 管理方式
        mgmt=d.mgmt_analysis(city)
        if mgmt:
            rows=[[escape(x["mgmt"] or "–"),_f(x["cnt"]),_f(x["avg_fee"]),_f(x["avg_up"],1)] for x in mgmt]
            inner+=f'<h3>管理方式 × 管理費 × 單價</h3>{_tbl(["管理方式","物件數","均管理費(元)","均單價(萬/坪)"],rows,["","n","n","n"])}'
        # 格局（房數）
        lo=d.layout_analysis(city)
        if lo:
            rows=[[f'{x["rooms"]}房',_f(x["cnt"]),_f(x["avg_price"]),_f(x["avg_up"],1),_f(x["avg_area"],1)] for x in lo]
            inner+=f'<h3>房數 × 均價 × 坪數</h3>{_tbl(["格局","物件數","均總價(萬)","均單價(萬/坪)","均坪數"],rows,["","n","n","n","n"])}'
        # 屋齡區間
        ap=d.age_price_cross(city)
        if ap:
            rows=[[x["age_grp"],_f(x["cnt"]),_f(x["avg_up"],1),_f(x["avg_price"])] for x in ap]
            inner+=f'<h3>屋齡 × 均單價</h3>{_tbl(["屋齡區間","物件數","均單價(萬/坪)","均總價(萬)"],rows,["","n","n","n"])}'
        # 邊間 / 暗房
        sd=d.side_darkroom(city)
        if sd and sd.get("total"):
            t=sd["total"]
            inner+=f'<h3>邊間 / 暗房</h3><table><thead><tr><th>指標</th><th>數值</th></tr></thead><tbody>'
            inner+=f'<tr><td>邊間比例</td><td class="n">{sd["side_cnt"] or 0}/{t} ({(sd["side_cnt"] or 0)/t*100:.1f}%)</td></tr>'
            inner+=f'<tr><td>暗房比例</td><td class="n">{sd["dark_cnt"] or 0}/{t} ({(sd["dark_cnt"] or 0)/t*100:.1f}%)</td></tr>'
            inner+=f'<tr><td>邊間均單價</td><td class="n">{_f(sd["side_up"],1)} 萬/坪</td></tr>'
            inner+=f'<tr><td>非邊間均單價</td><td class="n">{_f(sd["nonside_up"],1)} 萬/坪</td></tr>'
            inner+=f'</tbody></table>'
        # 門市排名
        stores=d.agent_store_ranking(city)
        if stores:
            rows=[[escape(x["store"] or "–"),_f(x["cnt"]),_f(x["avg_price"]),_f(x["avg_up"],1)] for x in stores]
            inner+=f'<h3>門市委售排名 Top 10</h3>{_tbl(["門市","物件數","均總價(萬)","均單價(萬/坪)"],rows,["","n","n","n"])}'

        if inner:
            parts.append(f'<details><summary>{escape(lb)}</summary>{inner}</details>')

    return f'<div class="s"><h2>五、深度交叉分析</h2>{"".join(parts)}</div>'

def _sec6_tags(d, top=20):
    tags=d.tag_pop(top=top)
    chart=_bar([t[0] for t in tags],[t[1] for t in tags],color="#7c3aed")
    parts=[f'<div class="cb"><h3>全台標籤熱度 Top {top}</h3>{chart}</div>']
    for city in d.city_list():
        lb=CITY_LABEL.get(city,city)
        tc=d.tag_pop(city=city,top=10)
        if not tc: continue
        c=_bar([t[0] for t in tc],[t[1] for t in tc],color="#7c3aed",w=500)
        parts.append(f'<details><summary>{escape(lb)}</summary><div class="cb">{c}</div></details>')
    return f'<div class="s"><h2>六、標籤熱度分析</h2>{"".join(parts)}</div>'

def _footer():
    return f'<div class="footer">house-search-mcp 自動產生 ｜ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}<br>僅供內部決策參考</div>'


# ══════════════════════════════════════════════════════════════════════
#  行政區 Drill-down 報表
# ══════════════════════════════════════════════════════════════════════

def _drill_header(d, db_path, zc):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    dn_name = d.dn(zc)
    return (f'<header><h1>{escape(dn_name)} 外網產品深度分析報表報表</h1>'
            f'<p>zip={zc} ｜ 資料：{escape(Path(db_path).name)} ｜ {now}</p></header>')


def _drill_kpi(d, zc):
    sql = f"""SELECT COUNT(*) total, ROUND(AVG(price),0) ap,
        ROUND(AVG(unit_price),1) aup, ROUND(AVG(age),1) aa,
        ROUND(AVG(monthly_fee),0) af, ROUND(AVG(building_area),1) aarea,
        MAX(watchers) mw,
        SUM(CASE WHEN discount_pct>0 THEN 1 ELSE 0 END) disc
        FROM houses WHERE {ACTIVE} AND zip_code=?"""
    r = d.conn.execute(sql, [zc]).fetchone()
    cards = [("委售物件",_f(r["total"]),"筆"), ("均總價",_f(r["ap"]),"萬"),
             ("均單價",_f(r["aup"],1),"萬/坪"), ("均屋齡",_f(r["aa"],1),"年"),
             ("均坪數",_f(r["aarea"],1),"坪"), ("均管理費",_f(r["af"]),"元/月"),
             ("降價物件",_f(r["disc"]),"筆"), ("最高關注",_f(r["mw"]),"人次")]
    items = "".join(f'<div class="kpi"><div class="num">{v}</div>'
                    f'<div class="label">{lb}（{u}）</div></div>' for lb,v,u in cards)
    return f'<div class="kpi-row">{items}</div>'


def _drill_streets(d, zc):
    """路街分析。"""
    streets = d.street_analysis(zc)
    if not streets: return ""
    N = "n"
    rows = []
    for s in streets:
        dp = f'{s["disc_cnt"]}/{s["cnt"]}' if s["cnt"] else "–"
        rows.append([escape(s["street"]), _f(s["cnt"]), _f(s["avg_price"]),
                     _f(s["avg_up"],1), _f(s["avg_age"],1), _f(s["avg_area"],1),
                     _f(s["avg_fee"]), dp, _f(s["avg_w"])])
    tbl = _tbl(["路街","物件數","均總價(萬)","均單價(萬/坪)","均屋齡","均坪數",
                "均管理費","降價數","均關注"],
               rows, ["",N,N,N,N,N,N,N,N])
    # 長條圖
    chart = _bar([s["street"] for s in streets[:20]],
                 [s["cnt"] for s in streets[:20]],
                 color="#2563eb", lw=140)
    return (f'<div class="s"><h2>一、路街分析</h2>{tbl}'
            f'<div class="cb"><h3>物件數量分佈</h3>{chart}</div></div>')


def _drill_communities(d, zc):
    """社區分析。"""
    comms = d.community_analysis(zc)
    if not comms: return ""
    N = "n"
    rows = [[escape(c["community"]), _f(c["cnt"]), _f(c["avg_price"]),
             _f(c["avg_up"],1), _f(c["avg_age"],1), _f(c["avg_area"],1),
             _f(c["avg_fee"]), _f(c["avg_w"])] for c in comms[:30]]
    tbl = _tbl(["社區","物件數","均總價(萬)","均單價(萬/坪)","均屋齡","均坪數",
                "均管理費(元)","均關注"],
               rows, ["",N,N,N,N,N,N,N])
    return f'<div class="s"><h2>二、社區分析</h2>{tbl}</div>'


def _drill_age_segment(d, zc):
    """新屋/舊屋分析。"""
    segs = d.age_segment_analysis(zc)
    if not segs: return ""
    N = "n"
    rows = []
    for s in segs:
        dp = f'{s["disc_cnt"]}/{s["cnt"]}' if s["cnt"] else "–"
        rows.append([s["seg"], _f(s["cnt"]), _f(s["avg_price"]), _f(s["avg_up"],1),
                     _f(s["avg_area"],1), _f(s["avg_fee"]), dp])
    tbl = _tbl(["屋齡分段","物件數","均總價(萬)","均單價(萬/坪)","均坪數","均管理費","降價數"],
               rows, ["",N,N,N,N,N,N])
    chart = _bar([s["seg"] for s in segs], [s["cnt"] for s in segs], color="#0d9488", lw=120)
    return (f'<div class="s"><h2>三、新屋 vs 舊屋</h2>{tbl}'
            f'<div class="cb">{chart}</div></div>')


def _drill_type_direction_layout(d, zc):
    """類型 + 座向 + 格局。"""
    parts = []
    # 類型
    td = d.zip_type_dist(zc)
    if td:
        donut = _donut([(x["type"],x["cnt"]) for x in td[:10]])
        rows = [[escape(x["type"]),_f(x["cnt"]),_f(x["ap"]),_f(x["aup"],1)] for x in td[:12]]
        tbl = _tbl(["物件類型","數量","均總價(萬)","均單價(萬/坪)"],rows,["","n","n","n"])
        parts.append(f'<div class="two-col"><div class="cb">{donut}</div><div>{tbl}</div></div>')
    # 座向
    dirs = d.zip_direction(zc)
    if dirs:
        rows = [[escape(x["dir"]),_f(x["cnt"]),_f(x["avg_up"],1),_f(x["avg_price"])] for x in dirs]
        parts.append(f'<h3>座向 × 均單價</h3>{_tbl(["座向","物件數","均單價(萬/坪)","均總價(萬)"],rows,["","n","n","n"])}')
    # 格局
    lo = d.zip_layout(zc)
    if lo:
        rows = [[f'{x["rooms"]}房',_f(x["cnt"]),_f(x["avg_price"]),_f(x["avg_up"],1),_f(x["avg_area"],1)] for x in lo]
        parts.append(f'<h3>房數 × 均價</h3>{_tbl(["格局","物件數","均總價(萬)","均單價(萬/坪)","均坪數"],rows,["","n","n","n","n"])}')
    if not parts: return ""
    return f'<div class="s"><h2>四、類型 / 座向 / 格局</h2>{"".join(parts)}</div>'


def _drill_stores(d, zc):
    """門市經營 & 庫存分析（管理重點）— 全部門市。"""
    inv = d.zip_store_inventory(zc, top=9999)
    if not inv: return ""
    N = "n"

    # 庫存總覽表
    rows = []
    for s in inv:
        rows.append([
            escape((s["store"] or "–")[:20]), _f(s["cnt"]),
            _f(s["avg_price"]), _f(s["avg_up"],1), _f(s["avg_age"],1),
            _f(s["avg_area"],1), _f(s["avg_fee"]),
            f'{s["new_cnt"] or 0}', f'{s["mid_cnt"] or 0}', f'{s["old_cnt"] or 0}',
            f'{s["disc_pct"] or 0:.1f}%', _f(s["avg_w"]),
        ])
    tbl = _tbl(["門市","委售數","均總價","均單價","均屋齡","均坪數","均管理費",
                "新屋≤5y","中屋5-15y","舊屋>15y","降價率","均關注"],
               rows, ["",N,N,N,N,N,N,N,N,N,N,N])

    # 門市 × 物件類型明細（全部門市）
    type_bd = d.store_type_breakdown(zc)
    type_detail = ""
    for s in inv:
        store = s["store"]
        types = type_bd.get(store, {})
        if types:
            items = sorted(types.items(), key=lambda x: x[1], reverse=True)
            tags_html = " ".join(f'<span style="background:#e2e8f0;padding:2px 8px;'
                                 f'border-radius:4px;font-size:.8rem;margin:2px;">'
                                 f'{escape(t)} {c}</span>' for t, c in items[:6])
            type_detail += (f'<tr><td>{escape(store[:20])}</td>'
                           f'<td>{tags_html}</td></tr>')
    if type_detail:
        type_detail = (f'<h3>門市 × 物件類型庫存</h3>'
                      f'<table><thead><tr><th>門市</th><th>物件類型分佈</th></tr></thead>'
                      f'<tbody>{type_detail}</tbody></table>')

    return (f'<div class="s"><h2>五、門市經營 & 庫存分析</h2>{tbl}'
            f'{type_detail}</div>')


def _drill_tags(d, zc):
    """標籤分析。"""
    tags = d.tag_pop(city=None, top=20)
    # 用 zip 過濾
    where = f"WHERE tags IS NOT NULL AND {ACTIVE} AND zip_code=?"
    rows_raw = d.conn.execute(f"SELECT tags FROM houses {where}", [zc]).fetchall()
    c = Counter()
    for (t,) in rows_raw:
        try:
            for tag in json.loads(t): c[tag] += 1
        except: pass
    tags = c.most_common(20)
    if not tags: return ""
    chart = _bar([t[0] for t in tags], [t[1] for t in tags], color="#7c3aed")
    return f'<div class="s"><h2>六、標籤熱度</h2><div class="cb">{chart}</div></div>'


def _drill_listing_days(d, zc):
    """上架天數分析。"""
    data = d.listing_days_analysis(zc)
    if not data or not data.get("total"):
        return ""
    N = "n"
    segs = data["seg_order"]
    total_bk = data["total_bk"]
    res_bk = data["res_bk"]
    com_bk = data["com_bk"]
    total = data["total"]

    # 分段表（合計欄可點擊展開物件清單）
    seg_items = data.get("seg_items", {})
    tbl_rows = []
    cum = 0
    for seg in segs:
        t = total_bk[seg]; r = res_bk[seg]; c = com_bk[seg]
        pct = t / total * 100 if total else 0
        cum += pct
        seg_id = seg.replace("+","p").replace("-","_").replace("天","d").replace("月","m").replace("年","y").replace("內","n")
        link = f'<a href="#seg_{seg_id}" style="color:#2563eb;text-decoration:underline;cursor:pointer;" onclick="document.getElementById(\'seg_{seg_id}\').open=true">{_f(t)}</a>'
        tbl_rows.append([seg, _f(r), _f(c), link, f"{pct:.1f}%", f"{cum:.1f}%"])
    tbl = _tbl(["上架天數", "住宅", "商用/其他", "合計", "佔比", "累計佔比"], tbl_rows, ["", N, N, N, N, N])

    # 100% stacked bar — 各天數區段佔比
    seg_colors = ["#16a34a","#2563eb","#0891b2","#d97706","#ea580c","#dc2626"]
    vals = [total_bk[s] for s in segs]
    chart = _pct_stacked_bar(segs, vals, seg_colors, total)

    # 各區段物件清單（可展開）
    seg_lists = ""
    for seg in segs:
        items = seg_items.get(seg, [])
        if not items: continue
        seg_id = seg.replace("+","p").replace("-","_").replace("天","d").replace("月","m").replace("年","y").replace("內","n")
        item_rows = []
        for s in items[:50]:  # 每段最多 50 筆
            hno = s.get("id") or ""
            name = s.get("name") or hno or "–"
            link = f'<a href="https://www.sinyi.com.tw/buy/house/{hno}" target="_blank">{escape(name)}</a>' if hno else escape(name)
            disc = f'{s["discount_pct"]:.1f}%' if s.get("discount_pct") and s["discount_pct"] > 0 else "–"
            item_rows.append([link, _f(s.get("days")), _f(s.get("price")),
                              _f(s.get("unit_price"), 1), disc,
                              escape((s.get("agent_store") or "–")[:15])])
        items_tbl = _tbl(["物件", "天數", "總價(萬)", "單價", "降幅", "門市"],
                         item_rows, ["", N, N, N, N, ""])
        seg_lists += (f'<details id="seg_{seg_id}" style="margin:6px 0;">'
                      f'<summary>{escape(seg)} — {len(items)} 筆</summary>'
                      f'{items_tbl}</details>')

    # 滯銷物件（>180天）分住宅/商用
    stale_html = ""
    hdrs = ["物件", "天數", "總價(萬)", "單價", "降幅", "門市"]
    cls = ["", N, N, N, N, ""]
    def _stale_rows(items):
        rows = []
        for s in items:
            disc = f'{s["discount_pct"]:.1f}%' if s["discount_pct"] and s["discount_pct"] > 0 else "–"
            hno = s.get("id") or ""
            name = s.get("name") or hno or "–"
            if hno:
                link = f'<a href="https://www.sinyi.com.tw/buy/house/{hno}" target="_blank">{escape(name)}</a>'
            else:
                link = escape(name)
            rows.append([link, _f(s["days"]),
                         _f(s["price"]), _f(s["unit_price"], 1),
                         disc, escape((s["agent_store"] or "–")[:15])])
        return rows
    stale_res = data.get("stale_res", [])
    stale_com = data.get("stale_com", [])
    if stale_res:
        stale_html += f'<h3>滯銷住宅（上架超過 180 天）— {len(stale_res)} 筆</h3>'
        stale_html += _tbl(hdrs, _stale_rows(stale_res), cls)
    if stale_com:
        stale_html += f'<h3>滯銷商用/其他（上架超過 180 天）— {len(stale_com)} 筆</h3>'
        stale_html += _tbl(hdrs, _stale_rows(stale_com), cls)

    avg_days = data["avg_days"]
    return (f'<div class="s"><h2>七、上架天數分析</h2>'
            f'<p style="margin:8px 0;font-size:.9rem;">平均上架 <b>{avg_days:.0f} 天</b>，'
            f'共 {total} 筆有上架日期。點擊合計數字可展開物件清單。</p>'
            f'<div class="two-col"><div>{tbl}</div><div class="cb">{chart}</div></div>'
            f'{seg_lists}'
            f'{stale_html}</div>')


def _drill_res_vs_comm(d, zc):
    """住宅 vs 商用分離分析。"""
    rvc = d.residential_vs_commercial(zc)
    res = rvc.get("住宅", {})
    com = rvc.get("商用", {})
    if not res.get("cnt") and not com.get("cnt"):
        return ""
    N = "n"

    # 對比表
    metrics = [
        ("物件數", _f(res.get("cnt")), _f(com.get("cnt"))),
        ("均總價(萬)", _f(res.get("avg_price")), _f(com.get("avg_price"))),
        ("均單價(萬/坪)", _f(res.get("avg_up"), 1), _f(com.get("avg_up"), 1)),
        ("均屋齡(年)", _f(res.get("avg_age"), 1), _f(com.get("avg_age"), 1)),
        ("均坪數", _f(res.get("avg_area"), 1), _f(com.get("avg_area"), 1)),
        ("均管理費(元)", _f(res.get("avg_fee")), _f(com.get("avg_fee"))),
        ("均關注", _f(res.get("avg_w")), _f(com.get("avg_w"))),
        ("降價物件", _f(res.get("disc")), _f(com.get("disc"))),
    ]
    rows = [[m[0], m[1], m[2]] for m in metrics]
    tbl = _tbl(["指標", "住宅", "商用"], rows, ["", N, N])

    # 住宅路街
    res_st = d.residential_streets(zc)
    res_st_html = ""
    if res_st:
        st_rows = [[escape(s["street"]), _f(s["cnt"]), _f(s["avg_price"]),
                     _f(s["avg_up"], 1), _f(s["avg_age"], 1), _f(s["avg_w"])]
                    for s in res_st[:15]]
        res_st_html = (f'<h3>住宅 — 路街分析</h3>'
                      + _tbl(["路街", "物件數", "均總價(萬)", "均單價(萬/坪)", "均屋齡", "均關注"],
                             st_rows, ["", N, N, N, N, N]))

    # 商用路街
    com_st = d.commercial_streets(zc)
    com_st_html = ""
    if com_st:
        st_rows = [[escape(s["street"]), _f(s["cnt"]), _f(s["avg_price"]),
                     _f(s["avg_up"], 1), _f(s["avg_age"], 1), _f(s["avg_w"])]
                    for s in com_st[:15]]
        com_st_html = (f'<h3>商用 — 路街分析</h3>'
                      + _tbl(["路街", "物件數", "均總價(萬)", "均單價(萬/坪)", "均屋齡", "均關注"],
                             st_rows, ["", N, N, N, N, N]))

    return (f'<div class="s"><h2>八、住宅 vs 商用分離分析</h2>'
            f'{tbl}{res_st_html}{com_st_html}</div>')


def _drill_listing(d, zc):
    """物件清單。"""
    items = d.zip_listing_table(zc, limit=100)
    if not items: return ""
    N = "n"
    rows = []
    for it in items:
        disc = f'{it["discount_pct"]:.1f}%' if it["discount_pct"] and it["discount_pct"] > 0 else "–"
        fl = f'{it["floor"] or "–"}/{it["total_floor"] or "–"}F'
        link = f'<a href="{it["detail_url"]}" target="_blank">{escape(it["name"] or it["id"])}</a>' if it.get("detail_url") else escape(it["name"] or it["id"])
        rows.append([link, _f(it["price"]), _f(it["unit_price"],1),
                     it["layout"] or "–", _f(it["building_area"],1), fl,
                     _f(it["age"],1), it["building_front"] or "–",
                     _f(it["monthly_fee"]),
                     disc, _f(it["watchers"]),
                     escape(it["community"] or "–"),
                     escape((it["agent_store"] or "–")[:12])])
    tbl = _tbl(["物件","總價(萬)","單價","格局","坪數","樓層","屋齡","座向",
                "管理費","降幅","關注","社區","門市"],
               rows, ["",N,N,"",N,"",N,"",N,N,N,"",""])
    return f'<div class="s"><h2>七、物件清單（Top 100 關注度）</h2>{tbl}</div>'


# ══════════════════════════════════════════════════════════════════════
#  熱力地圖
# ══════════════════════════════════════════════════════════════════════

LEAFLET_CSS = "https://unpkg.com/leaflet@1.9/dist/leaflet.css"
LEAFLET_JS = "https://unpkg.com/leaflet@1.9/dist/leaflet.js"
HEAT_JS = "https://unpkg.com/leaflet.heat@0.2/dist/leaflet-heat.js"


def _drill_heatmap(d, zc):
    """物件座標熱力地圖（純區域熱度，無 POI marker）。"""
    rows = d.conn.execute(f"""
        SELECT latitude, longitude, price
        FROM houses WHERE {ACTIVE} AND zip_code=?
        AND latitude IS NOT NULL AND latitude!=0""", [zc]).fetchall()
    if not rows:
        return ""

    lats = [r["latitude"] for r in rows]
    lngs = [r["longitude"] for r in rows]
    center_lat = sum(lats) / len(lats)
    center_lng = sum(lngs) / len(lngs)

    prices = [r["price"] or 0 for r in rows]
    max_p = max(prices) if prices else 1

    heat_points = ",".join(
        f'[{r["latitude"]},{r["longitude"]},{(r["price"] or 0)/max_p:.3f}]'
        for r in rows
    )

    return f'''
    <div class="s">
      <h2>八、物件熱力地圖</h2>
      <p style="font-size:.85rem;color:#6b7280;margin-bottom:8px;">
        顏色越深紅 = 該區域委售物件總價越高、密度越集中。
      </p>
      <link rel="stylesheet" href="{LEAFLET_CSS}"/>
      <div id="heatmap" style="height:520px;border-radius:12px;overflow:hidden;
           box-shadow:0 2px 8px rgba(0,0,0,.1);"></div>
      <script src="{LEAFLET_JS}"></script>
      <script src="{HEAT_JS}"></script>
      <script>
        var map = L.map('heatmap').setView([{center_lat},{center_lng}], 14);
        L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_nolabels/{{z}}/{{x}}/{{y}}@2x.png', {{
          attribution: '&copy; CartoDB', maxZoom: 19
        }}).addTo(map);
        L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_only_labels/{{z}}/{{x}}/{{y}}@2x.png', {{
          maxZoom: 19, pane: 'overlayPane'
        }}).addTo(map);
        L.heatLayer([{heat_points}], {{
          radius: 35, blur: 20, maxZoom: 17, max: 0.5, minOpacity: 0.35,
          gradient: {{0.0:'rgba(0,0,255,0)',0.15:'#0000ff',0.3:'#00ffff',
                     0.45:'#00ff00',0.6:'#ffff00',0.75:'#ff8800',
                     0.9:'#ff0000',1.0:'#cc0000'}}
        }}).addTo(map);
      </script>
    </div>'''


# ══════════════════════════════════════════════════════════════════════
#  AI 分析引擎（規則式自動洞察）
# ══════════════════════════════════════════════════════════════════════

def _drill_ai_analysis(d, zc):
    """自動產生市場洞察 + 弱點分析。"""
    insights = []   # (icon, title, content)
    warnings = []   # (icon, title, content)

    # ── 資料收集 ──
    streets = d.street_analysis(zc)
    comms = d.community_analysis(zc)
    segs = d.age_segment_analysis(zc)
    stores = d.zip_store_inventory(zc, top=9999)
    dirs = d.zip_direction(zc)
    layouts = d.zip_layout(zc)

    kpi_row = d.conn.execute(f"""
        SELECT COUNT(*) total, ROUND(AVG(price),0) ap, ROUND(AVG(unit_price),1) aup,
            ROUND(AVG(age),1) aa, ROUND(AVG(building_area),1) aarea,
            SUM(CASE WHEN discount_pct>0 THEN 1 ELSE 0 END) disc,
            ROUND(AVG(discount_pct),2) avg_disc_all,
            ROUND(AVG(CASE WHEN discount_pct>0 THEN discount_pct END),2) avg_disc_pos
        FROM houses WHERE {ACTIVE} AND zip_code=?""", [zc]).fetchone()
    total = kpi_row["total"]
    if total == 0:
        return ""

    # ── 1. 市場概況 ──
    disc_rate = (kpi_row["disc"] or 0) / total * 100
    insights.append(("📊", "市場規模",
        f'本區共 <b>{total}</b> 筆委售物件，'
        f'平均總價 <b>{_f(kpi_row["ap"])} 萬</b>，'
        f'平均單價 <b>{_f(kpi_row["aup"],1)} 萬/坪</b>，'
        f'平均屋齡 <b>{_f(kpi_row["aa"],1)} 年</b>。'))

    # ── 2. 降價趨勢 ──
    if disc_rate > 10:
        warnings.append(("⚠️", "降價壓力偏高",
            f'降價物件佔 <b>{disc_rate:.1f}%</b>（{kpi_row["disc"]}/{total}），'
            f'平均降幅 <b>{kpi_row["avg_disc_pos"] or 0:.2f}%</b>。'
            f'建議關注長期未成交且持續降價的物件。'))
    elif disc_rate > 5:
        insights.append(("📉", "降價情況",
            f'降價物件佔 <b>{disc_rate:.1f}%</b>，降幅 <b>{kpi_row["avg_disc_pos"] or 0:.2f}%</b>，屬正常範圍。'))
    else:
        insights.append(("✅", "價格穩定",
            f'降價物件僅 <b>{disc_rate:.1f}%</b>，市場價格穩定。'))

    # ── 3. 新舊屋結構 ──
    if segs:
        seg_map = {s["seg"]: s for s in segs}
        new_cnt = sum(s["cnt"] for s in segs if "預售" in s["seg"] or "5年內" in s["seg"])
        old_cnt = sum(s["cnt"] for s in segs if "30" in s["seg"])
        new_pct = new_cnt / total * 100
        old_pct = old_cnt / total * 100
        insights.append(("🏗️", "新舊屋結構",
            f'新屋（≤5年）佔 <b>{new_pct:.1f}%</b>（{new_cnt} 筆），'
            f'老屋（>30年）佔 <b>{old_pct:.1f}%</b>（{old_cnt} 筆）。'))
        if old_pct > 30:
            warnings.append(("🏚️", "老屋比例偏高",
                f'30年以上老屋佔 <b>{old_pct:.1f}%</b>，可能影響區域形象與成交速度。'
                f'建議加強老屋換屋需求的行銷。'))

    # ── 4. 熱門路街 vs 冷門路街 ──
    if streets:
        hot_st = sorted(streets, key=lambda x: x["avg_w"] or 0, reverse=True)
        cold_st = sorted(streets, key=lambda x: x["avg_w"] or 0)
        top3 = [s["street"] for s in hot_st[:3]]
        bot3 = [s["street"] for s in cold_st[:3] if s["avg_w"] and s["cnt"] >= 3]
        insights.append(("🔥", "熱門路街",
            f'關注度最高：<b>{", ".join(top3)}</b>。'))
        if bot3:
            warnings.append(("❄️", "低關注路街",
                f'<b>{", ".join(bot3)}</b> 關注度偏低，'
                f'建議評估是否需加強曝光或調整定價策略。'))

    # ── 5. 單價異常 ──
    if streets:
        priced = [s for s in streets if s["avg_up"] and s["cnt"] >= 3]
        if priced:
            avg_all = kpi_row["aup"] or 0
            high_st = [s for s in priced if s["avg_up"] > avg_all * 1.3]
            low_st = [s for s in priced if s["avg_up"] < avg_all * 0.7]
            if high_st:
                names = ", ".join(s["street"] for s in high_st[:3])
                insights.append(("💎", "高單價路段",
                    f'<b>{names}</b> 單價高於區均 30% 以上，屬精華地段。'))
            if low_st:
                names = ", ".join(s["street"] for s in low_st[:3])
                warnings.append(("💡", "低單價路段",
                    f'<b>{names}</b> 單價低於區均 30% 以上，'
                    f'可能為投資機會或需注意物件品質。'))

    # ── 6. 座向偏好 ──
    if dirs and len(dirs) >= 2:
        best = dirs[0]
        insights.append(("🧭", "座向分佈",
            f'最多物件座向為 <b>{best["dir"]}</b>（{best["cnt"]} 筆），'
            f'均單價 <b>{_f(best["avg_up"],1)} 萬/坪</b>。'))

    # ── 7. 門市經營弱點 ──
    if stores:
        # 高庫存但高降價率的門市
        problem_stores = [s for s in stores
                         if s["cnt"] >= 5 and (s["disc_pct"] or 0) > 15]
        if problem_stores:
            names = ", ".join(s["store"][:10] for s in problem_stores[:3])
            warnings.append(("🏪", "門市庫存警示",
                f'<b>{names}</b> 等門市降價率超過 15%（庫存≥5筆），'
                f'建議檢視定價策略或加強銷售力道。'))

        # 只有 1 筆的門市（跨區經營）
        cross_stores = [s for s in stores if s["cnt"] == 1]
        if len(cross_stores) > len(stores) * 0.3:
            warnings.append(("📍", "跨區門市比例高",
                f'{len(cross_stores)}/{len(stores)} 家門市僅委售 1 筆，'
                f'跨區經營比例 <b>{len(cross_stores)/len(stores)*100:.0f}%</b>，'
                f'建議評估在地深耕策略。'))

    # ── 8. 格局需求 ──
    if layouts:
        main_layout = max(layouts, key=lambda x: x["cnt"])
        insights.append(("🛏️", "主力格局",
            f'<b>{main_layout["rooms"]}房</b> 為主力（{main_layout["cnt"]} 筆，'
            f'均總價 {_f(main_layout["avg_price"])} 萬）。'))

    # ── 渲染 ──
    html = '<div class="s"><h2>九、AI 市場分析 & 弱點診斷</h2>'

    if insights:
        html += '<h3>市場洞察</h3><div style="display:grid;gap:12px;margin:12px 0;">'
        for icon, title, content in insights:
            html += (f'<div style="background:#f0f9ff;border-left:4px solid #2563eb;'
                     f'padding:14px 18px;border-radius:8px;">'
                     f'<b>{icon} {title}</b><br>{content}</div>')
        html += '</div>'

    if warnings:
        html += '<h3>弱點 & 風險提醒</h3><div style="display:grid;gap:12px;margin:12px 0;">'
        for icon, title, content in warnings:
            html += (f'<div style="background:#fef2f2;border-left:4px solid #dc2626;'
                     f'padding:14px 18px;border-radius:8px;">'
                     f'<b>{icon} {title}</b><br>{content}</div>')
        html += '</div>'

    html += '</div>'
    return html


def render_drill_report(db_path, output_path, zc):
    """產生單一行政區 drill-down 報表。"""
    d = RD(db_path)
    dn_name = d.dn(zc)
    html = (f'<!DOCTYPE html><html lang="zh-TW"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1.0">'
            f'<title>{escape(dn_name)} 外網產品深度分析報表</title><style>{CSS}</style></head><body>'
            f'{_drill_header(d,db_path,zc)}{_drill_kpi(d,zc)}'
            f'{_drill_res_vs_comm(d,zc)}'                  # 住宅 vs 商用
            f'{_drill_streets(d,zc)}{_drill_communities(d,zc)}'
            f'{_drill_age_segment(d,zc)}{_drill_type_direction_layout(d,zc)}'
            f'{_drill_stores(d,zc)}{_drill_tags(d,zc)}'
            f'{_drill_listing_days(d,zc)}'                  # 上架天數
            f'{_drill_listing(d,zc)}'
            f'{_drill_heatmap(d,zc)}'
            f'{_drill_ai_analysis(d,zc)}'
            f'{_footer()}<script>{JS}</script></body></html>')
    Path(output_path).write_text(html, encoding="utf-8")
    d.close()
    print(f"報表已產生: {output_path}")


# ══════════════════════════════════════════════════════════════════════
#  組裝 & CLI
# ══════════════════════════════════════════════════════════════════════

def render_report(db_path, output_path, cities=None, top_n=20):
    d=RD(db_path, cities)
    html=(f'<!DOCTYPE html><html lang="zh-TW"><head><meta charset="UTF-8">'
          f'<meta name="viewport" content="width=device-width,initial-scale=1.0">'
          f'<title>房屋市場分析報表</title><style>{CSS}</style></head><body>'
          f'{_header(d,db_path)}{_kpi(d)}'
          f'{_sec1(d)}{_sec2(d)}{_sec3(d)}{_sec4(d)}'
          f'{_sec5_detail(d)}{_sec6_tags(d,top_n)}'
          f'{_footer()}<script>{JS}</script></body></html>')
    Path(output_path).write_text(html, encoding="utf-8")
    d.close()
    print(f"報表已產生: {output_path}")

def _find_latest_db(data_dir="data"):
    p=Path(data_dir)
    if not p.is_dir(): return None
    dbs=sorted(p.glob("*.db"),reverse=True)
    return str(dbs[0]) if dbs else None

def main():
    parser=argparse.ArgumentParser(description="產生房屋市場分析報表（含交叉分析）")
    parser.add_argument("--db",default=None,help="SQLite 路徑")
    parser.add_argument("--output",default=None,help="輸出 HTML")
    parser.add_argument("--cities",nargs="*",default=None,help="指定城市")
    parser.add_argument("--zip",default=None,help="行政區 drill-down（如 114=內湖區）")
    parser.add_argument("--top",type=int,default=20,help="排名 Top N")
    args=parser.parse_args()
    db_path=args.db or _find_latest_db()
    if not db_path or not Path(db_path).exists():
        print("錯誤: 找不到 DB"); return

    if args.zip:
        output = args.output or f"report_{args.zip}_{datetime.now().strftime('%Y%m%d')}.html"
        print(f"資料庫: {db_path} ｜ drill-down: zip={args.zip}")
        render_drill_report(db_path, output, args.zip)
    else:
        output = args.output or f"report_{datetime.now().strftime('%Y%m%d')}.html"
        print(f"資料庫: {db_path}")
        render_report(db_path, output, args.cities, args.top)

if __name__=="__main__":
    main()
