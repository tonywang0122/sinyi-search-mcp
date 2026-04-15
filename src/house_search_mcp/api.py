"""房屋搜尋 API 核心邏輯 — 搜尋 + 物件明細。"""

import httpx

# ── API ──────────────────────────────────────────────────────────────

API_BASE = "https://sinyiwebapi.sinyi.com.tw"

DEVICE_BODY = {
    "machineNo": "", "ipAddress": "127.0.0.1", "osType": 4, "model": "web",
    "deviceVersion": "Mac OS X 10.15.7", "appVersion": "146.0.0.0",
    "deviceType": 3, "apType": 3, "browser": 1, "memberId": "",
    "domain": "www.sinyi.com.tw", "utmSource": "", "utmMedium": "",
    "utmCampaign": "", "utmCode": "", "requestor": 1, "utmContent": "",
    "utmTerm": "", "sinyiGroup": 1,
}

COMMON_HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "origin": "https://www.sinyi.com.tw",
    "referer": "https://www.sinyi.com.tw/",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
}

# ── 對照表 ────────────────────────────────────────────────────────────

CITY_MAP = {
    "Taipei": "1", "NewTaipei": "2", "Keelung": "3", "Yilan": "4",
    "Hsinchu": "5", "Hsinchu-county": "6", "Taoyuan": "7",
    "Miaoli": "8", "Taichung": "9", "Changhua": "10",
    "Nantou": "11", "Yunlin": "12", "Chiayi": "13",
    "Chiayi-county": "14", "Tainan": "15", "Kaohsiung": "16",
    "Pingtung": "17", "Taitung": "18", "Hualien": "19",
    "Penghu": "20", "Kinmen": "21", "Lienchiang": "22",
}

TYPE_MAP = {
    "apartment": "A", "building": "B", "flat": "C", "villa": "D",
    "store": "E", "office": "F", "factory": "G", "warehouse": "H",
    "land": "I", "parking": "J", "other": "K", "dalou": "L",
    "huaxia": "M", "landstore": "O",
}

PARKING_MAP = {
    "plane": "2", "auto": "3", "mix": "4", "other": "6",
    "mechanical": "7", "tower": "8", "firstfloor": "9",
}

SORT_MAP = {
    "diff-desc": "1", "publish-desc": "2",
    "price-desc": "3", "price-asc": "4",
    "area-asc": "5", "area-desc": "6",
    "year-asc": "7", "year-desc": "8",
}

TYPE_NAMES = {
    "A": "公寓", "B": "電梯大樓", "C": "套房", "D": "別墅/透天",
    "E": "店面", "F": "辦公", "G": "廠房", "H": "倉庫",
    "I": "土地", "J": "單售車位", "K": "其他", "L": "大樓",
    "M": "華廈", "N": "別墅/透天", "O": "土地/廠房",
}

TAG_NAMES = {
    "1": "毛胚屋", "2": "房間皆有窗", "3": "前後陽台", "4": "有陽台",
    "5": "廁所開窗", "6": "有景觀", "7": "有裝潢", "8": "健身房",
    "9": "游泳池", "10": "具垃圾處理", "11": "花園", "12": "警衛管理",
    "13": "新上架", "14": "店長推薦", "15": "無障礙空間", "16": "近公園",
    "17": "近捷運", "18": "近市場", "19": "近學校", "20": "低總價",
    "21": "租賃中", "22": "三角窗", "100": "有2D/3D看屋",
    "101": "有影片", "102": "有電梯", "103": "落地窗", "106": "新降價",
    "107": "近超市",
}


# ── HTTP ─────────────────────────────────────────────────────────────

def _post(path: str, body: dict, extra_headers: dict | None = None) -> dict:
    headers = {**COMMON_HEADERS, **(extra_headers or {})}
    payload = {**DEVICE_BODY, **body}
    resp = httpx.post(f"{API_BASE}/{path}", json=payload, headers=headers, timeout=15, verify=False)
    resp.raise_for_status()
    data = resp.json()
    if data.get("retCode") != "200":
        raise RuntimeError(f"API {path}: [{data.get('retCode')}] {data.get('retMsg')}")
    return data["content"]


