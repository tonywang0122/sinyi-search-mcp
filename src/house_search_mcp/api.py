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
    house_no = obj.get("houseNo", "")
    return {
        "id": house_no,
        "name": obj.get("name"),
        "address": obj.get("address"),
        "age": obj.get("age"),
        "type": [TYPE_NAMES.get(t, t) for t in (obj.get("houselandtype") or [])],
        "price": obj.get("totalPrice"),
        "price_original": obj.get("priceFirst"),
        "discount_pct": obj.get("discount"),
        "building_area": obj.get("areaBuilding"),
        "main_area": obj.get("pingUsed"),
        "layout": obj.get("totalLayout") or obj.get("layout"),
        "floor": obj.get("floor"),
        "total_floor": obj.get("totalfloor"),
        "has_parking": obj.get("isParking", False),
        "parking": obj.get("parking"),
        "tags": [TAG_NAMES.get(str(t), str(t)) for t in (obj.get("tags") or [])],
        "watchers": obj.get("threeMonthsClicks"),
        "community": obj.get("commName"),
        "detail_url": f"https://www.sinyi.com.tw/buy/house/{house_no}" if house_no else None,
        "zip_code": obj.get("zipCode"),
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


def format_object_detail(content: dict, detail: dict) -> dict:
    house_no = content.get("houseNo", "")
    agent = content.get("agent")
    return {
        "id": house_no,
        "name": content.get("name"),
        "address": content.get("address"),
        "city": content.get("cityName"),
        "district": content.get("zipName"),
        "community": content.get("commName"),
        "price": content.get("totalPrice"),
        "price_original": content.get("priceFirst"),
        "discount_pct": content.get("discount"),
        "layout": content.get("totalLayout") or content.get("layout"),
        "floor": content.get("floor"),
        "total_floor": content.get("floors"),
        "age": content.get("age"),
        "type": [TYPE_NAMES.get(t, t) for t in (content.get("houselandtype") or [])],
        "building_area": content.get("areaBuilding"),
        "main_area": content.get("pingUsed"),
        "land_area": content.get("areaLand"),
        "area_detail": content.get("areaInfo"),
        "building_front": content.get("buildingFront"),
        "window_front": content.get("windowFront"),
        "is_side_unit": content.get("sfside", False),
        "has_darkroom": content.get("sfdarkroom", False),
        "management": content.get("hasmanager"),
        "monthly_fee": content.get("monthlyFee"),
        "parking": content.get("parking"),
        "structure": (detail.get("detail") or {}).get("buildingStructure"),
        "wall": (detail.get("detail") or {}).get("wallStructure"),
        "families_per_floor": (detail.get("detail") or {}).get("family"),
        "purpose": (detail.get("detail") or {}).get("purpose"),
        "zoning": (detail.get("detail") or {}).get("partition"),
        "description": detail.get("description", []),
        "tags": [TAG_NAMES.get(str(t), str(t)) for t in (detail.get("tags") or [])],
        "nearby": _extract_nearby(detail.get("lifeInfo") or []),
        "detail_url": f"https://www.sinyi.com.tw/buy/house/{house_no}" if house_no else None,
        "share_url": content.get("shareURL"),
        "watchers": content.get("threeMonthsClicks"),
        "first_listed": content.get("firstDisplay"),
        "agent": {"name": agent.get("agentName"), "store": agent.get("agentStore"),
                  "tel": agent.get("agentTel")} if agent else None,
    }
