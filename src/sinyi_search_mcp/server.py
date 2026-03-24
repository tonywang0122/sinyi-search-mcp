"""sinyi-search-mcp — MCP Server entry point."""

import json
import math

from mcp.server.fastmcp import FastMCP

from . import api

mcp = FastMCP("sinyi-search", instructions="""台灣房屋物件搜尋工具。
提供 sinyi_search（搜尋物件列表）和 sinyi_get_detail（查詢單一物件明細）。
搜尋結果包含價格、坪數、格局、屋齡、標籤、關注人數等。
物件明細包含座向、建築結構、經紀人賣點、周邊生活圈步行距離、管理費等。
""")


@mcp.tool()
def sinyi_search(
    city: str,
    zip: str = "",
    type: str = "",
    rooms: str = "",
    price: str = "",
    area: str = "",
    year: str = "",
    floor: str = "",
    tags: str = "",
    exclude: str = "",
    keyword: str = "",
    sort: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """搜尋台灣房屋物件列表。

    Args:
        city: 城市代碼。Taipei=台北市, NewTaipei=新北市, Taoyuan=桃園市,
              Hsinchu=新竹市, Taichung=台中市, Tainan=台南市, Kaohsiung=高雄市,
              Keelung=基隆市, Miaoli=苗栗縣, Changhua=彰化縣, Nantou=南投縣,
              Yunlin=雲林縣, Chiayi=嘉義市, Pingtung=屏東縣, Yilan=宜蘭縣,
              Hualien=花蓮縣, Taitung=台東縣
        zip: 行政區 zipCode，多個逗號分隔。
             台北市: 100=中正,103=大同,104=中山,105=松山,106=大安,108=萬華,
             110=信義,111=士林,112=北投,114=內湖,115=南港,116=文山。
             新北市: 220=板橋,221=汐止,231=新店,234=永和,235=中和,236=土城,
             241=三重,242=新莊,244=林口,247=蘆洲,251=淡水
        type: 物件類型，多個逗號分隔。apartment=公寓, building=電梯大樓(B),
              dalou=大樓(L), huaxia=華廈(M), flat=套房, villa=別墅/透天,
              store=店面, office=辦公, land=土地
        rooms: 房數。3=正好3房, 2-3=2~3房, 4+=4房以上, 2-=2房以下
        price: 總價(萬元)。1500-3000=區間, 2000+=以上, 1000-=以下
        area: 建物坪數。20-40=區間, 50+=以上, 15-=以下
        year: 屋齡(年)。0-10=區間, 30+=以上, 5-=以下
        floor: 樓層。2-5=區間, 10+=以上, 3-=以下
        tags: 標籤ID逗號分隔。4=有陽台,5=廁所開窗,7=有裝潢,6=有景觀,
              102=有電梯,17=近捷運,19=近學校,18=近市場,16=近公園,
              12=警衛管理,13=新上架,106=新降價
        exclude: 排除條件。4f=排除4樓, sfroofplus=排除頂加,
                 sfdarkroom=排除暗房, sfside=排除邊間
        keyword: 關鍵字搜尋（物件名稱），如：面寬邊間、河景
        sort: 排序。price-asc=價格低到高, price-desc=高到低,
              publish-desc=最新上架, diff-desc=降價幅度
        status: presale=預售屋, resale=成屋
        page: 頁次（預設1）
        page_size: 每頁筆數（預設20）
    """
    try:
        sat, sid = api.get_session()
    except Exception as e:
        return json.dumps({"error": f"API 連線失敗: {e}"}, ensure_ascii=False)

    params = {
        "city": city, "zip": zip, "type": type, "rooms": rooms,
        "price": price, "area": area, "year": year, "floor": floor,
        "tags": tags, "exclude": exclude, "keyword": keyword,
        "sort": sort, "status": status,
    }
    filter_body = api.build_filter(params)
    sort_val = api.SORT_MAP.get(sort, sort or "0")

    try:
        data = api.search(sat, sid, filter_body, page, page_size, sort_val)
    except Exception as e:
        return json.dumps({"error": f"搜尋失敗: {e}"}, ensure_ascii=False)

    total = data.get("totalCnt", 0)
    result = {
        "total": total,
        "page": page,
        "page_size": page_size,
        "page_count": math.ceil(total / page_size) if total > 0 else 0,
        "items": [api.format_item(o) for o in (data.get("object") or [])],
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def sinyi_get_detail(house_no: str) -> str:
    """查詢單一房屋物件的完整明細。

    回傳座向、建築結構、經紀人賣點描述、周邊生活圈步行距離、
    管理方式、車位詳情、月管理費等完整資訊。

    Args:
        house_no: 物件編號（如 '1083GN'），從 sinyi_search 結果的 id 欄位取得。
                  也可傳入物件 URL，會自動提取編號。
    """
    if "/" in house_no:
        house_no = house_no.rstrip("/").split("/")[-1]

    try:
        sat, sid = api.get_session()
    except Exception as e:
        return json.dumps({"error": f"API 連線失敗: {e}"}, ensure_ascii=False)

    try:
        content = api.get_object_content(sat, sid, house_no)
        detail = api.get_object_detail(sat, sid, house_no)
    except Exception as e:
        return json.dumps({"error": f"物件查詢失敗: {e}"}, ensure_ascii=False)

    return json.dumps(api.format_object_detail(content, detail), ensure_ascii=False, indent=2)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
