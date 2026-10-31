# -*- coding: utf-8 -*-
"""
剧OK (juok3.top) 四壳通用 Python 爬虫
适配: TVBox / 影视仓 / OK影视 / PickTV / Hawk(ANT TV) 等标准 TVBox Python 壳
- homeContent 仅返回 class + filters（首页列表由 homeVideoContent 提供）
- 封面与 m3u8/mp4 一律原始直链 + 标准 header，不内置本地代理、不做未成年词过滤
"""

import json
import re
import time
import urllib.parse

import requests

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    try:
        import sys
        sys.path.append('..')
        from base.spider import Spider as BaseSpider
    except ImportError:
        BaseSpider = object

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

RAW_SITES = ["https://juok3.top", "https://juok1.top"]
CAT_MAP = {"1": "电影", "2": "电视剧", "3": "综艺", "4": "动漫"}
SITE_NAMES = {
    "youku": "优酷", "qiyi": "爱奇艺", "qq": "腾讯", "imgo": "芒果",
    "leshi": "乐视", "sohu": "搜狐", "tudou": "土豆", "pptv": "PPTV",
    "mgtv": "芒果", "vl": "线路",
}
_MEDIA_RE = re.compile(r'\.(?:mp4|m3u8?|flv|ts|m4v|mpd)$', re.I)
_IMG_RE = re.compile(r'\.(?:jpg|jpeg|png|webp|gif|bmp)', re.I)

# 直连会话，不继承系统代理（手机壳内无代理；避免桌面/CI 代理把请求拦掉）
_SESSION = requests.Session()
_SESSION.trust_env = False
_SESSION.verify = False
try:
    requests.packages.urllib3.disable_warnings()
except Exception:
    pass


def _text(v):
    return '' if v is None else str(v).strip()


def _quote(v):
    return urllib.parse.quote(str(v), safe='')


def _pic(url):
    url = _text(url)
    if url.startswith('//'):
        return 'https:' + url
    return url


