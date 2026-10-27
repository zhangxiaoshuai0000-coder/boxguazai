# -*- coding: utf-8 -*-
"""
非凡影视 —— 苹果CMS v10 采集接口源

接口：http://ffzy.tv/api.php/provide/vod/
实测（2026-10-27）：
  * ac=list   → 31 个分类（带 type_pid 分类树），4941 页，9.9 万条；**不返回 vod_pic**
  * ac=detail → 完整字段，vod_play_from/vod_play_url 已是 TVBox 格式
  * 根分类（电影片/连续剧/综艺片/动漫片）用 t=1..4 查不到数据，源里按分类树只保留子分类
  * 线路 feifan 是 /share/ 空页面（200 但 0 字节），**ffm3u8 才是直链**，源里已把直链排前面
  * 支持搜索（ac=detail&wd=）
"""

import sys
import json
import gzip
import zlib
import ssl
import time
import urllib.parse
import urllib.request
import urllib.error

sys.path.append('..')
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    BaseSpider = object

# ---------------- 站点配置 ----------------
SITE_NAME = "非凡影视"
BASE_URL = "http://ffzy.tv"
API_PATH = "/api.php/provide/vod/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
TIMEOUT = 15

# 分类探测结果按接口地址缓存（模块级），Spider 重建时也能复用，避免每次进首页都探一遍
_CLASS_MEMO = {}

# 没有 type_pid 分类树的站（闪电）需要手动跳过父分类：
# 1=电影 2=电视剧 3=综艺 4=动漫，它们本身没有视频，查出来是 0 条
ROOT_IDS = set()
ROOT_NAMES = set()