def get_session() -> tuple[str, str]:
    h = {"code": "0", "sat": "", "sid": ""}
    sat = str(_post("appSetup.php", {}, h)["accessCode"])
    h["sat"] = sat
    sid = str(_post("getSession.php", {}, h)["sid"])
    return sat, sid


def search(sat: str, sid: str, filter_body: dict, page: int, page_size: int, sort: str) -> dict:
    h = {"code": "0", "sat": sat, "sid": sid}
    return _post("filterObject.php", {
        "filter": filter_body, "page": page, "pageCnt": page_size,
        "sort": sort, "isReturnTotal": True,
    }, h)


def get_object_content(sat: str, sid: str, house_no: str) -> dict:
    return _post("getObjectContent.php", {"houseNo": house_no}, {"code": "0", "sat": sat, "sid": sid})


def get_object_detail(sat: str, sid: str, house_no: str) -> dict:
    return _post("getObjectDetail.php", {"houseNo": house_no}, {"code": "0", "sat": sat, "sid": sid})


# ── Filter 組裝 ──────────────────────────────────────────────────────

def format_range(value: str) -> str:
    value = value.strip()
    if value.endswith("+"):
        return f"{value[:-1].split('-')[-1]}-up"
    if value.endswith("-"):
        return f"min-{value[:-1].split('-')[0]}"
    if "-" not in value:
        return f"{value}-{value}"
    return value


def _safe_val(params: dict, key: str) -> str | None:
    v = params.get(key)
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def build_filter(params: dict) -> dict:
    f: dict = {"exludeSameTrade": False, "objectStatus": 0}

    zip_val = _safe_val(params, "zip")
    city_val = _safe_val(params, "city")
    if zip_val:
        f["retType"] = 2
        f["retRange"] = zip_val.split(",")
    elif city_val:
        city_id = CITY_MAP.get(city_val)
        f["retType"] = 1
        f["retRange"] = [city_id] if city_id else ["1"]
    else:
        f["retType"] = 1
        f["retRange"] = ["1"]

    type_val = _safe_val(params, "type")
    if type_val:
        f["houselandtype"] = [TYPE_MAP.get(t, t) for t in type_val.split(",")]

    rooms_val = _safe_val(params, "rooms")
    if rooms_val:
        f["room"] = {"isRoofPlus": True, "roomRange": [format_range(rooms_val)]}

    price_val = _safe_val(params, "price")
    if price_val:
        f["price"] = {"priceType": 2, "priceRange": [format_range(price_val)]}

    uniprice_val = _safe_val(params, "uniprice")
    if uniprice_val:
        f["price"] = {"priceType": 1, "priceRange": [format_range(uniprice_val)]}

    area_val = _safe_val(params, "area")
    if area_val:
        f["ping"] = {"pingType": 1, "pingRange": [format_range(area_val)]}

    year_val = _safe_val(params, "year")
    if year_val:
        f["houseAge"] = [format_range(year_val)]

    floor_val = _safe_val(params, "floor")
    if floor_val:
        f["floor"] = [format_range(floor_val)]

    tags_val = _safe_val(params, "tags")
    if tags_val:
        f["houseSpec"] = [t for t in tags_val.split(",") if t.strip()]

    exclude_val = _safe_val(params, "exclude")
    if exclude_val:
        f["exclude"] = [e for e in exclude_val.split(",") if e.strip()]

    keyword_val = _safe_val(params, "keyword")
    if keyword_val:
        f["keyword"] = {"keyword": keyword_val}

    parking_val = _safe_val(params, "parking")
    if parking_val:
        if parking_val == "no":
            f["parkType"] = ["0"]
        elif parking_val != "yes":
            f["parkType"] = [PARKING_MAP.get(p, p) for p in parking_val.split(",")]

    status_val = _safe_val(params, "status")
    if status_val == "presale":
        f["objectStatus"] = 3

    return f


# ── Format ───────────────────────────────────────────────────────────