class Spider(BaseSpider):
    def getName(self):
        return '剧OK'

    # ---------- 基础请求 ----------
    def _base(self):
        return getattr(self, 'siteUrl', RAW_SITES[0]) or RAW_SITES[0]

    def _get(self, path, headers=None):
        h = {"Referer": self._base() + "/", "User-Agent": UA}
        if headers:
            h.update(headers)
        for base in RAW_SITES:
            try:
                r = _SESSION.get(base + path, headers=h, timeout=10)
                if r.status_code == 200 and r.text:
                    self.siteUrl = base
                    return r
            except Exception:
                continue
        return None

    def _post(self, path, body):
        h = {"User-Agent": UA, "Content-Type": "application/json",
             "X-Player-Request": "1", "Referer": self._base() + "/"}
        for base in RAW_SITES:
            try:
                r = _SESSION.post(base + path, headers=h,
                                  data=json.dumps(body), timeout=12)
                if r.status_code == 200 and r.text:
                    return r
            except Exception:
                continue
        return None

    # ---------- 四壳标准接口 ----------
    def init(self, extend=''):
        self.extend = extend or ''
        self.siteUrl = RAW_SITES[0]
        try:
            if isinstance(self.extend, str) and self.extend:
                ext = json.loads(self.extend)
                if isinstance(ext, dict):
                    if ext.get('siteUrl'):
                        self.siteUrl = _text(ext['siteUrl']).rstrip('/')
                    elif ext.get('proxy'):
                        self.siteUrl = _text(ext['proxy']).rstrip('/')
        except Exception:
            pass
        try:
            self._get('/api/config')
        except Exception:
            pass
        return self

    def homeContent(self, filter=None):
        # 只返回分类 + 筛选，首页视频走 homeVideoContent
        classes = [{"type_id": c, "type_name": n} for c, n in CAT_MAP.items()]
        areas = ["大陆", "香港", "台湾", "美国", "韩国", "日本", "英国", "其他"]
        years = ["2026", "2025", "2024", "2023", "2022", "2021", "2020"]
        filters = {}
        for cid in CAT_MAP:
            filters[cid] = [
                {"key": "area", "name": "地区", "init": "",
                 "value": [{"n": "全部", "v": ""}] + [{"n": a, "v": a} for a in areas]},
                {"key": "year", "name": "年份", "init": "",
                 "value": [{"n": "全部", "v": ""}] + [{"n": y, "v": y} for y in years]},
            ]
        return {"class": classes, "filters": filters}

    def homeVideoContent(self):
        try:
            r = self._get("/api/filter?catId=1&page=1&size=20")
            data = r.json() if r else {}
            vlist = [self._to_vod(m, "1") for m in data.get("movies", [])]
            return {"list": vlist}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        tid = _text(tid)
        try:
            page = int(pg)
        except Exception:
            page = 1
        if not isinstance(filter, dict):
            filter = {}
        size = 20
        qs = "catId=%s&page=%d&size=%d" % (tid, page, size)
        if filter.get("area"):
            qs += "&area=" + _quote(filter["area"])
        if filter.get("year"):
            qs += "&year=" + _quote(filter["year"])
        try:
            r = self._get("/api/filter?" + qs)
            data = r.json() if r else {}
        except Exception:
            data = {}
        movies = data.get("movies", [])
        total = data.get("total", len(movies))
        pc = max(1, (int(total) + size - 1) // size)
        vlist = [self._to_vod(m, tid) for m in movies]
        return {"page": page, "pagecount": pc, "limit": size,
                "total": total, "list": vlist}

    def detailContent(self, ids):
        if not isinstance(ids, (list, tuple)):
            ids = [ids]
        result = []
        for raw_id in ids:
            item = self._build_detail(_text(raw_id))
            if item:
                result.append(item)
        return {"list": result}

    def searchContent(self, key, quick=False, pg='1'):
        try:
            page = int(pg)
        except Exception:
            page = 1
        try:
            r = self._get("/api/search?q=%s&page=%d" % (_quote(key), page))
            data = r.json() if r else {}
        except Exception:
            data = {}
        vlist = []
        for it in data.get("results", []):
            cat_id = _text(it.get("cat_id") or "1")
            en_id = it.get("en_id") or it.get("id")
            title = re.sub(r"<[^>]+>", "", _text(it.get("title") or it.get("titleTxt")))
            ci = it.get("coverInfo") if isinstance(it.get("coverInfo"), dict) else {}
            remarks = _text(ci.get("duration")) or _text(it.get("year"))
            vlist.append({
                "vod_id": "%s_%s" % (cat_id, en_id),
                "vod_name": title,
                "vod_pic": _pic(it.get("cover", "")),
                "vod_remarks": remarks,
            })
        return {"page": page, "pagecount": 1, "limit": 20,
                "total": len(vlist), "list": vlist}

    def playerContent(self, flag, id, vipFlags=None):
        resolved = _text(id)
        try:
            r = self._post("/api/player/resolve", {"playUrl": id})
            if r:
                d = r.json()
                if d.get("success") and d.get("url"):
                    resolved = d["url"]
                    if d.get("encrypted"):
                        dr = self._post("/api/player/decrypt",
                                        {"encrypted": d["encrypted"], "nonce": ""})
                        if dr:
                            dd = dr.json()
                            if dd.get("url"):
                                resolved = dd["url"]
        except Exception:
            pass
        header = {"User-Agent": UA, "Referer": self._base() + "/"}
        path = urllib.parse.urlparse(resolved).path.lower()
        if _IMG_RE.search(path) or not _MEDIA_RE.search(urllib.parse.urlparse(resolved).path):
            # VIP 空壳线路返回的是封面图，或非媒体地址 -> 交宿主外部解析
            return {"parse": 1, "jx": 1, "url": id, "header": header}
        return {"parse": 0, "jx": 0, "url": resolved,
                "header": header, "format": "application/x-mpegURL"}

    def localProxy(self, param=None):
        return None

    def isVideoFormat(self, url):
        return bool(_MEDIA_RE.search(urllib.parse.urlparse(_text(url)).path))

    def manualVideoCheck(self):
        return False

    def action(self, action, data=None):
        return {}

    def destroy(self):
        pass

    # ---------- 内部 ----------
    def _to_vod(self, m, cat_id):
        cover = m.get("cdncover") or m.get("cover") or ""
        if m.get("moviecategory"):
            remarks = "/".join(m["moviecategory"])[:12]
        elif m.get("score"):
            remarks = _text(m.get("score"))
        else:
            remarks = _text(m.get("pubdate"))
        return {
            "vod_id": "%s_%s" % (cat_id, m.get("id", "")),
            "vod_name": _text(m.get("title")),
            "vod_pic": _pic(cover),
            "vod_remarks": remarks,
        }

    def _build_detail(self, raw_id):
        parts = raw_id.split("_", 1)
        cat, slug = (parts[0], parts[1]) if len(parts) == 2 else ("1", raw_id)
        try:
            r = self._get("/api/detail?cat=%s&id=%s" % (cat, slug))
            data = (r.json() or {}).get("data", {}) if r else {}
        except Exception:
            data = {}
        if not data:
            return {}

        pld = data.get("playlinksdetail", {}) or {}
        alle = data.get("allepidetail", {}) or {}
        lines = []
        for site, info in pld.items():
            sname = SITE_NAMES.get(site, site)
            eps = alle.get(site)
            if eps:
                ep_lines = []
                for ep in eps:
                    num = ep.get("playlink_num") or ep.get("id") or "正片"
                    url = ep.get("url") or info.get("default_url", "")
                    if url:
                        ep_lines.append("%s$%s" % (num, url))
                if ep_lines:
                    lines.append((1, sname, "#".join(ep_lines)))
            else:
                url = info.get("default_url", "")
                if url:
                    lines.append((0, sname, "正片$%s" % url))
        # 有真实选集的线路排前面
        lines.sort(key=lambda x: x[0], reverse=True)

        return {
            "vod_id": raw_id,
            "vod_name": _text(data.get("title")),
            "vod_pic": _pic(data.get("cdncover", "")),
            "vod_year": _text(data.get("pubdate"))[:4],
            "vod_area": "/".join(data.get("area", []) or []),
            "vod_remarks": CAT_MAP.get(cat, ""),
            "vod_content": _text(data.get("description") or data.get("comment")),
            "vod_director": "/".join(data.get("director", []) or []),
            "vod_actor": "/".join(data.get("actor", []) or []),
            "vod_play_from": "$$$".join(x[1] for x in lines),
            "vod_play_url": "$$$".join(x[2] for x in lines),
            "type_name": CAT_MAP.get(cat, ""),
        }