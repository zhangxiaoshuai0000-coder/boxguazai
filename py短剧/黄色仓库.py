#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import gzip
import re
import zlib
import ssl
import sys
import time
import threading
import urllib.error
import urllib.request
import urllib.parse

ENTRY_DOMAINS = [
    "https://333.9966hsck.cc",
    "https://111.9966hsck.cc",
    "https://hsck.tv",
    "https://333.9959hsck.cc",
]
API_PATH = "/api.php/provide/vod/"
PIC_PROXY_DEFAULT = "https://wsrv.nl/?url="
UA = ("Mozilla/5.0 (Linux; Android 12; Mobile) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

LIVE_TYPES = [
    (7, "日本有码"),
    (8, "无码中文字幕"),
    (9, "有码中文字幕"),
    (10, "日本无码"),
    (15, "国产视频"),
    (21, "欧美高清"),
    (22, "动漫剧情"),
    (26, "骑兵破解"),
]

ALL_TYPES = [
    (1, "日韩AV"),
    (2, "国产系列"),
    (3, "欧美"),
    (4, "成人动漫"),
    (7, "日本有码"),
    (8, "无码中文字幕"),
    (9, "有码中文字幕"),
    (10, "日本无码"),
    (15, "国产视频"),
    (21, "欧美高清"),
    (22, "动漫剧情"),
    (25, "广告"),
    (26, "骑兵破解"),
    (27, "PA"),
]

# ---------- 分类筛选定义 ----------
# 更新时间：走 API 参数 h（近 N 小时），服务端过滤，列表会真正变少
FILTER_TIME = {
    "key": "h",
    "name": "更新时间",
    "init": "",
    "value": [
        {"n": "全部", "v": ""},
        {"n": "近24小时", "v": "24"},
        {"n": "近3天", "v": "72"},
        {"n": "近7天", "v": "168"},
        {"n": "近30天", "v": "720"},
    ],
}

# 排序：接口不支持 order/by，对当前页结果做客户端排序
FILTER_SORT = {
    "key": "sort",
    "name": "排序",
    "init": "",
    "value": [
        {"n": "默认(最新)", "v": ""},
        {"n": "播放量高→低", "v": "hits_desc"},
        {"n": "播放量低→高", "v": "hits_asc"},
        {"n": "时间新→旧", "v": "time_desc"},
        {"n": "时间旧→新", "v": "time_asc"},
    ],
}

# 播放量门槛：对当前页结果按 vod_hits 过滤
FILTER_HITS = {
    "key": "hits",
    "name": "播放量",
    "init": "",
    "value": [
        {"n": "全部", "v": ""},
        {"n": "1千+", "v": "1000"},
        {"n": "1万+", "v": "10000"},
        {"n": "5万+", "v": "50000"},
        {"n": "10万+", "v": "100000"},
        {"n": "50万+", "v": "500000"},
    ],
}

# 每个分类挂上的筛选项（顺序即 UI 展示顺序）
CATEGORY_FILTERS = [FILTER_TIME, FILTER_SORT, FILTER_HITS]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Spider(object):
    def __init__(self):
        self.api = ENTRY_DOMAINS[0] + API_PATH
        self.site = ENTRY_DOMAINS[0]
        self.ua = UA
        self.timeout = 20
        self.retry = 3
        self.all_types = 0
        self.pic_mode = "proxy"
        self.pic_proxy = PIC_PROXY_DEFAULT
        self.pic_suffix = "&output=jpg&w=400&q=80"
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        self.diag = ""
        self._base = ""
        self._base_exp = 0.0
        self._override = ""
        self._lock = threading.Lock()
        self._opener = urllib.request.build_opener(_NoRedirect)

    def getName(self):
        return "黄色仓库"

    def init(self, extend=""):
        cfg = {}
        if extend:
            if isinstance(extend, dict):
                cfg = extend
            else:
                try:
                    cfg = json.loads(extend)
                except Exception:
                    cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        api = str(cfg.get("api") or "").strip()
        site = str(cfg.get("site") or "").strip()
        if api:
            self._override = api.split("/api.php")[0].rstrip("/")
            self.api = api if api.endswith("/") else api + "/"
            self.site = site or self._override
        elif site:
            self._override = site.rstrip("/")
            self.site = self._override
        if cfg.get("ua"):
            self.ua = str(cfg["ua"])
        if cfg.get("timeout"):
            self.timeout = int(cfg["timeout"])
        if cfg.get("retry"):
            self.retry = int(cfg["retry"])
        self.all_types = int(cfg.get("all_types") or 0)
        mode = str(cfg.get("pic_mode") or "").strip().lower()
        if mode in ("proxy", "cdn", "src"):
            self.pic_mode = mode
        if "pic_proxy" in cfg:
            self.pic_proxy = str(cfg.get("pic_proxy") or "")
        if "pic_suffix" in cfg:
            self.pic_suffix = str(cfg.get("pic_suffix") or "")
        elif self.pic_proxy and "wsrv.nl" not in self.pic_proxy:
            self.pic_suffix = ""

    def _headers(self, referer=None):
        return {
            "User-Agent": self.ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "identity",
            "Referer": referer or (self.site.rstrip("/") + "/"),
        }

    def _decode(self, resp):
        raw = resp.read()
        enc = (resp.headers.get("Content-Encoding") or "").lower()
        if "gzip" in enc:
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        elif "deflate" in enc:
            try:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            except Exception:
                pass
        for cs in ("utf-8", "gbk", "gb18030"):
            try:
                return raw.decode(cs)
            except Exception:
                continue
        return raw.decode("utf-8", "replace")

    def _fetch(self, url, referer=None, attempts=None, timeout=None):
        tries = max(1, int(attempts or self.retry))
        to = float(timeout or self.timeout)
        last = None
        for i in range(tries):
            try:
                req = urllib.request.Request(url, headers=self._headers(referer))
                return self._decode(urllib.request.urlopen(req, timeout=to, context=self.ctx))
            except Exception as e:
                last = e
                if i + 1 < tries:
                    time.sleep(0.6 * (i + 1))
        raise last

    def _probe(self, base):
        try:
            txt = self._fetch(base + API_PATH + "?ac=list&pg=1", referer=base.rstrip("/") + "/", attempts=1, timeout=8)
            j = json.loads(txt)
            return isinstance(j, dict) and "list" in j
        except Exception:
            return False

    def _hop(self, base):
        try:
            resp = self._opener.open(urllib.request.Request(base.rstrip("/") + "/", headers={"User-Agent": self.ua}), timeout=8)
            if getattr(resp, "status", 200) == 200:
                return base.rstrip("/")
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                loc = (e.headers.get("Location") or "").strip()
                if loc.startswith("http"):
                    return loc.rstrip("/")
        except Exception:
            pass
        return ""

    def _set_base(self, base):
        self._base = base
        self.site = base
        self.api = base + API_PATH
        self._base_exp = time.time() + 1800

    def _resolve_base(self):
        if self._base and time.time() < self._base_exp:
            return self._base
        with self._lock:
            if self._base and time.time() < self._base_exp:
                return self._base
            cands = []
            if self._override:
                cands.append(self._override.rstrip("/"))
            for d in ENTRY_DOMAINS:
                d = d.rstrip("/")
                if d not in cands:
                    cands.append(d)
            for base in cands:
                if self._probe(base):
                    self._set_base(base)
                    return self._base
                nxt = self._hop(base)
                if nxt and nxt != base and self._probe(nxt):
                    self._set_base(nxt)
                    return self._base
            self._base = ""
            if not self.diag:
                self.diag = "域名不可用|全部候选探测失败"
            return ""

    def _api(self, params):
        last = ""
        for attempt in (0, 1):
            base = self._resolve_base()
            if not base:
                raise ValueError(self.diag or "无可用域名")
            url = base + API_PATH + "?" + urllib.parse.urlencode(params)
            try:
                txt = self._fetch(url)
            except Exception as e:
                last = "网络|%s" % type(e).__name__
            else:
                try:
                    j = json.loads(txt)
                except Exception:
                    head = (txt or "").strip().replace("\n", " ")[:60]
                    last = "非JSON|" + head
                else:
                    if isinstance(j, dict) and "list" in j:
                        self.diag = ""
                        return j
                    last = "结构异常|" + str(j)[:60]
            if attempt == 0:
                self._base = ""
                self._base_exp = 0.0
        self.diag = last
        raise ValueError("接口异常：%s" % last)

    def _clean(self, s):
        s = str(s or "")
        s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
        s = s.replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">")
        return s.strip()

    def _html2text(self, s):
        s = str(s or "")
        s = s.replace("\r", "\n")
        s = re.sub(r"(?i)<br\s*/?>", "\n", s)
        s = re.sub(r"(?i)</p>", "\n", s)
        s = re.sub(r"<[^>]+>", "", s)
        s = self._clean(s)
        s = re.sub(r"[ \t]+", " ", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()

    def _remark(self, it):
        r = self._clean(it.get("vod_remarks"))
        if r:
            return r
        t = self._clean(it.get("vod_time"))
        return t[:10] if t else self._clean(it.get("type_name"))

    def _cdn_pic(self, it, pic):
        pu = str(it.get("vod_play_url") or "")
        m = re.search(r"(https://[^/]+)/video/m3u8/(.+?)/index\.m3u8", pu)
        if not m:
            m = re.search(r"(https://[^/]+)/video/m3u8/(.+?)/", pu)
        if not m:
            return ""
        host, d = m.group(1), m.group(2)
        if "/video/" in pic:
            tail = re.sub(r"^https?://[^/]+", "", pic)
            return host + tail
        return "%s/video/m3u8/%s/vod.jpg" % (host, d)

    def _pic(self, it):
        pic = self._clean(it.get("vod_pic"))
        if not pic or not pic.startswith("http"):
            return ""
        if self.pic_mode == "src":
            return pic
        if self.pic_mode == "cdn":
            return self._cdn_pic(it, pic) or pic
        if self.pic_proxy:
            return self.pic_proxy + urllib.parse.quote(pic, safe="") + self.pic_suffix
        return pic

    def _hits_num(self, it):
        for k in ("vod_hits", "vod_hits_month", "vod_hits_week", "vod_hits_day"):
            try:
                n = int(it.get(k) or 0)
                if n > 0:
                    return n
            except Exception:
                continue
        return 0

    def _hits_label(self, n):
        try:
            n = int(n or 0)
        except Exception:
            n = 0
        if n >= 100000000:
            return "%.1f亿播" % (n / 100000000.0)
        if n >= 10000:
            return "%.1f万播" % (n / 10000.0) if n % 10000 else "%d万播" % (n // 10000)
        if n > 0:
            return "%d播" % n
        return ""

    def _vod(self, it):
        vid = str(it.get("vod_id") or "")
        name = self._clean(it.get("vod_name")) or ("视频 " + vid)
        content = self._html2text(it.get("vod_blurb")) or self._html2text(it.get("vod_content"))
        hits = self._hits_num(it)
        remarks = self._remark(it)
        hl = self._hits_label(hits)
        if hl and hl not in remarks:
            remarks = (hl + " · " + remarks) if remarks else hl
        return {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": self._pic(it),
            "vod_remarks": remarks,
            "vod_year": self._clean(it.get("vod_year")),
            "vod_area": self._clean(it.get("vod_area")),
            "type_name": self._clean(it.get("type_name")),
            "vod_content": content,
            # 内部字段，供排序/播放量筛选（多数客户端会忽略未知字段）
            "vod_hits": hits,
            "vod_time": self._clean(it.get("vod_time")),
        }

    def _play(self, it):
        froms = [x.strip() for x in str(it.get("vod_play_from") or "").split("$$$")]
        urls = str(it.get("vod_play_url") or "").split("$$$")
        outs_f, outs_u = [], []
        for i, blk in enumerate(urls):
            blk = (blk or "").strip()
            if not blk:
                continue
            eps = []
            parts = [x for x in blk.split("#") if x.strip()]
            for n, part in enumerate(parts, 1):
                part = part.strip()
                if "$" in part:
                    pname, purl = part.split("$", 1)
                else:
                    pname, purl = "", part
                purl = purl.strip()
                if not purl:
                    continue
                if not pname:
                    if len(parts) > 1:
                        pname = "第%02d集" % n
                    else:
                        pname = self._remark(it) or "正片"
                eps.append("%s$%s" % (self._clean(pname), purl))
            if not eps:
                continue
            f = froms[i] if i < len(froms) and froms[i] else "线路%d" % (len(outs_f) + 1)
            outs_f.append(f)
            outs_u.append("#".join(eps))
        if not outs_f:
            return "", ""
        return "$$$".join(outs_f), "$$$".join(outs_u)

    def _class_item(self, tid, name):
        """单个分类：同时挂 filters，兼容只读 class.filters 的壳。"""
        return {
            "type_id": str(tid),
            "type_name": name,
            "filters": list(CATEGORY_FILTERS),
        }

    def _classes(self):
        """分类列表：最新更新 + 有内容的具体分类（跳过空的大类/广告）。"""
        cls = [self._class_item("new", "最新更新")]
        try:
            j = self._api({"ac": "list", "pg": 1})
            remote = j.get("class") or []
        except Exception:
            remote = []
        live = dict(LIVE_TYPES)
        # 无内容的大类 / 广告，默认不展示（可用 all_types=1 强制全开）
        skip = {1, 2, 3, 4, 25, 27}
        if self.all_types and remote:
            for c in remote:
                tid = str(c.get("type_id") or "")
                name = self._clean(c.get("type_name"))
                if tid and name:
                    cls.append(self._class_item(tid, name))
            return cls
        if remote:
            for c in remote:
                try:
                    tid = int(c.get("type_id") or 0)
                except Exception:
                    continue
                if tid in skip:
                    continue
                if tid in live or self.all_types:
                    name = self._clean(c.get("type_name")) or live.get(tid) or str(tid)
                    cls.append(self._class_item(str(tid), name))
            if len(cls) > 1:
                return cls
        for tid, name in LIVE_TYPES:
            cls.append(self._class_item(str(tid), name))
        return cls

    def _diag_card(self, where):
        return [{
            "vod_id": "diag",
            "vod_name": "[诊断] %s | %s" % (where, self.diag or "无数据"),
            "vod_pic": "",
            "vod_remarks": "接口异常",
            "vod_content": "接口：%s\n请检查域名是否更换（本站换域名频繁），可在配置里用 {\"api\": \"http://新域名/api.php/provide/vod/\"} 覆盖。" % (self.api or ""),
        }]

    def _build_filters(self, classes):
        """每个分类挂上：更新时间 / 排序 / 播放量。"""
        filters = {}
        for c in classes or []:
            tid = str(c.get("type_id") or "")
            if not tid:
                continue
            filters[tid] = list(CATEGORY_FILTERS)
        return filters

    def _as_dict(self, obj):
        """把客户端传来的 extend/filter 统一成 dict。兼容 JSON 字符串、列表等。"""
        if obj is None or obj is False or obj is True:
            return {}
        if isinstance(obj, dict):
            return dict(obj)
        if isinstance(obj, (bytes, bytearray)):
            try:
                obj = obj.decode("utf-8", "ignore")
            except Exception:
                return {}
        if isinstance(obj, str):
            s = obj.strip()
            if not s or s in ("{}", "null", "None", "false", "true"):
                return {}
            try:
                j = json.loads(s)
                if isinstance(j, dict):
                    return j
                if isinstance(j, list):
                    return self._list_to_filter_dict(j)
            except Exception:
                pass
            if "=" in s:
                try:
                    q = urllib.parse.parse_qs(s, keep_blank_values=True)
                    return {k: (v[0] if isinstance(v, list) and v else v) for k, v in q.items()}
                except Exception:
                    pass
            return {}
        if isinstance(obj, (list, tuple)):
            return self._list_to_filter_dict(obj)
        return {}

    def _list_to_filter_dict(self, lst):
        """兼容 [{'key':'h','value':'24'}, ...] 或 [['h','24'], ...]"""
        out = {}
        for item in lst or []:
            if isinstance(item, dict):
                k = item.get("key") or item.get("n") or item.get("name")
                v = item.get("value") if "value" in item else item.get("v")
                if k is not None and v is not None:
                    out[str(k)] = v
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                out[str(item[0])] = item[1]
        return out

    def _parse_filter_src(self, extend, filter_arg):
        """合并 extend 与 filter，兼容各壳传参差异。"""
        src = {}
        src.update(self._as_dict(filter_arg))
        src.update(self._as_dict(extend))
        nested = src.get("filters")
        if nested is not None:
            src.update(self._as_dict(nested))
        flat = {}
        for k, v in list(src.items()):
            if k in ("filters", "filter", "class", "type_id"):
                continue
            if isinstance(v, dict):
                if "v" in v:
                    flat[k] = v.get("v")
                elif "value" in v:
                    flat[k] = v.get("value")
                else:
                    flat[k] = v
            else:
                flat[k] = v
        return flat

    def _extend_params(self, extend, filter_arg):
        """仅返回应传给 API 的参数（目前主要是 h）。"""
        params = {}
        src = self._parse_filter_src(extend, filter_arg)
        h = str(src.get("h") or "").strip()
        if h.isdigit() and int(h) > 0:
            params["h"] = str(int(h))
        return params

    def _client_options(self, extend, filter_arg):
        """客户端排序 / 播放量门槛（接口不支持，在本页结果上处理）。"""
        src = self._parse_filter_src(extend, filter_arg)
        sort = str(src.get("sort") or "").strip().lower()
        hits_min = 0
        hv = str(src.get("hits") or "").strip()
        if hv.isdigit():
            hits_min = int(hv)
        return sort, hits_min

    def _apply_client_filters(self, items, sort, hits_min):
        """对当前页列表做播放量过滤 + 排序。"""
        if not items:
            return items
        out = list(items)
        if hits_min > 0:
            filtered = []
            for it in out:
                try:
                    h = int(it.get("vod_hits") or 0)
                except Exception:
                    h = 0
                if h >= hits_min:
                    filtered.append(it)
            out = filtered

        def hit_key(it):
            try:
                return int(it.get("vod_hits") or 0)
            except Exception:
                return 0

        def time_key(it):
            return str(it.get("vod_time") or "")

        if sort == "hits_desc":
            out.sort(key=hit_key, reverse=True)
        elif sort == "hits_asc":
            out.sort(key=hit_key)
        elif sort == "time_desc":
            out.sort(key=time_key, reverse=True)
        elif sort == "time_asc":
            out.sort(key=time_key)
        return out

    def homeContent(self, filter):
        classes = self._classes()
        # 始终返回 filters，避免部分壳因 filter=False 拿不到筛选项
        res = {
            "class": classes,
            "filters": self._build_filters(classes),
            "list": [],
        }
        try:
            j = self._api({"ac": "detail", "pg": 1})
            res["list"] = [self._vod(it) for it in (j.get("list") or [])]
        except Exception:
            res["list"] = self._diag_card("首页")
        return res

    def homeVideoContent(self):
        try:
            j = self._api({"ac": "detail", "pg": 1})
            return {"list": [self._vod(it) for it in (j.get("list") or [])]}
        except Exception:
            return {"list": self._diag_card("推荐")}

    def categoryContent(self, tid, pg, filter=None, extend=None, *args, **kwargs):
        """
        分类列表。筛选说明：
        - 更新时间 h：服务端过滤（列表数量会变）
        - 排序 / 播放量：对本页结果处理
        注意：站点配置里需 filterable:1，否则壳可能不把 extend 传进来。
        """
        try:
            pg = max(1, int(pg or 1))
        except Exception:
            pg = 1
        # 兼容少数壳把 extend 放在 filter 位置，或放进 kwargs
        if extend is None and args:
            extend = args[0] if args else None
        if kwargs:
            if extend is None and "extend" in kwargs:
                extend = kwargs.get("extend")
            if (filter is None or filter is False) and isinstance(kwargs.get("filter"), (dict, str, list)):
                filter = kwargs.get("filter")

        params = {"ac": "detail", "pg": pg}
        tid = str(tid or "new")
        if tid not in ("new", "0", ""):
            params["t"] = tid

        # 无论 filter 布尔值如何，只要带了条件就应用（部分文档写 filter=false 可忽略 extend，
        # 但实际很多壳会传 filter=false + 非空 extend，这里一律处理以保证“选了就刷新”）
        api_extra = self._extend_params(extend, filter)
        params.update(api_extra)
        sort, hits_min = self._client_options(extend, filter)

        out = {"page": pg, "pagecount": pg, "limit": 20, "total": 0, "list": []}
        try:
            j = self._api(params)
            lst = j.get("list") or []
            items = [self._vod(it) for it in lst]
            items = self._apply_client_filters(items, sort, hits_min)
            out["list"] = items
            out["pagecount"] = max(1, int(j.get("pagecount") or pg))
            out["total"] = int(j.get("total") or 0)
            out["limit"] = int(j.get("limit") or 20)
            # 客户端筛选后若本页被滤空，pagecount 仍用接口值；避免误弹诊断
            if not out["list"] and pg == 1:
                if api_extra or hits_min or sort:
                    out["list"] = []
                else:
                    out["list"] = self._diag_card("分类%s" % tid)
        except Exception:
            out["list"] = self._diag_card("分类%s" % tid)
        return out

    def _detail_vod(self, vid, it):
        v = self._vod(it)
        pfrom, purl = self._play(it)
        v.update({
            "vod_actor": self._clean(it.get("vod_actor")),
            "vod_director": self._clean(it.get("vod_director")),
            "vod_pubdate": self._clean(it.get("vod_pubdate")),
            "vod_play_from": pfrom or "dplayer",
            "vod_play_url": purl,
        })
        if not v["vod_content"]:
            bits = [x for x in [v.get("type_name"), self._clean(it.get("vod_time"))] if x]
            v["vod_content"] = " / ".join(bits)
        return v

    def detailContent(self, ids):
        if isinstance(ids, (list, tuple)):
            want = [str(x).strip() for x in ids]
        else:
            want = [str(ids).strip()]
        seen = []
        for x in want:
            if x and x != "diag" and x not in seen:
                seen.append(x)
        if not seen:
            return {"list": []}
        found = {}
        for i in range(0, len(seen), 20):
            chunk = seen[i:i + 20]
            try:
                j = self._api({"ac": "detail", "ids": ",".join(chunk)})
            except Exception:
                continue
            for it in j.get("list") or []:
                found[str(it.get("vod_id"))] = it
        out = []
        for vid in seen:
            it = found.get(vid)
            if it:
                out.append(self._detail_vod(vid, it))
        if not out:
            return {"list": self._diag_card("详情%s" % ",".join(seen[:3]))}
        return {"list": out}

    def searchContent(self, key, quick, page="1"):
        try:
            pg = max(1, int(page or 1))
        except Exception:
            pg = 1
        try:
            j = self._api({"ac": "detail", "wd": key, "pg": pg})
            lst = [self._vod(it) for it in (j.get("list") or [])]
            if not lst:
                return {"list": self._diag_card("搜索「%s」无结果" % key)}
            return {"list": lst}
        except Exception:
            return {"list": self._diag_card("搜索「%s」" % key)}

    def playerContent(self, flag, id, vipFlags):
        url = str(id or "").strip()
        hdr = {"User-Agent": self.ua, "Referer": self.site + "/"}
        if url.startswith("http") and (".m3u8" in url.lower() or ".mp4" in url.lower()):
            return {"parse": 0, "playUrl": "", "url": url, "header": hdr}
        if url.startswith("http"):
            return {"parse": 1, "playUrl": "", "url": url, "header": hdr, "jx": 1}
        return {"parse": 1, "playUrl": "", "url": url, "header": hdr, "jx": 1}

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        return ".m3u8" in u or ".mp4" in u

    def localProxy(self, param):
        return None

    def destroy(self):
        self._base = ""
        self._base_exp = 0.0


if __name__ == "__main__":
    s = Spider()
    s.init()
    print("入口:", " | ".join(ENTRY_DOMAINS))
    print("解析后站点:", s.site)
    print("接口:", s.api)

    h = s.homeContent(True)
    print("\n[首页] 分类数=%d  首页条数=%d" % (len(h["class"]), len(h["list"])))
    print("  分类:", " ".join("%s=%s" % (c["type_id"], c["type_name"]) for c in h["class"]))
    if h["list"]:
        print("  首条:", h["list"][0]["vod_name"][:50], "| 角标:", h["list"][0]["vod_remarks"])
        print("  封面:", h["list"][0]["vod_pic"][:110])

    def probe(u):
        if not u:
            return "空"
        try:
            req = urllib.request.Request(u, headers={"User-Agent": s.ua})
            resp = urllib.request.urlopen(req, timeout=25, context=s.ctx)
            body = resp.read(4)
            ok = (resp.headers.get("Content-Type") or "").startswith("image") or body[:2] == b"\xff\xd8"
            return "%s %s %s" % (resp.status, resp.headers.get("Content-Type"), "图片OK" if ok else "非图片")
        except Exception as e:
            return "失败 %s" % type(e).__name__

    if h["list"]:
        raw = ""
        play_url = ""
        try:
            j = s._api({"ac": "detail", "pg": 1})
            first = (j.get("list") or [{}])[0]
            raw = str(first.get("vod_pic") or "")
            play_url = str(first.get("vod_play_url") or "")
        except Exception:
            pass
        print("\n[封面] 原始地址:", raw[:110])
        for mode in ("src", "cdn", "proxy"):
            old_mode, old_proxy = s.pic_mode, s.pic_proxy
            s.init({"pic_mode": mode, "pic_proxy": old_proxy or PIC_PROXY_DEFAULT,
                    "pic_suffix": "&output=jpg&w=400&q=80"})
            url = s._pic({"vod_pic": raw, "vod_play_url": play_url})
            print("  %-5s -> %-9s %s" % (mode, probe(url), url[:110]))
            s.pic_mode, s.pic_proxy = old_mode, old_proxy

    for tid in ("7", "15", "21"):
        c = s.categoryContent(tid, 1, False, {})
        print("\n[分类%s] 条数=%d pagecount=%s total=%s 首条=%s"
              % (tid, len(c["list"]), c["pagecount"], c["total"],
                 (c["list"][0]["vod_name"][:36] if c["list"] else "-")))

    c2 = s.categoryContent("7", 100, False, {})
    print("[分类7 第100页] 条数=%d 首条=%s" % (len(c2["list"]), c2["list"][0]["vod_name"][:30] if c2["list"] else "-"))

    if h["list"]:
        vid = h["list"][0]["vod_id"]
        d = s.detailContent([vid])
        if d["list"]:
            v = d["list"][0]
            print("\n[详情%s] %s" % (vid, v["vod_name"][:40]))
            print("  线路:", v["vod_play_from"])
            pu = v["vod_play_url"]
            print("  播放:", pu[:110])
            first = pu.split("$$$")[0].split("#")[0]
            ep = first.split("$", 1)[1] if "$" in first else first
            p = s.playerContent(v["vod_play_from"], ep, None)
            print("  playerContent: parse=%s url=%s" % (p["parse"], p["url"][:100]))
            if p["url"].startswith("http"):
                try:
                    r = urllib.request.urlopen(urllib.request.Request(p["url"], headers=p["header"]), timeout=15, context=s.ctx)
                    head = r.read(200).decode("utf-8", "ignore")
                    print("  M3U8 状态:", r.status, r.headers.get("Content-Type"), "| 头:", head[:70].replace("\n", "|"))
                except Exception as e:
                    print("  M3U8 探测失败:", type(e).__name__, str(e)[:80])

    sc = s.searchContent("JUL", False, "1")
    print("\n[搜索 JUL] 条数=%d 首条=%s" % (len(sc["list"]), sc["list"][0]["vod_name"][:40] if sc["list"] else "-"))
    sc2 = s.searchContent("JUL", False, "2")
    print("[搜索 JUL 第2页] 条数=%d 首条=%s" % (len(sc2["list"]), sc2["list"][0]["vod_name"][:40] if sc2["list"] else "-"))
    print("\n自检结束。diag=", s.diag or "无")