def format_item(obj: dict) -> dict:
    """格式化搜尋列表中的單筆物件 — 完整對應 filterObject API 回傳欄位。"""
    house_no = obj.get("houseNo", "")
    return {
        # ── 識別 ──
        "id": house_no,                                        # 物件編號
        "object_id": obj.get("objectId"),                      # 物件內部 ID
        "object_type": obj.get("objectType"),                  # 物件類型碼（數字）
        "kind": obj.get("kind"),                               # 物件種類
        "status": obj.get("status"),                           # 物件狀態
        "is_off": obj.get("isOff"),                            # 是否已下架
        # ── 名稱 / 位置 ──
        "name": obj.get("name"),                               # 物件名稱
        "address": obj.get("address"),                         # 地址
        "zip_code": obj.get("zipCode"),                        # 行政區郵遞區號
        "community_id": obj.get("commId"),                     # 社區 ID
        "community": obj.get("commName"),                      # 社區名稱
        "latitude": obj.get("latitude"),                       # 緯度
        "longitude": obj.get("longitude"),                     # 經度
        # ── 類型 ──
        "type": [TYPE_NAMES.get(t, t) for t in (obj.get("houselandtype") or [])],  # 物件型態（中文）
        "type_raw": obj.get("houselandtype"),                  # 物件型態（原始代碼）
        "type_show": obj.get("houselandtypeShow"),             # 物件型態（顯示用文字）
        # ── 價格 ──
        "price": obj.get("totalPrice"),                        # 總價（萬元）
        "price_original": obj.get("priceFirst"),               # 原始開價（萬元）
        "discount_pct": obj.get("discount"),                   # 降價幅度（%）
        "unit_price": obj.get("uniPrice"),                     # 單價（萬/坪）
        # ── 格局 / 樓層 ──
        "layout": obj.get("totalLayout") or obj.get("layout"), # 格局（如 3房2廳2衛）
        "add_layout": obj.get("addLayout"),                    # 加蓋格局
        "floor": obj.get("floor"),                             # 所在樓層
        "total_floor": obj.get("totalfloor"),                  # 總樓層數
        "age": obj.get("age"),                                 # 屋齡（年）
        # ── 面積 ──
        "building_area": obj.get("areaBuilding"),              # 建物面積（坪）
        "main_area": obj.get("pingUsed"),                      # 主建物面積（坪）
        "land_area": obj.get("areaLand"),                      # 土地面積（坪）
        # ── 特徵旗標 ──
        "has_parking": obj.get("isParking", False),            # 是否有車位
        "parking": obj.get("parking"),                         # 車位資訊
        "has_balcony": obj.get("isHasBalcony"),                # 是否有陽台
        "has_view": obj.get("isHasView"),                      # 是否有景觀
        "has_video": obj.get("isHasVideo"),                    # 是否有影片
        "has_3dvr": obj.get("Is3Dvr"),                         # 是否有 3D VR
        "vr_3d": obj.get("3DVR"),                              # 3D VR 資訊
        "is_similar": obj.get("isSimilar"),                    # 是否為相似物件
        # ── 圖片 ──
        "image": obj.get("image"),                             # 首圖 URL
        "large_image": obj.get("largeImage"),                  # 大圖 URL
        "image_tag": obj.get("imageTag"),                      # 圖片標籤
        # ── 標籤 ──
        "tags": [TAG_NAMES.get(str(t), str(t)) for t in (obj.get("tags") or [])],  # 標籤（中文）
        "tags_raw": obj.get("tags"),                           # 標籤（原始 ID）
        # ── 統計 / 其他 ──
        "watchers": obj.get("threeMonthsClicks"),              # 近三月關注人數
        "manager_id": obj.get("managerId"),                    # 管理者 ID
        "group_company": obj.get("groupCompany"),              # 集團公司
        # ── 連結 ──
        "detail_url": f"https://www.sinyi.com.tw/buy/house/{house_no}" if house_no else None,
        "share_url": obj.get("shareURL"),                      # 分享連結
    }


