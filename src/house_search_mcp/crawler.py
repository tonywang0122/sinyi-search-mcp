"""全地理區物件爬取工具 — 搜尋列表 + 物件明細，完整存入 SQLite。

預設行為：對每筆物件呼叫 getObjectContent + getObjectDetail 取得所有欄位。
若只需搜尋列表（快速模式），加 --list-only。

用法：
    python -m house_search_mcp.crawler                          # 互動選城市，含 detail
    python -m house_search_mcp.crawler --cities Taipei           # 指定城市
    python -m house_search_mcp.crawler --list-only               # 只抓搜尋列表（快速）
    python -m house_search_mcp.crawler --enrich data/20260331.db # 對已有 DB 補抓 detail
"""

import argparse
import math
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import json as _json

from . import api

# ── 常數 ──────────────────────────────────────────────────────────────

PAGE_SIZE = 100
REQUEST_DELAY = 0.3
DETAIL_DELAY = 0.2       # detail 請求間隔（秒）
CONCURRENCY = 3           # detail 並行 worker 數
SESSION_REFRESH = 500

# ── 城市中文對照 ──────────────────────────────────────────────────────

CITY_LABEL = {
    "Taipei": "台北市", "NewTaipei": "新北市", "Keelung": "基隆市",
    "Yilan": "宜蘭縣", "Hsinchu": "新竹市", "Hsinchu-county": "新竹縣",
    "Taoyuan": "桃園市", "Miaoli": "苗栗縣", "Taichung": "台中市",
    "Changhua": "彰化縣", "Nantou": "南投縣", "Yunlin": "雲林縣",
    "Chiayi": "嘉義市", "Chiayi-county": "嘉義縣", "Tainan": "台南市",
    "Kaohsiung": "高雄市", "Pingtung": "屏東縣", "Taitung": "台東縣",
    "Hualien": "花蓮縣", "Penghu": "澎湖縣", "Kinmen": "金門縣",
    "Lienchiang": "連江縣",
}

