# -*- coding: utf-8 -*-
"""
影视空壳 Python 蜘蛛（多源聚合）
列表：暴风资源接口，筛选参数直接交给接口（年份/地区/语言）
详情：按片名并行检索多条公开采集线路并合并，4K 线路排最前
运行环境：Python 3.11 + requests
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


class Spider:
    def __init__(self):
        self.list_api = "https://bfzyapi.com/api.php/provide/vod/"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        self.timeout = 8

        # 公开采集站。显示名用站点真实线路标识，不额外加「4K」。
        self.sources = [
            ("暴风", "https://bfzyapi.com/api.php/provide/vod/"),
            ("量子", "https://cj.lziapi.com/api.php/provide/vod/"),
            ("非凡", "https://api.ffzyapi.com/api.php/provide/vod/"),
            ("红牛", "https://www.hongniuzy2.com/api.php/provide/vod/"),
            ("极速", "https://jszyapi.com/api.php/provide/vod/"),
            ("光速", "https://api.guangsuapi.com/api.php/provide/vod/"),
            ("如意", "https://cj.rycjapi.com/api.php/provide/vod/"),
            ("天堂", "http://caiji.dyttzyapi.com/api.php/provide/vod/"),
            ("爱奇艺", "https://iqiyizyapi.com/api.php/provide/vod/"),
            ("魔都", "https://www.mdzyapi.com/api.php/provide/vod/"),
            ("金鹰", "http://jyzyapi.com/provide/vod/"),
            ("U酷", "https://api.ukuapi.com/api.php/provide/vod/"),
            ("360", "https://360zy.com/api.php/provide/vod/"),
            ("茅台", "https://caiji.maotaizy.cc/api.php/provide/vod/"),
        ]

        self.default_tid = {
            "1": "26",  # 电影 → 剧情片（父分类几乎无数据）
            "2": "31",  # 电视剧 → 国产剧
            "3": "46",
            "4": "40",
            "5": "28",
            "6": "50",  # 少儿 → 动画片
            "7": "58",  # 短剧
        }
        self.filter_tid = {
            "1": {
                "喜剧": "22", "动作": "21", "科幻": "24", "爱情": "25",
                "剧情": "26", "恐怖": "23", "战争": "27", "动画": "50",
                "悬疑": "26", "奇幻": "24", "犯罪": "21", "惊悚": "23",
                "冒险": "21", "灾难": "24", "伦理": "26", "其他": "26",
            },
            "2": {
                "国产剧": "31", "美剧": "32", "港剧": "33", "韩剧": "34",
                "台剧": "35", "日剧": "36", "海外剧": "37", "泰剧": "38",
            },
            "3": {"大陆": "46", "港台": "47", "日韩": "48", "欧美": "49"},
            "4": {"国产": "40", "日韩": "41", "欧美": "42", "港台": "43", "海外": "44"},
            "7": {
                "重生民国": "59", "穿越年代": "60", "现代言情": "61",
                "反转爽文": "62", "女恋总裁": "63", "闪婚离婚": "64",
                "都市脑洞": "65", "古装仙侠": "66", "AI漫剧": "68",
            },
        }
        # 未点「类型」时，用地区切到对应子分类，避免在国产剧里滤「日本」变成空
        self.area_tid = {
            "2": {
                "中国大陆": "31", "中国香港": "33", "中国台湾": "35",
                "美国": "32", "日本": "36", "韩国": "34", "泰国": "38", "印度": "37",
            },
            "3": {
                "中国大陆": "46", "中国香港": "47", "中国台湾": "47",
                "日本": "48", "韩国": "48", "美国": "49",
            },
            "4": {
                "中国大陆": "40", "中国香港": "43", "中国台湾": "43",
                "日本": "41", "韩国": "41", "美国": "42",
            },
            "1": {},
        }
        self.area_api = {
            "中国大陆": "中国大陆",
            "中国香港": "香港",
            "中国台湾": "台湾",
            "美国": "美国",
            "日本": "日本",
            "韩国": "韩国",
            "印度": "印度",
            "泰国": "泰国",
            "其他": "其他",
        }

    def getName(self):
        return "雨鹿源"

    def init(self, extend=""):
        return

    def homeContent(self, filter):
        years = [{"n": "全部", "v": ""}] + [
            {"n": y, "v": y} for y in [
                "2026", "2025", "2024", "2023", "2022", "2021", "2020",
                "2019", "2018", "2017", "2016", "2015", "2014", "2013",
                "2012", "2011", "2010",
            ]
        ] + [{"n": "2009~2000", "v": "2000"}]
        areas = [
            {"n": "全部", "v": ""},
            {"n": "中国大陆", "v": "中国大陆"},
            {"n": "中国香港", "v": "中国香港"},
            {"n": "中国台湾", "v": "中国台湾"},
            {"n": "美国", "v": "美国"},
            {"n": "日本", "v": "日本"},
            {"n": "韩国", "v": "韩国"},
            {"n": "印度", "v": "印度"},
            {"n": "泰国", "v": "泰国"},
            {"n": "其他", "v": "其他"},
        ]
        langs = [
            {"n": "全部", "v": ""},
            {"n": "国语", "v": "国语"},
            {"n": "英语", "v": "英语"},
            {"n": "粤语", "v": "粤语"},
            {"n": "韩语", "v": "韩语"},
            {"n": "日语", "v": "日语"},
            {"n": "其他", "v": "其他"},
        ]
        sorts = [
            {"n": "上映时间", "v": "time"},
            {"n": "人气高低", "v": "hits"},
            {"n": "评分高低", "v": "score"},
        ]
        movie_types = [
            "全部", "喜剧", "动作", "科幻", "爱情", "悬疑", "奇幻", "剧情",
            "恐怖", "犯罪", "动画", "惊悚", "战争", "冒险", "灾难", "伦理", "其他",
        ]
        return {
            "class": [
                {"type_id": "1", "type_name": "电影"},
                {"type_id": "2", "type_name": "电视剧"},
                {"type_id": "3", "type_name": "综艺"},
                {"type_id": "4", "type_name": "动漫"},
                {"type_id": "5", "type_name": "纪录片"},
                {"type_id": "6", "type_name": "少儿"},
                {"type_id": "7", "type_name": "短剧"},
            ],
            "filters": {
                "1": [
                    {"key": "class", "name": "类型", "value": self._opts(movie_types)},
                    {"key": "area", "name": "地区", "value": areas},
                    {"key": "year", "name": "年份", "value": years},
                    {"key": "lang", "name": "语言", "value": langs},
                    {"key": "by", "name": "排序", "value": sorts},
                ],
                "2": [
                    {"key": "class", "name": "类型", "value": self._opts([
                        "全部", "国产剧", "韩剧", "美剧", "日剧", "港剧", "台剧", "泰剧", "海外剧",
                    ])},
                    {"key": "area", "name": "地区", "value": areas},
                    {"key": "year", "name": "年份", "value": years},
                    {"key": "lang", "name": "语言", "value": langs},
                    {"key": "by", "name": "排序", "value": sorts},
                ],
                "3": [
                    {"key": "class", "name": "类型", "value": self._opts(["全部", "大陆", "港台", "日韩", "欧美"])},
                    {"key": "area", "name": "地区", "value": areas},
                    {"key": "year", "name": "年份", "value": years},
                    {"key": "by", "name": "排序", "value": sorts},
                ],
                "4": [
                    {"key": "class", "name": "类型", "value": self._opts(["全部", "国产", "日韩", "欧美", "港台", "海外"])},
                    {"key": "area", "name": "地区", "value": areas},
                    {"key": "year", "name": "年份", "value": years},
                    {"key": "lang", "name": "语言", "value": langs},
                    {"key": "by", "name": "排序", "value": sorts},
                ],
                "5": [
                    {"key": "area", "name": "地区", "value": areas},
                    {"key": "year", "name": "年份", "value": years},
                    {"key": "by", "name": "排序", "value": sorts},
                ],
                "6": [
                    {"key": "year", "name": "年份", "value": years},
                    {"key": "by", "name": "排序", "value": sorts},
                ],
                "7": [
                    {"key": "class", "name": "类型", "value": self._opts([
                        "全部", "重生民国", "穿越年代", "现代言情", "反转爽文",
                        "女恋总裁", "闪婚离婚", "都市脑洞", "古装仙侠", "AI漫剧",
                    ])},
                    {"key": "year", "name": "年份", "value": years},
                    {"key": "by", "name": "排序", "value": sorts},
                ],
            },
        }

    def _opts(self, names):
        return [{"n": n, "v": "" if n == "全部" else n} for n in names]

    def homeVideoContent(self):
        try:
            data = self._get(self.list_api, {"ac": "list", "t": "31", "pg": "1"})
            return {"list": [self._vod_item(v) for v in (data.get("list") or [])[:16]]}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        result = {
            "list": [],
            "page": int(pg) if str(pg).isdigit() else 1,
            "pagecount": 1,
            "limit": 20,
            "total": 0,
        }
        tid = str(tid)
        extend = self._parse_extend(extend)
        class_val = (extend.get("class") or "").strip()
        area_ui = (extend.get("area") or "").strip()
        year = (extend.get("year") or "").strip()
        lang = (extend.get("lang") or "").strip()
        by = (extend.get("by") or "").strip()

        real_tid = self.default_tid.get(tid, tid)
        if class_val and tid in self.filter_tid and self.filter_tid[tid].get(class_val):
            real_tid = self.filter_tid[tid][class_val]
        elif area_ui and tid in self.area_tid and self.area_tid[tid].get(area_ui):
            real_tid = self.area_tid[tid][area_ui]

        params = {"ac": "list", "t": real_tid, "pg": pg}
        area_api = self.area_api.get(area_ui, "")
        if area_api and area_api != "其他":
            params["area"] = area_api
        if year and year != "2000":
            params["year"] = year
        if lang and lang != "其他":
            params["lang"] = lang
        if by in ("time", "hits", "score"):
            params["by"] = by

        try:
            data = self._get(self.list_api, params)
            videos = data.get("list") or []
            # 2009~2000：接口没有区间参数，合并近年份的第一页，避免空列表
            if year == "2000":
                videos = self._years_range(real_tid, params)
            if not videos and (area_api or lang or year):
                # 组合过严时去掉语言再试一次，仍按地区/年份
                retry = dict(params)
                retry.pop("lang", None)
                if year == "2000":
                    retry.pop("year", None)
                data = self._get(self.list_api, retry)
                videos = data.get("list") or []
            result["list"] = [self._vod_item(v) for v in videos]
            result["page"] = int(data.get("page") or pg or 1)
            result["pagecount"] = int(data.get("pagecount") or 1)
            result["limit"] = int(data.get("limit") or 20)
            result["total"] = int(data.get("total") or len(videos))
        except Exception as e:
            print("[categoryContent]", e)
        return result

    def _years_range(self, real_tid, base_params):
        found = []
        seen = set()
        for y in ("2009", "2008", "2007", "2006", "2005", "2004", "2003", "2002", "2001", "2000"):
            p = dict(base_params)
            p["year"] = y
            p["pg"] = "1"
            p["t"] = real_tid
            try:
                data = self._get(self.list_api, p)
            except Exception:
                continue
            for v in data.get("list") or []:
                vid = str(v.get("vod_id"))
                if vid in seen:
                    continue
                seen.add(vid)
                found.append(v)
                if len(found) >= 20:
                    return found
        return found

    def detailContent(self, ids):
        result = {"list": []}
        if not ids:
            return result
        vod_id = ids[0] if isinstance(ids, list) else ids
        try:
            data = self._get(self.list_api, {"ac": "detail", "ids": vod_id})
            if not data.get("list"):
                return result
            v = data["list"][0]
            name = v.get("vod_name") or ""
            froms, urls = self._aggregate_lines(name, v.get("vod_play_from") or "", v.get("vod_play_url") or "")
            result["list"] = [{
                "vod_id": str(v.get("vod_id", "")),
                "vod_name": name,
                "vod_pic": v.get("vod_pic", ""),
                "type_name": v.get("type_name", ""),
                "vod_year": v.get("vod_year", ""),
                "vod_area": v.get("vod_area", ""),
                "vod_remarks": v.get("vod_remarks", ""),
                "vod_actor": v.get("vod_actor", ""),
                "vod_director": v.get("vod_director", ""),
                "vod_content": self._clean_html(v.get("vod_content", "")),
                "vod_play_from": "$$$".join(froms),
                "vod_play_url": "$$$".join(urls),
            }]
        except Exception as e:
            print("[detailContent]", e)
        return result

    def _aggregate_lines(self, name, primary_from, primary_url):
        lines = []  # (order, label, urlblock, sig)
        seen_sig = set()
        order = 0

        def signature(block):
            urls = []
            for part in (block or "").split("#"):
                if "$" in part:
                    urls.append(part.split("$", 1)[1].strip())
                elif part.strip():
                    urls.append(part.strip())
            return tuple(urls)

        def push(play_from, play_url):
            nonlocal order
            if not play_url:
                return
            froms = (play_from or "").split("$$$")
            blocks = play_url.split("$$$")
            if len(froms) != len(blocks):
                blocks = [play_url]
                froms = [play_from or "线路"]
            for raw, block in zip(froms, blocks):
                sig = signature(block)
                if not sig or sig in seen_sig:
                    continue
                seen_sig.add(sig)
                show = self._line_name(raw)
                lines.append((order, show, block))
                order += 1

        push(primary_from, primary_url)

        def fetch_one(api):
            try:
                data = self._get(api, {"ac": "list", "wd": name, "pg": "1"}, timeout=6)
            except Exception:
                return None
            for item in data.get("list") or []:
                if (item.get("vod_name") or "").strip() != name.strip():
                    continue
                if item.get("vod_play_url"):
                    return item.get("vod_play_from") or "", item.get("vod_play_url")
                vid = item.get("vod_id")
                if not vid:
                    return None
                try:
                    detail = self._get(api, {"ac": "detail", "ids": vid}, timeout=6)
                except Exception:
                    return None
                if detail.get("list"):
                    d = detail["list"][0]
                    return d.get("vod_play_from") or "", d.get("vod_play_url") or ""
            return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(fetch_one, api) for _, api in self.sources]
            try:
                for fut in as_completed(futs, timeout=12):
                    try:
                        got = fut.result()
                    except Exception:
                        continue
                    if got:
                        push(got[0], got[1])
            except Exception:
                pass

        # 名字相同但地址不同时，用原标识区分，不再编序号冒充新线路
        used = {}
        froms, urls = [], []
        # 原标识里带 4k 的排前面，其余保持返回顺序
        lines.sort(key=lambda x: (0 if "4k" in x[1].lower() else 1, x[0]))
        for _, show, block in lines:
            key = show
            n = 2
            while key in used:
                key = "%s%s" % (show, n)
                n += 1
            used[key] = True
            froms.append(key)
            urls.append(block)
        return froms, urls

    def _line_name(self, raw):
        raw = (raw or "").strip()
        known = {
            "bfzym3u8": "暴风",
            "lzm3u8": "量子",
            "liangzi": "量子云",
            "ffm3u8": "非凡",
            "feifan": "非凡云",
            "hnm3u8": "红牛",
            "hnyun": "红牛云",
            "jsm3u8": "极速",
            "jsyun": "极速云",
            "gsm3u8": "光速",
            "gsyun": "光速云",
            "rym3u8": "如意",
            "ruyi": "如意云",
            "dyttm3u8": "天堂",
            "dytt": "天堂云",
            "iqym3u8": "爱奇艺",
            "modum3u8": "魔都",
            "ukm3u8": "U酷",
            "ukyun": "U酷云",
            "360zy": "360",
            "jinyingm3u8": "金鹰",
            "jinyingyun": "金鹰云",
            "mtm3u8": "茅台",
            "mtyun": "茅台云",
            "sdm3u8": "闪电",
            "lbm3u8": "乐播",
        }
        name = known.get(raw.lower(), raw or "线路")
        # 只有原标识里真有 4K 才保留这几个字
        if "4k" in raw.lower() and "4k" not in name.lower():
            name = name + "4K"
        return name

    def searchContent(self, key, quick, pg="1"):
        result = {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        try:
            data = self._get(self.list_api, {"ac": "list", "wd": key, "pg": pg})
            videos = data.get("list") or []
            result["list"] = [self._vod_item(v) for v in videos]
            result["page"] = int(data.get("page") or pg or 1)
            result["pagecount"] = int(data.get("pagecount") or 1)
            result["total"] = int(data.get("total") or 0)
        except Exception as e:
            print("[searchContent]", e)
        return result

    def searchContentPage(self, key, quick, pg):
        return self.searchContent(key, quick, pg)

    def playerContent(self, flag, id, vipFlags):
        result = {"parse": 0, "url": id, "header": self.headers}
        low = (id or "").lower()
        if not any(x in low for x in (".m3u8", ".mp4", ".flv", ".mkv", ".ts")):
            result["parse"] = 1
        return result

    def localProxy(self, param):
        return None

    def isVideoFormat(self, url):
        return any(x in (url or "").lower() for x in (".m3u8", ".mp4", ".flv", ".mkv", ".ts"))

    def manualVideoCheck(self):
        return False

    def _vod_item(self, v):
        return {
            "vod_id": str(v.get("vod_id", "")),
            "vod_name": v.get("vod_name", ""),
            "vod_pic": v.get("vod_pic", ""),
            "vod_remarks": v.get("vod_remarks", ""),
            "vod_year": v.get("vod_year") or "",
        }

    def _parse_extend(self, extend):
        if isinstance(extend, str):
            try:
                extend = json.loads(extend) if extend else {}
            except Exception:
                extend = {}
        return extend if isinstance(extend, dict) else {}

    def _get(self, api, params, timeout=None):
        rsp = requests.get(
            api, params=params, headers=self.headers,
            timeout=timeout or self.timeout, verify=False,
        )
        rsp.encoding = "utf-8"
        data = rsp.json()
        if "list" not in data and data.get("code") not in (1, "1", 200, "200"):
            raise Exception(data.get("msg") or "api error")
        return data

    def _clean_html(self, text):
        if not text:
            return ""
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("\xa0", " ")
        return " ".join(text.split())


def init(extend=""):
    return Spider().init(extend)

def homeContent(filter):
    return json.dumps(Spider().homeContent(filter), ensure_ascii=False)

def homeVideoContent():
    return json.dumps(Spider().homeVideoContent(), ensure_ascii=False)

def categoryContent(tid, pg, filter, extend):
    return json.dumps(Spider().categoryContent(tid, pg, filter, extend), ensure_ascii=False)

def detailContent(ids):
    return json.dumps(Spider().detailContent(ids), ensure_ascii=False)

def searchContent(key, quick):
    return json.dumps(Spider().searchContent(key, quick), ensure_ascii=False)

def searchContentPage(key, quick, pg):
    return json.dumps(Spider().searchContentPage(key, quick, pg), ensure_ascii=False)

def playerContent(flag, id, vipFlags):
    return json.dumps(Spider().playerContent(flag, id, vipFlags), ensure_ascii=False)