def _extract_nearby(life_info: list) -> dict:
    result = {}
    type_map = {"traffic": "交通", "school": "學校", "market": "市場商圈",
                "hospital": "醫療", "other": "其他"}
    for group in life_info:
        label = type_map.get(group.get("type", ""), group.get("type", ""))
        items = group.get("info", [])
        nearest = sorted(items, key=lambda x: x.get("distance", 9999))[:3]
        if nearest:
            result[label] = [
                {"name": i.get("title", ""), "distance_m": i.get("distance", 0),
                 "walk_min": round(int(i.get("time") or 0) / 60)}
                for i in nearest
            ]
    return result


def _format_agent(agent: dict | None) -> dict | None:
    if not agent:
        return None
    return {
        "id": agent.get("agentId"),
        "name": agent.get("agentName"),
        "image": agent.get("agentImage"),
        "tel": agent.get("agentTel"),
        "official_tel": agent.get("agentOfficialTel"),
        "store_id": agent.get("agentStoreID"),
        "store": agent.get("agentStore"),
        "store_addr": agent.get("agentStoreAddr"),
        "store_tel": agent.get("agentStoreTel"),
        "lets_chat": agent.get("useLetsChat"),
        "title": agent.get("title"),
    }


def format_object_detail(content: dict, detail: dict) -> dict:
    """合併 getObjectContent + getObjectDetail — 完整對應所有 API 回傳欄位。"""
    house_no = content.get("houseNo", "")
    d = detail.get("detail") or {}

    return {
        # ── 基本識別 ──
        "id": house_no,                                        # 物件編號
        "name": content.get("name"),                           # 物件名稱
        "address": content.get("address"),                     # 地址
        "city_id": content.get("cityId"),                      # 城市代碼
        "city": content.get("cityName"),                       # 城市名稱
        "zip_code": content.get("zipCode"),                    # 行政區郵遞區號
        "district": content.get("zipName"),                    # 行政區名稱
        "community_id": content.get("commId"),                 # 社區 ID
        "community": content.get("commName"),                  # 社區名稱
        "object_type": content.get("objectType"),              # 物件類型碼
        "type": [TYPE_NAMES.get(t, t) for t in (content.get("houselandtype") or [])],  # 型態（中文）
        "type_raw": content.get("houselandtype"),              # 型態（原始代碼）
        "type_show": content.get("houselandtypeShow"),         # 型態（顯示用文字）
        # ── 價格 ──
        "price": content.get("totalPrice"),                    # 總價（萬元）
        "price_original": content.get("priceFirst"),           # 原始開價（萬元）
        "discount_pct": content.get("discount"),               # 降價幅度（%）
        "unit_price": content.get("uniPrice"),                 # 單價（萬/坪）
        "land_unit_price": content.get("landUniprice"),        # 土地單價（萬/坪）
        # ── 格局 ──
        "layout": content.get("totalLayout") or content.get("layout"),  # 格局（如 3房2廳2衛）
        "roomplus": content.get("roomplus"),                   # 房數
        "hallplus": content.get("hallplus"),                   # 廳數
        "bathroomplus": content.get("bathroomplus"),           # 衛浴數
        "openroomplus": content.get("openroomplus"),           # 開放式房間數
        "floor": content.get("floor"),                         # 所在樓層
        "total_floor": content.get("floors"),                  # 總樓層數
        "age": content.get("age"),                             # 屋齡（年）
        # ── 面積 ──
        "building_area": content.get("areaBuilding"),          # 建物面積（坪）
        "main_area": content.get("pingUsed"),                  # 主建物面積（坪）
        "land_area": content.get("areaLand"),                  # 土地面積（坪）
        "area_detail": content.get("areaInfo"),                # 面積明細
        "house_size": content.get("houseSize"),                # 房屋大小分類
        "has_balcony": content.get("isHasBalcony"),            # 是否有陽台
        # ── 座向 ──
        "house_front": content.get("houseFront"),              # 房屋座向
        "building_front": content.get("buildingFront"),        # 大樓座向
        "window_front": content.get("windowFront"),            # 窗戶座向
        "direction_land": content.get("directionland"),        # 土地座向
        # ── 特徵 ──
        "is_side_unit": content.get("sfside", False),          # 是否為邊間
        "has_darkroom": content.get("sfdarkroom", False),      # 是否有暗房
        "management": content.get("hasmanager"),               # 管理方式
        "monthly_fee": content.get("monthlyFee"),              # 月管理費
        # ── 車位 ──
        "has_parking": content.get("isParking"),               # 是否有車位
        "parking": content.get("parking"),                     # 車位詳情
        # ── 建築結構 (from getObjectDetail) ──
        "structure": d.get("buildingStructure"),               # 建築結構
        "wall": d.get("wallStructure"),                        # 牆壁結構
        "families_per_floor": d.get("family"),                 # 每層戶數
        "purpose": d.get("purpose"),                           # 用途
        "zoning": d.get("partition"),                          # 使用分區
        "detail_other": d.get("other"),                        # 其他說明
        "detail_notice": d.get("notice"),                      # 注意事項
        # ── 經紀人賣點 ──
        "description": detail.get("description", []),          # 經紀人賣點描述列表
        # ── 標籤 ──
        "tags": [TAG_NAMES.get(str(t), str(t)) for t in (detail.get("tags") or [])],  # 標籤（中文）
        "tags_raw": detail.get("tags"),                        # 標籤（原始 ID）
        "house_spec_tags": detail.get("houseSpecTags"),        # 房屋規格標籤
        "house_facility_tags": detail.get("houseFacilityTags"),# 設施標籤
        "house_life_tags": detail.get("houseLifeTags"),        # 生活機能標籤
        "house_feature_tags": detail.get("houseFeatureTags"),  # 特色標籤
        # ── 圖片 & 媒體 ──
        "images": content.get("images"),                       # 物件照片 URL 列表
        "layout_image": content.get("layoutImage"),            # 格局圖 URL
        "layout_image_3d": content.get("layoutImage3D"),       # 3D 格局圖 URL
        "map_image": content.get("map"),                       # 地圖圖片 URL
        "vr_type": content.get("vrType"),                      # VR 類型
        "vr_url": content.get("vrUrl"),                        # VR 看屋連結
        "vr_demo_url": content.get("vrDemoUrl"),               # VR 體驗連結
        "vr_image": content.get("vrImgUrl"),                   # VR 預覽圖 URL
        "ai_tour": content.get("aiTour"),                      # AI 導覽旗標
        "ai_tour_url": content.get("aiTourURL"),               # AI 導覽連結
        "video_url": content.get("videoUrl"),                  # 影片 URL
        "enable_ai_clear": content.get("enableAIClear"),       # AI 清除功能旗標
        # ── 語音導覽 (from getObjectDetail) ──
        "audio_list": detail.get("audioList"),                 # 語音導覽列表
        "audio_count": detail.get("audioCount"),               # 語音導覽數量
        # ── 生活圈 ──
        "nearby": _extract_nearby(detail.get("lifeInfo") or []),  # 周邊生活圈（整理後）
        "life_info_raw": detail.get("lifeInfo"),               # 周邊生活圈（原始資料）
        "utility_life_info": detail.get("utilitylifeInfo"),    # 公用設施生活圈
        # ── 連結 ──
        "detail_url": f"https://www.sinyi.com.tw/buy/house/{house_no}" if house_no else None,
        "share_url": content.get("shareURL"),                  # 分享連結
        # ── 座標 ──
        "latitude": content.get("latitude"),                   # 緯度
        "longitude": content.get("longitude"),                 # 經度
        # ── 統計 ──
        "watchers": content.get("threeMonthsClicks"),          # 近三月關注人數
        "first_listed": content.get("firstDisplay"),           # 首次上架日期
        "is_same_trade": content.get("isSameTrade"),           # 是否同業物件
        # ── 經紀人 ──
        "agent": _format_agent(content.get("agent")),          # 主要經紀人
        "agent2": _format_agent(content.get("agent2")),        # 次要經紀人
        "agent_default_tab": content.get("agentDefaultTab"),   # 經紀人預設分頁
        # ── 門市 ──
        "store": content.get("store"),                         # 門市資訊
    }