# ── SQLite schema ─────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS houses (
    -- ═══ 搜尋列表欄位（filterObject API）═══
    -- 識別
    id              TEXT PRIMARY KEY,   -- 物件編號 (houseNo)
    object_id       TEXT,               -- 物件內部 ID
    object_type     TEXT,               -- 物件類型碼
    kind            TEXT,               -- 物件種類
    status          TEXT,               -- 物件狀態
    is_off          INTEGER,            -- 是否已下架 (0/1)
    -- 名稱 / 位置
    name            TEXT,               -- 物件名稱
    address         TEXT,               -- 地址
    city            TEXT,               -- 城市代碼 (CITY_MAP key)
    zip_code        TEXT,               -- 行政區郵遞區號
    community_id    TEXT,               -- 社區 ID
    community       TEXT,               -- 社區名稱
    latitude        REAL,               -- 緯度
    longitude       REAL,               -- 經度
    -- 類型
    type            TEXT,               -- 物件型態（中文，JSON array）
    type_raw        TEXT,               -- 物件型態（原始代碼，JSON array）
    type_show       TEXT,               -- 物件型態（顯示用文字）
    -- 價格
    price           REAL,               -- 總價（萬元）
    price_original  REAL,               -- 原始開價（萬元）
    discount_pct    REAL,               -- 降價幅度（%）
    unit_price      REAL,               -- 單價（萬/坪）— 列表 API 不回傳，由 detail 補
    -- 格局 / 樓層
    layout          TEXT,               -- 格局（如 3房2廳2衛）
    add_layout      TEXT,               -- 加蓋格局
    floor           TEXT,               -- 所在樓層
    total_floor     TEXT,               -- 總樓層數
    age             REAL,               -- 屋齡（年）
    -- 面積
    building_area   REAL,               -- 建物面積（坪）
    main_area       REAL,               -- 主建物面積（坪）
    land_area       REAL,               -- 土地面積（坪）
    -- 特徵旗標
    has_parking     INTEGER,            -- 是否有車位 (0/1)
    parking         TEXT,               -- 車位資訊
    has_balcony     INTEGER,            -- 是否有陽台 (0/1)
    has_view        INTEGER,            -- 是否有景觀 (0/1)
    has_video       INTEGER,            -- 是否有影片 (0/1)
    has_3dvr        INTEGER,            -- 是否有 3D VR (0/1)
    vr_3d           TEXT,               -- 3D VR 資訊
    is_similar      INTEGER,            -- 是否為相似物件 (0/1)
    -- 圖片
    image           TEXT,               -- 首圖 URL
    large_image     TEXT,               -- 大圖 URL
    image_tag       TEXT,               -- 圖片標籤
    -- 標籤
    tags            TEXT,               -- 標籤（中文，JSON array）
    tags_raw        TEXT,               -- 標籤（原始 ID，JSON array）
    -- 統計 / 其他
    watchers        INTEGER,            -- 近三月關注人數
    manager_id      TEXT,               -- 管理者 ID
    group_company   TEXT,               -- 集團公司
    -- 連結
    detail_url      TEXT,               -- 物件明細頁 URL
    share_url       TEXT,               -- 分享連結

    -- ═══ 明細欄位（getObjectContent API）═══
    city_name       TEXT,               -- 城市名稱（中文）
    district        TEXT,               -- 行政區名稱（中文）
    land_unit_price REAL,               -- 土地單價（萬/坪）
    -- 格局細項
    roomplus        INTEGER,            -- 房數
    hallplus        INTEGER,            -- 廳數
    bathroomplus    INTEGER,            -- 衛浴數
    openroomplus    INTEGER,            -- 開放式房間數
    -- 面積細項
    area_detail     TEXT,               -- 面積明細（JSON array）
    house_size      TEXT,               -- 房屋大小分類（JSON）
    -- 座向
    house_front     TEXT,               -- 房屋座向
    building_front  TEXT,               -- 大樓座向
    window_front    TEXT,               -- 窗戶座向
    direction_land  TEXT,               -- 土地座向
    -- 特徵
    is_side_unit    INTEGER,            -- 是否為邊間 (0/1)
    has_darkroom    INTEGER,            -- 是否有暗房 (0/1)
    management      TEXT,               -- 管理方式
    monthly_fee     REAL,               -- 月管理費（元）
    -- 媒體
    images          TEXT,               -- 物件照片 URL 列表（JSON array）
    layout_image    TEXT,               -- 格局圖 URL
    layout_image_3d TEXT,               -- 3D 格局圖 URL
    map_image       TEXT,               -- 地圖圖片 URL
    vr_type         TEXT,               -- VR 類型
    vr_url          TEXT,               -- VR 看屋連結
    vr_demo_url     TEXT,               -- VR 體驗連結
    vr_image        TEXT,               -- VR 預覽圖 URL
    ai_tour         TEXT,               -- AI 導覽旗標
    ai_tour_url     TEXT,               -- AI 導覽連結
    video_url       TEXT,               -- 影片 URL
    -- 經紀人
    agent_id        TEXT,               -- 主要經紀人 ID
    agent_name      TEXT,               -- 主要經紀人姓名
    agent_store     TEXT,               -- 主要經紀人門市
    agent_store_id  TEXT,               -- 門市 ID
    agent_tel       TEXT,               -- 經紀人電話
    agent2_id       TEXT,               -- 次要經紀人 ID
    agent2_name     TEXT,               -- 次要經紀人姓名
    -- 統計
    first_listed    TEXT,               -- 首次上架日期
    is_same_trade   INTEGER,            -- 是否同業物件

    -- ═══ 明細欄位（getObjectDetail API）═══
    structure       TEXT,               -- 建築結構
    wall            TEXT,               -- 牆壁結構
    families_per_floor TEXT,            -- 每層戶數
    purpose         TEXT,               -- 用途
    zoning          TEXT,               -- 使用分區
    detail_other    TEXT,               -- 其他說明
    detail_notice   TEXT,               -- 注意事項
    description     TEXT,               -- 經紀人賣點（JSON array）
    -- 標籤（detail 版，較完整）
    house_spec_tags TEXT,               -- 房屋規格標籤（JSON）
    house_facility_tags TEXT,           -- 設施標籤（JSON）
    house_life_tags TEXT,               -- 生活機能標籤（JSON）
    house_feature_tags TEXT,            -- 特色標籤（JSON）
    -- 語音導覽
    audio_count     INTEGER,            -- 語音導覽數量
    -- 生活圈
    nearby          TEXT,               -- 周邊生活圈（整理後，JSON）
    life_info_raw   TEXT,               -- 周邊生活圈（原始，JSON）

    -- ═══ 中繼資料 ═══
    has_detail      INTEGER DEFAULT 0,  -- 是否已抓取 detail (0/1)
    crawled_at      TEXT,               -- 爬取時間 (ISO 8601)
    detail_at       TEXT                -- detail 抓取時間 (ISO 8601)
);
"""

CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_city       ON houses (city);",
    "CREATE INDEX IF NOT EXISTS idx_zip_code   ON houses (zip_code);",
    "CREATE INDEX IF NOT EXISTS idx_price      ON houses (price);",
    "CREATE INDEX IF NOT EXISTS idx_unit_price ON houses (unit_price);",
    "CREATE INDEX IF NOT EXISTS idx_age        ON houses (age);",
    "CREATE INDEX IF NOT EXISTS idx_type_show  ON houses (type_show);",
    "CREATE INDEX IF NOT EXISTS idx_has_detail ON houses (has_detail);",
]

CREATE_STATS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS crawl_stats (
    city            TEXT PRIMARY KEY,
    total_count     INTEGER,
    fetched_count   INTEGER,
    newin_cnt       INTEGER,
    newprice_cnt    INTEGER,
    hot_cnt         INTEGER,
    hot_deal_cnt    INTEGER,
    bestprice_cnt   INTEGER,
    crawled_at      TEXT
);
"""