class Spider(BaseSpider):
    def __init__(self):
        try:
            super(Spider, self).__init__()
        except Exception:
            pass
        self.siteName = SITE_NAME
        self.baseUrl = BASE_URL
        self.apiUrl = BASE_URL + API_PATH
        self._class_cache = None
        self._img_cache = {}

    def getName(self):
        return self.siteName

    def init(self, extend=""):
        # {"api": "http://新域名/api.php/provide/vod/"} 可整体覆盖接口地址
        if isinstance(extend, dict) and extend.get("api"):
            self.apiUrl = str(extend["api"]).strip()
            m = urllib.parse.urlparse(self.apiUrl)
            self.baseUrl = "%s://%s" % (m.scheme, m.netloc)
        self.headers = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx))

    def getDependence(self):
        return []

    # ---------------- HTTP ----------------

    def _fetch(self, url):
        try:
            req = urllib.request.Request(url, headers=self.headers)
            with self.opener.open(req, timeout=TIMEOUT) as r:
                raw = r.read()
                enc = (r.headers.get("Content-Encoding", "") or "").lower()
            if raw[:2] == b"\x1f\x8b" or "gzip" in enc:
                try:
                    raw = gzip.decompress(raw)
                except Exception:
                    pass
            elif "deflate" in enc:
                try:
                    raw = zlib.decompress(raw)
                except Exception:
                    pass
            return r.getcode(), raw.decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            return e.code, ""
        except Exception:
            return -1, ""

    def _api(self, params):
        """调用采集接口，返回 dict；非 JSON（如「暂不支持搜索」）返回 None"""
        url = self.apiUrl + "?" + urllib.parse.urlencode(params)
        code, text = self._fetch(url)
        if code != 200 or not text:
            return None
        t = text.strip()
        if not t.startswith("{"):
            return None
        try:
            return json.loads(t)
        except Exception:
            return None

    # ---------------- 分类 ----------------

    def _probe(self, tid):
        """探活：该分类下有没有数据"""
        d = self._api({"ac": "list", "t": tid, "pg": 1})
        try:
            return int((d or {}).get("total") or 0) > 0
        except Exception:
            return False

    def _load_classes(self):
        if self._class_cache is not None:
            return self._class_cache
        if self.apiUrl in _CLASS_MEMO:
            self._class_cache = _CLASS_MEMO[self.apiUrl]
            return self._class_cache

        data = self._api({"ac": "list", "pg": 1}) or {}
        raw = [c for c in (data.get("class") or []) if isinstance(c, dict)]

        has_pid = any("type_pid" in c for c in raw)
        cands = []
        if has_pid:
            # 有分类树：只取子分类；没有子分类的根也保留
            parents = set()
            for c in raw:
                pid = c.get("type_pid")
                if pid not in (None, 0, "0", ""):
                    parents.add(str(pid))
            for c in raw:
                tid = str(c.get("type_id") or "")
                name = str(c.get("type_name") or "")
                if not tid or not name:
                    continue
                pid = c.get("type_pid")
                if pid in (None, 0, "0", ""):
                    if tid not in parents:      # 根分类且无子分类
                        cands.append((tid, name))
                else:
                    cands.append((tid, name))
        else:
            # 没有分类树（闪电）：1~4 是父分类（电影/电视剧/综艺/动漫），查询返回 0 条。
            # 不探活——该站按 IP 串行处理，12 个探活就要 8 秒，首页会明显卡。
            cands = [(str(c.get("type_id")), str(c.get("type_name")))
                     for c in raw if c.get("type_id") and c.get("type_name")]
            kept = [x for x in cands if x[0] not in ROOT_IDS and x[1] not in ROOT_NAMES]
            if kept:
                cands = kept

        self._class_cache = cands
        _CLASS_MEMO[self.apiUrl] = cands
        return cands

    # ---------------- 格式化 ----------------

    def _clean(self, s):
        return " ".join(str(s or "").split())

    def _card(self, v):
        return {
            "vod_id": str(v.get("vod_id") or ""),
            "vod_name": self._clean(v.get("vod_name")) or str(v.get("vod_id") or ""),
            "vod_pic": v.get("vod_pic") or v.get("vod_pic_thumb") or "",
            "vod_remarks": self._clean(v.get("vod_remarks")) or "",
        }

    def _fill_pics(self, items):
        """列表接口不带封面：用 ac=detail&ids= 批量补（一次请求）"""
        ids = [str(v.get("vod_id")) for v in items if v.get("vod_id")]
        if not ids:
            return items
        missed = [i for i in ids if i not in self._img_cache]
        if missed:
            d = self._api({"ac": "detail", "ids": ",".join(missed[:20])})
            for v in ((d or {}).get("list") or []):
                if isinstance(v, dict) and v.get("vod_id"):
                    self._img_cache[str(v["vod_id"])] = v
        for v in items:
            vid = str(v.get("vod_id") or "")
            full = self._img_cache.get(vid)
            if full:
                if not v.get("vod_pic"):
                    v["vod_pic"] = full.get("vod_pic") or full.get("vod_pic_thumb") or ""
                if not v.get("vod_remarks"):
                    v["vod_remarks"] = full.get("vod_remarks") or ""
        return items

    # ---------------- 列表 ----------------

    def homeContent(self, filter):
        classes = [{"type_id": tid, "type_name": name}
                   for tid, name in self._load_classes()]
        result = {"class": classes}
        try:
            result["list"] = self.categoryContent("", 1, None, None)["list"]
        except Exception:
            result["list"] = []
        return result

    def homeVideoContent(self):
        return self.categoryContent("", 1, None, None)

    def categoryContent(self, tid, page, filter, ext):
        try:
            pg = max(int(page), 1) if page else 1
        except Exception:
            pg = 1

        params = {"ac": "list", "pg": pg}
        if tid and str(tid).isdigit():
            params["t"] = int(tid)

        data = self._api(params) or {}
        items = data.get("list") or []
        items = self._fill_pics(items)

        try:
            pc = int(data.get("pagecount") or pg)
        except Exception:
            pc = pg
        try:
            total = int(data.get("total") or len(items))
        except Exception:
            total = len(items)

        return {
            "page": pg,
            "pagecount": max(pc, 1),
            "limit": int(data.get("limit") or len(items) or 20),
            "total": total,
            "list": [self._card(v) for v in items],
        }

    def searchContent(self, key, quick, page="1"):
        try:
            pg = max(int(page), 1) if page else 1
        except Exception:
            pg = 1

        # 能用 ac=detail&wd= 的站直接返回完整信息（含封面）
        data = self._api({"ac": "detail", "wd": key, "pg": pg})
        if data is None:
            data = self._api({"ac": "list", "wd": key, "pg": pg})
        if not data:
            # 本站不支持搜索（闪电会返回「暂不支持搜索」）
            return {"list": [], "page": pg, "pagecount": pg, "limit": 20, "total": 0}

        items = data.get("list") or []
        if items and not items[0].get("vod_pic"):
            items = self._fill_pics(items)

        try:
            pc = int(data.get("pagecount") or pg)
        except Exception:
            pc = pg

        return {
            "page": pg,
            "pagecount": max(pc, 1),
            "limit": int(data.get("limit") or len(items) or 20),
            "total": int(data.get("total") or len(items)),
            "list": [self._card(v) for v in items],
        }

    # ---------------- 详情 ----------------

    def detailContent(self, ids):
        vid = str(ids[0] if ids else "").strip()
        if not vid:
            return {"list": []}

        data = self._api({"ac": "detail", "ids": vid}) or {}
        lst = data.get("list") or []
        if not lst:
            return {"list": [{"vod_id": vid, "vod_name": "获取详情失败",
                              "vod_play_from": "", "vod_play_url": ""}]}
        v = lst[0]

        froms, urls = self._split_play(v)
        vod = {
            "vod_id": str(v.get("vod_id") or vid),
            "vod_name": self._clean(v.get("vod_name")),
            "vod_pic": v.get("vod_pic") or v.get("vod_pic_thumb") or "",
            "vod_remarks": self._clean(v.get("vod_remarks")),
            "vod_year": self._clean(v.get("vod_year")),
            "vod_area": self._clean(v.get("vod_area")),
            "vod_lang": self._clean(v.get("vod_lang")),
            "vod_actor": self._clean(v.get("vod_actor")),
            "vod_director": self._clean(v.get("vod_director")),
            "vod_content": self._clean(v.get("vod_content")),
            "vod_play_from": froms,
            "vod_play_url": urls,
        }
        return {"list": [vod]}

    def _split_play(self, v):
        """拆分线路；把「直链 m3u8」的线路排到最前面。
        /share/ 这类是空页面（200 但 0 字节），播放会失败，尽量靠后。"""
        froms = [x for x in (v.get("vod_play_from") or "").split("$$$")]
        urls = [x for x in (v.get("vod_play_url") or "").split("$$$")]
        pairs = list(zip(froms, urls))
        if not pairs:
            return "", ""

        def direct(url):
            first = (url or "").split("#")[0]
            if "$" in first:
                first = first.split("$", 1)[1]
            return 0 if ".m3u8" in first or ".mp4" in first else 1

        pairs.sort(key=lambda p: (direct(p[1]),
                                  0 if "m3u8" in (p[0] or "").lower() else 1))
        return "$$$".join(p[0] for p in pairs), "$$$".join(p[1] for p in pairs)

    # ---------------- 播放 ----------------

    def playerContent(self, flag, pid, vipFlags):
        target = str(pid or "").strip()
        if "$" in target:
            target = target.split("$", 1)[1]
        header = {
            "User-Agent": UA,
            "Referer": self.baseUrl + "/",
            "Accept": "*/*",
        }
        if not target:
            return {"parse": 0, "url": "", "header": json.dumps(header)}
        is_direct = self.isVideoFormat(target)
        return {
            "parse": 0 if is_direct else 1,
            "playUrl": "",
            "url": target,
            "header": json.dumps(header),
        }

    def isVideoFormat(self, url):
        low = str(url or "").lower()
        return ".m3u8" in low or ".mp4" in low or ".flv" in low or ".ts" in low

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self.opener = None


if __name__ == "__main__":
    sp = Spider()
    sp.init({})
    print("站点:", sp.getName(), "| 接口:", sp.apiUrl)
    cls = sp.homeContent(True)["class"]
    print("分类数:", len(cls), "|", [c["type_name"] for c in cls[:8]])
    r = sp.categoryContent(cls[0]["type_id"] if cls else "", 1, None, None)
    print("首页:", len(r["list"]), "条 pagecount", r["pagecount"])
    for v in r["list"][:3]:
        print("   -", v["vod_name"][:22], "|", v["vod_remarks"], "|", (v["vod_pic"] or "")[:48])
    if r["list"]:
        d = sp.detailContent([r["list"][0]["vod_id"]])["list"][0]
        print("详情:", d["vod_name"], "| 线路:", d["vod_play_from"])
        first = d["vod_play_url"].split("$$$")[0].split("#")[0]
        print("首集:", first[:90])
        p = sp.playerContent("", first.split("$")[-1], [])
        print("播放:", p["parse"], (p["url"] or "")[:70])
    s = sp.searchContent("庆余年", False, "1")
    print("搜索 庆余年:", s["total"], "条")
    for v in s["list"][:3]:
        print("   -", v["vod_name"][:22])