# ── DB helpers ────────────────────────────────────────────────────────


def _init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute(CREATE_TABLE_SQL)
    conn.execute(CREATE_STATS_TABLE_SQL)
    # 先 migrate（補欄位），再建索引（索引可能參照新欄位）
    _migrate_columns(conn)
    for sql in CREATE_INDEX_SQL:
        conn.execute(sql)
    conn.commit()
    return conn


def _migrate_columns(conn: sqlite3.Connection):
    """若已有 DB 缺少新欄位，自動補上。"""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(houses)").fetchall()}
    new_cols = [
        ("city_name", "TEXT"), ("district", "TEXT"), ("land_unit_price", "REAL"),
        ("roomplus", "INTEGER"), ("hallplus", "INTEGER"), ("bathroomplus", "INTEGER"),
        ("openroomplus", "INTEGER"), ("area_detail", "TEXT"), ("house_size", "TEXT"),
        ("house_front", "TEXT"), ("building_front", "TEXT"), ("window_front", "TEXT"),
        ("direction_land", "TEXT"), ("is_side_unit", "INTEGER"), ("has_darkroom", "INTEGER"),
        ("management", "TEXT"), ("monthly_fee", "REAL"),
        ("images", "TEXT"), ("layout_image", "TEXT"), ("layout_image_3d", "TEXT"),
        ("map_image", "TEXT"), ("vr_type", "TEXT"), ("vr_url", "TEXT"),
        ("vr_demo_url", "TEXT"), ("vr_image", "TEXT"), ("ai_tour", "TEXT"),
        ("ai_tour_url", "TEXT"), ("video_url", "TEXT"),
        ("agent_id", "TEXT"), ("agent_name", "TEXT"), ("agent_store", "TEXT"),
        ("agent_store_id", "TEXT"), ("agent_tel", "TEXT"),
        ("agent2_id", "TEXT"), ("agent2_name", "TEXT"),
        ("first_listed", "TEXT"), ("is_same_trade", "INTEGER"),
        ("structure", "TEXT"), ("wall", "TEXT"), ("families_per_floor", "TEXT"),
        ("purpose", "TEXT"), ("zoning", "TEXT"), ("detail_other", "TEXT"),
        ("detail_notice", "TEXT"), ("description", "TEXT"),
        ("house_spec_tags", "TEXT"), ("house_facility_tags", "TEXT"),
        ("house_life_tags", "TEXT"), ("house_feature_tags", "TEXT"),
        ("audio_count", "INTEGER"), ("nearby", "TEXT"), ("life_info_raw", "TEXT"),
        ("has_detail", "INTEGER"), ("detail_at", "TEXT"),
    ]
    for col, typ in new_cols:
        if col not in existing:
            conn.execute(f"ALTER TABLE houses ADD COLUMN {col} {typ}")


def _to_int(v):
    if v is None: return None
    if isinstance(v, bool): return 1 if v else 0
    try: return int(v)
    except (ValueError, TypeError): return None


def _to_float(v):
    """安全轉 float，自動去除中文單位（如 '14.6年'、'99.67 萬/坪'）。"""
    if v is None: return None
    if isinstance(v, str):
        import re as _re
        # 去除中文單位和空白，只留數字和小數點
        cleaned = _re.sub(r'[^\d.\-]', '', v.strip())
        if not cleaned: return None
        v = cleaned
    try: return float(v)
    except (ValueError, TypeError): return None


def _val(v):
    if isinstance(v, (list, dict)):
        return _json.dumps(v, ensure_ascii=False)
    return v


# ── 搜尋列表寫入 ─────────────────────────────────────────────────────

def _insert_items(conn, items, city, now_iso):
    """批次寫入搜尋列表物件。"""
    rows = []
    for item in items:
        rows.append((
            item.get("id"), _val(item.get("object_id")), _val(item.get("object_type")),
            _val(item.get("kind")), _val(item.get("status")), _to_int(item.get("is_off")),
            _val(item.get("name")), _val(item.get("address")), city,
            _val(item.get("zip_code")), _val(item.get("community_id")),
            _val(item.get("community")), _to_float(item.get("latitude")),
            _to_float(item.get("longitude")),
            _val(item.get("type")), _val(item.get("type_raw")), _val(item.get("type_show")),
            _to_float(item.get("price")), _to_float(item.get("price_original")),
            _to_float(item.get("discount_pct")), _to_float(item.get("unit_price")),
            _val(item.get("layout")), _val(item.get("add_layout")),
            _val(item.get("floor")), _val(item.get("total_floor")),
            _to_float(item.get("age")),
            _to_float(item.get("building_area")), _to_float(item.get("main_area")),
            _to_float(item.get("land_area")),
            _to_int(item.get("has_parking")), _val(item.get("parking")),
            _to_int(item.get("has_balcony")), _to_int(item.get("has_view")),
            _to_int(item.get("has_video")), _to_int(item.get("has_3dvr")),
            _val(item.get("vr_3d")), _to_int(item.get("is_similar")),
            _val(item.get("image")), _val(item.get("large_image")),
            _val(item.get("image_tag")),
            _val(item.get("tags")), _val(item.get("tags_raw")),
            _to_int(item.get("watchers")), _val(item.get("manager_id")),
            _val(item.get("group_company")),
            _val(item.get("detail_url")), _val(item.get("share_url")),
            now_iso,
        ))
    conn.executemany("""INSERT OR REPLACE INTO houses (
        id, object_id, object_type, kind, status, is_off,
        name, address, city, zip_code, community_id, community, latitude, longitude,
        type, type_raw, type_show,
        price, price_original, discount_pct, unit_price,
        layout, add_layout, floor, total_floor, age,
        building_area, main_area, land_area,
        has_parking, parking, has_balcony, has_view, has_video, has_3dvr, vr_3d, is_similar,
        image, large_image, image_tag, tags, tags_raw,
        watchers, manager_id, group_company, detail_url, share_url, crawled_at
    ) VALUES (?,?,?,?,?,?, ?,?,?,?,?,?,?,?, ?,?,?, ?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?,?,?,?,?,?, ?,?,?, ?,?, ?,?,?, ?,?, ?)""", rows)


# ── Detail 寫入 ──────────────────────────────────────────────────────

def _update_detail(conn, house_no, content, detail_data, now_iso):
    """將 getObjectContent + getObjectDetail 的資料 UPDATE 到 houses 表。"""
    d = detail_data.get("detail") or {}
    agent = content.get("agent") or {}
    agent2 = content.get("agent2") or {}

    conn.execute("""UPDATE houses SET
        unit_price=?, land_unit_price=?,
        city_name=?, district=?,
        roomplus=?, hallplus=?, bathroomplus=?, openroomplus=?,
        area_detail=?, house_size=?,
        house_front=?, building_front=?, window_front=?, direction_land=?,
        is_side_unit=?, has_darkroom=?, management=?, monthly_fee=?,
        images=?, layout_image=?, layout_image_3d=?, map_image=?,
        vr_type=?, vr_url=?, vr_demo_url=?, vr_image=?,
        ai_tour=?, ai_tour_url=?, video_url=?,
        agent_id=?, agent_name=?, agent_store=?, agent_store_id=?, agent_tel=?,
        agent2_id=?, agent2_name=?,
        first_listed=?, is_same_trade=?,
        structure=?, wall=?, families_per_floor=?, purpose=?, zoning=?,
        detail_other=?, detail_notice=?,
        description=?,
        house_spec_tags=?, house_facility_tags=?, house_life_tags=?, house_feature_tags=?,
        audio_count=?,
        nearby=?, life_info_raw=?,
        has_detail=1, detail_at=?
    WHERE id=?""", (
        _to_float(content.get("uniPrice")),
        _to_float(content.get("landUniprice")),
        content.get("cityName"), content.get("zipName"),
        _to_int(content.get("roomplus")), _to_int(content.get("hallplus")),
        _to_int(content.get("bathroomplus")), _to_int(content.get("openroomplus")),
        _val(content.get("areaInfo")), _val(content.get("houseSize")),
        content.get("houseFront"), content.get("buildingFront"),
        content.get("windowFront"), content.get("directionland"),
        _to_int(content.get("sfside")), _to_int(content.get("sfdarkroom")),
        content.get("hasmanager"), _to_float(content.get("monthlyFee")),
        _val(content.get("images")), content.get("layoutImage"),
        content.get("layoutImage3D"), _val(content.get("map")),
        content.get("vrType"), content.get("vrUrl"),
        content.get("vrDemoUrl"), content.get("vrImgUrl"),
        _val(content.get("aiTour")), content.get("aiTourURL"),
        content.get("videoUrl"),
        agent.get("agentId"), agent.get("agentName"),
        agent.get("agentStore"), agent.get("agentStoreID"), agent.get("agentTel"),
        agent2.get("agentId"), agent2.get("agentName"),
        content.get("firstDisplay"), _to_int(content.get("isSameTrade")),
        d.get("buildingStructure"), d.get("wallStructure"),
        d.get("family"), d.get("purpose"), d.get("partition"),
        d.get("other"), d.get("notice"),
        _val(detail_data.get("description")),
        _val(detail_data.get("houseSpecTags")), _val(detail_data.get("houseFacilityTags")),
        _val(detail_data.get("houseLifeTags")), _val(detail_data.get("houseFeatureTags")),
        _to_int(detail_data.get("audioCount")),
        _val(api._extract_nearby(detail_data.get("lifeInfo") or [])),
        _val(detail_data.get("lifeInfo")),
        now_iso, house_no,
    ))


def _insert_stats(conn, city, total, fetched, data, now_iso):
    conn.execute("""INSERT OR REPLACE INTO crawl_stats
        (city, total_count, fetched_count, newin_cnt, newprice_cnt,
         hot_cnt, hot_deal_cnt, bestprice_cnt, crawled_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (city, total, fetched,
         data.get("newinCnt"), data.get("newpriceCnt"),
         data.get("hotCnt"), data.get("hotDealCnt"),
         data.get("bestpriceCnt"), now_iso))


# ── 爬取邏輯 ─────────────────────────────────────────────────────────

def crawl_zip(conn, sat, sid, zip_codes, city_hint, page_size, delay,
              request_count, with_detail=True, concurrency=CONCURRENCY):
    """爬取指定行政區（zip codes）。

    Args:
        zip_codes: 逗號分隔的 zip code 字串，如 "114" 或 "114,115"
        city_hint: 城市代碼，用於 DB 的 city 欄位
    Returns: (fetched, request_count, sat, sid)
    """
    now_iso = datetime.now().isoformat()
    filter_body = api.build_filter({"zip": zip_codes})
    return _crawl_with_filter(conn, sat, sid, filter_body, city_hint,
                              page_size, delay, request_count, with_detail,
                              now_iso, concurrency)


def crawl_city(conn, sat, sid, city, page_size, delay, request_count,
               with_detail=True, concurrency=CONCURRENCY):
    """爬取單一城市：搜尋列表 + (可選) 逐筆 detail。

    Returns: (fetched, request_count, sat, sid)
    """
    now_iso = datetime.now().isoformat()
    filter_body = api.build_filter({"city": city})
    return _crawl_with_filter(conn, sat, sid, filter_body, city,
                              page_size, delay, request_count, with_detail,
                              now_iso, concurrency)


def _crawl_with_filter(conn, sat, sid, filter_body, city_label,
                       page_size, delay, request_count, with_detail,
                       now_iso, concurrency=CONCURRENCY):
    """通用爬取邏輯（搜尋列表 + detail）。"""
    fetched = 0

    # 第一頁
    data = api.search(sat, sid, filter_body, 1, page_size, "0")
    request_count += 1
    total = data.get("totalCnt", 0)
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    if total == 0:
        return 0, request_count, sat, sid

    # 處理所有頁
    all_house_nos = []
    for page in range(1, total_pages + 1):
        if page > 1:
            time.sleep(delay)
            if request_count % SESSION_REFRESH == 0:
                sat, sid = api.get_session(); request_count += 2
            data = api.search(sat, sid, filter_body, page, page_size, "0")
            request_count += 1

        items = [api.format_item(o) for o in (data.get("object") or [])]
        if not items:
            break
        _insert_items(conn, items, city_label, now_iso)
        fetched += len(items)
        all_house_nos.extend(item["id"] for item in items if item.get("id"))
        conn.commit()

        if page == 1:
            _insert_stats(conn, city_label, total, fetched, data, now_iso)
        if page > 1:
            _insert_stats(conn, city_label, total, fetched, data, now_iso)
            pct = fetched / total * 100 if total > 0 else 0
            print(f"  列表: {page}/{total_pages} 頁, {fetched}/{total} 筆 ({pct:.0f}%)",
                  flush=True)

    # 抓 detail
    if with_detail and all_house_nos:
        print(f"  開始抓取 detail ({len(all_house_nos)} 筆)...")
        sat, sid, request_count = _fetch_details(
            conn, sat, sid, all_house_nos, delay, request_count, concurrency)

    return fetched, request_count, sat, sid


class _DetailWorker:
    """Detail 抓取 worker — 維持獨立 session，定期 refresh。"""

    def __init__(self, worker_id: int, delay: float):
        self.id = worker_id
        self.delay = delay
        self.sat, self.sid = api.get_session()
        self.req_count = 2  # get_session = 2 reqs
        self._call_count = 0

    def fetch(self, hno: str):
        """抓取單筆 detail。Returns: (hno, content, detail) or (hno, None, error)"""
        time.sleep(self.delay)
        self._call_count += 1

        # 每 200 次請求 refresh session
        if self._call_count % 200 == 0:
            try:
                self.sat, self.sid = api.get_session()
                self.req_count += 2
            except Exception:
                pass

        try:
            content = api.get_object_content(self.sat, self.sid, hno)
            self.req_count += 1
            detail = api.get_object_detail(self.sat, self.sid, hno)
            self.req_count += 1
            return (hno, content, detail)
        except Exception as e:
            # session 可能過期，refresh 後重試一次
            try:
                self.sat, self.sid = api.get_session()
                self.req_count += 2
                content = api.get_object_content(self.sat, self.sid, hno)
                self.req_count += 1
                detail = api.get_object_detail(self.sat, self.sid, hno)
                self.req_count += 1
                return (hno, content, detail)
            except Exception as e2:
                return (hno, None, str(e2))


def _fetch_details(conn, sat, sid, house_nos, delay, request_count,
                   concurrency=CONCURRENCY):
    """並行抓取 detail 並 UPDATE。每個 worker 維持獨立 session。

    Args:
        concurrency: 並行 worker 數（預設 3）
    """
    now_iso = datetime.now().isoformat()

    # 過濾已抓過的
    need = []
    for hno in house_nos:
        row = conn.execute("SELECT has_detail FROM houses WHERE id=?", (hno,)).fetchone()
        if not (row and row[0]):
            need.append(hno)
    skipped = len(house_nos) - len(need)
    total = len(need)

    if not need:
        print(f"  detail: 全部已抓過（{skipped} 筆跳過）")
        return sat, sid, request_count

    if skipped:
        print(f"  跳過已抓過 {skipped} 筆，剩餘 {total} 筆")

    # 建立 workers（每個 worker 持有獨立 session）
    workers: dict[int, _DetailWorker] = {}
    print(f"  建立 {concurrency} 個 detail workers...", flush=True)
    for i in range(concurrency):
        workers[i] = _DetailWorker(i, delay)
    print(f"  並行 detail: {concurrency} workers, {total} 筆待抓", flush=True)

    done = 0
    errors = 0
    db_lock = threading.Lock()

    def _worker_fetch(args):
        worker_id, hno = args
        return workers[worker_id].fetch(hno)

    # 輪流分配 house_nos 給 workers
    tasks = [(i % concurrency, hno) for i, hno in enumerate(need)]

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_worker_fetch, task): task[1] for task in tasks}

        for future in as_completed(futures):
            result = future.result()
            hno = result[0]

            if result[1] is not None:
                content, detail_data = result[1], result[2]
                with db_lock:
                    _update_detail(conn, hno, content, detail_data, now_iso)
                    done += 1
            else:
                with db_lock:
                    errors += 1
                    if errors % 10 == 0:
                        print(f"  detail 錯誤 ({errors}): {result[2]}", file=sys.stderr)

            with db_lock:
                processed = done + errors
                if processed % 50 == 0:
                    conn.commit()
                    pct = done / total * 100
                    print(f"  detail: {done}/{total} ({pct:.0f}%), 錯誤={errors}",
                          flush=True)

    conn.commit()

    # 累計 worker 請求數
    total_worker_reqs = sum(w.req_count for w in workers.values())
    request_count += total_worker_reqs

    print(f"  detail 完成: {done}/{total}, 錯誤={errors}")
    return sat, sid, request_count


def enrich_db(db_path: str, delay: float = DETAIL_DELAY,
              concurrency: int = CONCURRENCY):
    """對已有 DB 中 has_detail=0 的物件補抓 detail。"""
    conn = _init_db(db_path)
    rows = conn.execute(
        "SELECT id FROM houses WHERE has_detail IS NULL OR has_detail = 0"
    ).fetchall()
    house_nos = [r[0] for r in rows]

    if not house_nos:
        print("所有物件已有 detail 資料。")
        conn.close()
        return

    print(f"需補抓 {len(house_nos)} 筆 detail（{concurrency} workers）...")
    sat, sid = api.get_session()
    request_count = 2
    t0 = time.time()
    sat, sid, request_count = _fetch_details(
        conn, sat, sid, house_nos, delay, request_count, concurrency)
    elapsed = time.time() - t0
    conn.close()
    print(f"補抓完成！耗時 {elapsed:.1f} 秒, 請求 {request_count} 次")


# ── 互動選單 ──────────────────────────────────────────────────────────

def _prompt_city_selection():
    entries = list(api.CITY_MAP.items())
    print("\n可選城市：")
    print("-" * 50)
    for i, (code, _) in enumerate(entries, 1):
        print(f"  {i:>2}. {CITY_LABEL.get(code, code)} ({code})")
    print("-" * 50)
    print("  輸入編號（如 1,2,3 或 1-5），all = 全部，Enter = 全部")
    print()
    while True:
        raw = input("請選擇城市> ").strip()
        if not raw or raw.lower() == "all":
            print(f"→ 已選擇全部 {len(entries)} 個城市")
            return api.CITY_MAP
        selected = set()
        try:
            for token in raw.replace(",", " ").split():
                if not token.strip(): continue
                if "-" in token:
                    parts = token.split("-", 1)
                    selected.update(range(int(parts[0]), int(parts[1]) + 1))
                else:
                    selected.add(int(token))
        except ValueError:
            print("格式錯誤"); continue
        invalid = [n for n in selected if n < 1 or n > len(entries)]
        if invalid: print(f"超出範圍: {invalid}"); continue
        if not selected: print("未選擇"); continue
        chosen = {entries[i-1][0]: entries[i-1][1] for i in sorted(selected)}
        print(f"→ 已選擇 {len(chosen)} 個城市: {', '.join(CITY_LABEL.get(c,c) for c in chosen)}")
        return chosen


# ── 主程式 ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="爬取房屋物件並存入 SQLite（含完整明細）")
    parser.add_argument("--output-dir", default="data", help="輸出目錄（預設: data/）")
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE)
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY, help="搜尋請求間隔秒數")
    parser.add_argument("--detail-delay", type=float, default=DETAIL_DELAY, help="detail 請求間隔秒數")
    parser.add_argument("--cities", nargs="*", default=None, help="指定城市")
    parser.add_argument("--zip", default=None,
                        help="指定行政區 zip code（如 114=內湖, 多個逗號分隔 114,115）")
    parser.add_argument("--concurrency", "-c", type=int, default=CONCURRENCY,
                        help=f"detail 並行 worker 數（預設: {CONCURRENCY}）")
    parser.add_argument("--list-only", action="store_true", help="只抓搜尋列表（不抓 detail）")
    parser.add_argument("--enrich", metavar="DB_PATH", help="對已有 DB 補抓 detail")
    args = parser.parse_args()

    # enrich 模式
    if args.enrich:
        if not Path(args.enrich).exists():
            print(f"錯誤: DB 不存在: {args.enrich}")
            return
        enrich_db(args.enrich, args.detail_delay, args.concurrency)
        return

    # 正常爬取
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_name = datetime.now().strftime("%Y%m%d") + ".db"
    db_path = out_dir / db_name
    if db_path.exists():
        db_name = datetime.now().strftime("%Y%m%d_%H%M%S") + ".db"
        db_path = out_dir / db_name

    print(f"資料庫: {db_path}")
    mode = '僅搜尋列表' if args.list_only else f'搜尋列表 + 完整明細（{args.concurrency} workers）'
    print(f"模式: {mode}")
    conn = _init_db(str(db_path))

    print("取得 API session...")
    sat, sid = api.get_session()
    request_count = 2
    grand_total = 0
    t0 = time.time()

    # --zip 模式：直接指定行政區
    if args.zip:
        zip_str = args.zip
        # 自動推斷城市（取第一個 zip 查詢）
        city_hint = args.cities[0] if args.cities else "unknown"
        print(f"\n[zip={zip_str}] 開始爬取...")
        try:
            fetched, request_count, sat, sid = crawl_zip(
                conn, sat, sid, zip_str, city_hint,
                args.page_size, args.delay, request_count,
                with_detail=not args.list_only, concurrency=args.concurrency)
            grand_total += fetched
            print(f"[zip={zip_str}] 完成: {fetched} 筆")
        except Exception as e:
            print(f"[zip={zip_str}] 錯誤: {e}", file=sys.stderr)
    else:
        # 城市模式
        if args.cities:
            cities = {c: api.CITY_MAP[c] for c in args.cities if c in api.CITY_MAP}
            unknown = [c for c in args.cities if c not in api.CITY_MAP]
            if unknown:
                print(f"警告: 不認識的城市: {', '.join(unknown)}")
        else:
            cities = _prompt_city_selection()

        for city in cities:
            print(f"\n[{city}] 開始爬取...")
            try:
                fetched, request_count, sat, sid = crawl_city(
                    conn, sat, sid, city, args.page_size, args.delay, request_count,
                    with_detail=not args.list_only, concurrency=args.concurrency)
                grand_total += fetched
                print(f"[{city}] 完成: {fetched} 筆")
            except Exception as e:
                print(f"[{city}] 錯誤: {e}", file=sys.stderr)
                try: sat, sid = api.get_session(); request_count += 2
                except Exception: pass

    elapsed = time.time() - t0
    conn.close()

    # 統計
    detail_note = "（含明細）" if not args.list_only else "（僅列表）"
    print(f"\n{'='*50}")
    print(f"爬取完成！{detail_note}")
    print(f"  資料庫: {db_path}")
    print(f"  總筆數: {grand_total:,}")
    print(f"  耗時:   {elapsed:.1f} 秒")
    print(f"  請求數: {request_count:,}")


if __name__ == "__main__":
    main()
