# -*- coding: utf-8 -*-
"""
================================================================================
 小山影视源 · CatVod / Box  Python Spider
================================================================================
 后端   : http://43.248.128.122:578
 账号   : sukeke / sukeke.1   (已内置,可在 init 参数中覆盖)
 依赖   : requests (无则退回 urllib)

 已完整验证的链路
 ----------------------------------------------------------------------------
  1. 登录       POST /api/v1/user/login      {"Username","Password","device_id"}
  2. 密钥交换   GET  /api/v1/security/challenge  →  POST /api/v1/security/init
                → session_id + sign_key
  3. 列表/搜索  GET  /api/v1/search?wd=*&type=<分类>&page=<页>
                → data.hits[]   (wd=* 为通配,配合 type 即分类全量)
  4. 详情       GET  /api/v1/video/detail?id=<vod_id>
                → data.vod_info.vod_url_with_player[]  每条线路带 tk 票根
  5. 换票       POST /api/v1/vod/ticket       body {"token": "<tk完整值>"}
                → data.ticket  (play_ticket, 内含 parse_api / data.url / 有效期)
  6. 取流       按 parse_api 分三种形态解析:
                 · 相对路径  /api/v1/vod/parse?code=..&t=..&url=
                        → 拼 BASE 后 GET,服务端直接吐播放地址
                 · 外部解析  https://.../json_api.php?key=..&vid={md5}
                        → {md5} 用 data.url 替换,返回 JSON 取 url
                 · 外部解析  https://.../api/?key=..&url=
                        → url= 后拼 data.url,返回 JSON 取 url
  7. 推荐       GET  /api/v1/video/recommend?id=<vod_id>

 注意:device_id 必须与账号已绑定的设备一致(每个新 device_id 占一个设备配额,
      超了会报"设备数量已达上限")。下方已预置可用设备号。

 线路归类:对所有资源只做两件事 ——
      ① 改名:线路名等于"蓝光4K【推荐】/蓝光4k推荐"→蓝光4K02、等于"4K"→蓝光4K01;
         其余线路(如"小腾4K"、"蓝光"、"1080P-2")一律保持原名,不合并、不去重。
      ② 排序:蓝光4K01、蓝光4K02 置顶,后面的其他线路维持服务端原有顺序。
      对照表 LINE_RENAME、顺序 LINE_PRIORITY,也可用 init 参数 line_rename /
      line_priority 覆盖。

 分类筛选:homeContent 输出 类型/地区/年份 三组筛选项,categoryContent 接收
      extend 后本地过滤(服务端不支持这些参数,详见 FILTER_GENRES_COMMON 上方注释);
      filter_enable=0 可退回无筛选面板的老行为。
================================================================================
"""
import json
import time
import uuid
import base64
import hashlib
import hmac
import urllib.parse
import os
import random

try:
    import requests
except Exception:
    requests = None


try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        def init(self, extend=""):
            pass

        def getName(self):
            return ""

        def isVideoFormat(self, url):
            return False

        def manualVideoCheck(self):
            return False

        def destroy(self):
            pass

        def localProxy(self, param):
            return None


# 已实测的分类表(type_id -> 名称)。search 接口有严格限流,
# 分类探测会连发数十次请求必然触发风控,因此默认直接使用本表,不做在线探测。
KNOWN_TYPES = [
    (1, "电影"), (2, "连续剧"), (3, "综艺"), (4, "动漫"),
    (20, "短剧"), (21, "少儿"), (22, "漫剧"), (23, "纪录片"),
]

# ---------------------------------------------------------------- 线路归类规则
# 只改标签名字,不动资源本身:服务端线路名与下面的键"完全相等"时才改名
# (比对时忽略大小写/空格/括号,并允许省略开头的"线路"二字)。
# 命中不上的线路一律保持服务端原名,不做合并、不做去重。
LINE_RENAME = {
    "蓝光4k推荐": "蓝光4K02",      # 原"蓝光4K【推荐】"、"线路蓝光4k推荐"
    "4k": "蓝光4K01",              # 原"4K"、"线路4K"
}

# 线路排序优先级:此列表内的线路名按列表顺序排在最前,
# 其余线路一律排到后面,并保持服务端原有先后顺序。
LINE_PRIORITY = ["蓝光4K01", "蓝光4K02"]
# ---------------------------------------------------------------- 分类筛选面板
# 实测结论(2026-11-09):服务端 /api/v1/search 只认 wd / type / page 三个参数,
# area / year / class / lang / sort / by 全部被忽略(total 恒为 21036、返回内容逐字
# 相同),也不存在 filter / video/list / types 这类接口。所以筛选这么落地:
#   ① homeContent 按下面的表声明筛选面板(和 App 截图一致:类型 / 地区 / 年份);
#   ② categoryContent 收到 extend 后,把选中项一并发给服务端(万一将来支持就能少翻页),
#      同时始终在本地按 vod_class / vod_area / vod_year 过滤,保证结果真的是筛选后的。
# 类型选项来自各分类真实数据的标签词表,地区按 App 叫法给出、匹配时再展开成
# 服务端的各种写法("中国大陆 / 内地 / 国产 / 中国香港 / 港台" 等)。

# 通用类型池(电影 / 连续剧 / 短剧 / 漫剧 共用,对齐 App 筛选面板)
FILTER_GENRES_COMMON = [
    "剧情", "古装", "战争", "谍战", "爱情", "罪案", "悬疑", "家庭", "军旅", "喜剧",
    "都市", "武侠", "言情", "偶像", "青春", "农村", "穿越", "奇幻", "历史", "年代",
    "科幻", "生活", "励志", "婚姻", "警匪", "犯罪", "推理", "商战", "宫廷", "仙侠",
    "神话", "动作", "复仇", "惊悚",
]

# 分类特有的标签(实测数据里真实出现过的,追加在通用池后面)
FILTER_GENRES_EXTRA = {
    "电影": ["恐怖", "动画", "冒险", "运动", "院线", "枪战", "纯爱", "纪录", "音乐"],
    "连续剧": ["情感", "国产", "港台", "同性", "海外", "历史革命"],
    "短剧": ["逆袭", "甜宠", "萌宝", "战神", "穿越"],
    "漫剧": ["动态漫", "短剧"],
    "综艺": ["真人秀", "脱口秀", "访谈", "游戏", "竞技", "播客", "旅行观光", "音乐游学",
             "文化", "美食", "求职", "明星", "芒果出品", "伦理", "职场", "旅行"],
    "动漫": ["动漫", "动画", "玄幻", "热血", "番剧", "国创", "原创", "搞笑", "日常",
             "治愈", "战斗", "萌系", "智斗", "漫画改", "国产动漫", "欧美", "少儿", "恋爱"],
    "少儿": ["动画", "动漫", "益智", "亲子", "童话", "魔法", "热血", "搞笑", "冒险",
             "励志", "科幻", "真人", "少儿"],
    "纪录片": ["纪录", "人文", "自然", "科学", "社会", "探索", "传记", "刑侦", "战争",
               "历史", "美食", "萌宠", "旅游"],
}

# 地区(按 App 面板叫法),"其他" = 不属于以下任何一个
FILTER_AREAS = ["大陆", "香港", "台湾", "韩国", "日本", "美国", "泰国",
                "法国", "英国", "德国", "印度", "其他"]

# 服务端写法 -> 面板叫法。按顺序匹配,一个标签可以命中多个叫法(如"港台");
# 若某标签同时命中"大陆"和其他地区(如"中国香港"),只保留其他地区。
AREA_RULES = [
    ("香港", "香港"), ("港剧", "香港"), ("港", "香港"),
    ("台湾", "台湾"), ("台剧", "台湾"),
    ("韩国", "韩国"), ("韩剧", "韩国"),
    ("日本", "日本"), ("日剧", "日本"), ("日漫", "日本"),
    ("美国", "美国"), ("美剧", "美国"), ("欧美", "美国"),
    ("泰国", "泰国"), ("泰剧", "泰国"),
    ("法国", "法国"), ("英国", "英国"), ("德国", "德国"), ("印度", "印度"),
    ("大陆", "大陆"), ("内地", "大陆"), ("国产", "大陆"), ("华语", "大陆"),
    ("中国", "大陆"),
]

FILTER_YEAR_BACK = 8     # 年份选项:当年往前推 8 年(共9年),再加"其他",对齐 App 面板

# init 接口的服务端要求字段(只校验存在性,不校验取值)
_INIT_FILLER = {
    "sign": "s", "signature": "s", "app_id": "1", "app_key": "1",
    "app_version": "1.0", "version": "1", "platform": "android",
    "device": "android", "version_code": 1, "uid": "1",
    "source_id": "1", "site_id": "1", "type": "1",
}


class Spider(BaseSpider):
    CONFIG = {
        "base": "http://43.248.128.122:578",
        "username": "sukeke",
        "password": "sukeke.1",
        # 账号 sukeke 已绑定的设备号,换账号请改成自己的
        "device_id": "de94cd65-a825-4972-adf9-7dbece13e9f1",
        "timeout": 30,
        "user_agent": "Mozilla/5.0 (Linux; Android 12) okhttp/3.12.1",
        "page_size": 20,
        "auto_fallback": 1,   # 当前线路解析失败时自动降级到其它可用线路
        # 线路改名表与排序优先级,可在 init 参数里覆盖
        "line_rename": LINE_RENAME,
        "line_priority": LINE_PRIORITY,
        "filter_enable": 1,      # 是否输出分类筛选面板(0=退回原来的空 filters)
        "filter_scan_pages": 12, # 筛选模式最多向后翻多少原始页做本地过滤
        "filter_page_step": 4,   # 每次批量拉几页(越小首屏越快,越大深处越准)
        "filter_year_back": FILTER_YEAR_BACK,
    }

    def __init__(self):
        super().__init__()
        self.cfg = dict(self.CONFIG)
        self.base = self.CONFIG["base"].rstrip("/")
        self.device_id = ""
        self.jwt = ""
        self.session_id = ""
        self.sign_key = ""
        self._types = []
        self._http = None
        self._lines = []          # 上次详情里的线路顺序(用于降级)
        self._tkmap = {}          # tk -> {"name","code","ep"} 索引
        self._scan_cache = {}     # (tid,筛选串) -> 已过滤的原始命中,翻页复用

    # ================================================================= 基础
    def getName(self):
        return "小山"

    def init(self, extend=""):
        self.cfg = dict(self.CONFIG)
        if isinstance(extend, dict):
            self.cfg.update(extend)
        elif isinstance(extend, str) and extend.strip():
            try:
                self.cfg.update(json.loads(extend))
            except Exception:
                for kv in str(extend).split(","):
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        self.cfg[k.strip()] = v.strip()

        self.base = str(self.cfg["base"]).rstrip("/")
        self.device_id = str(self.cfg.get("device_id") or "").strip()
        if not self.device_id:
            self.device_id = uuid.uuid4().hex.upper()
            self._save_device_id(self.device_id)

        self._scan_cache = {}
        self._http = requests.Session() if requests else None
        if self._http:
            self._http.headers.update({"User-Agent": self.cfg.get("user_agent", "okhttp/3.12.1")})

        try:
            self._ensure_session()
        except Exception:
            pass

    def _save_device_id(self, did):
        for p in ("/sdcard/.xiaoshan_did", "/storage/emulated/0/.xiaoshan_did"):
            try:
                with open(p, "w") as f:
                    f.write(did)
                return
            except Exception:
                continue

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        return any(x in u for x in (".m3u8", ".mp4", ".flv", ".ts", "cmecloud", "apdcdn"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        try:
            if self._http:
                self._http.close()
        except Exception:
            pass

    def localProxy(self, param):
        return [404, "text/plain", "", None]

    # ================================================================= HTTP
    def _headers(self, extra=None):
        h = {"User-Agent": self.cfg.get("user_agent", "okhttp/3.12.1")}
        if self.jwt:
            h["Authorization"] = "Bearer " + self.jwt
        if self.session_id:
            h["X-Session-Id"] = self.session_id
        if extra:
            h.update(extra)
        return h

    def _get(self, path, params=None, headers=None, timeout=None):
        url = path if path.startswith("http") else self.base + path
        t = timeout or self.cfg.get("timeout", 20)
        try:
            if self._http:
                r = self._http.get(url, headers=self._headers(headers), params=params, timeout=t)
            else:
                q = ("?" + urllib.parse.urlencode(params)) if params else ""
                req = urllib.request.Request(url + q, headers=self._headers(headers))
                r = urllib.request.urlopen(req, timeout=t)
                body = r.read().decode("utf-8", "replace")
                return json.loads(body)
            return r.json()
        except Exception as e:
            return {"code": 0, "msg": "请求失败: %s" % e}

    def _post(self, path, payload, headers=None, timeout=None):
        url = path if path.startswith("http") else self.base + path
        t = timeout or self.cfg.get("timeout", 20)
        hh = self._headers(headers)
        hh["Content-Type"] = "application/json"
        try:
            if self._http:
                r = self._http.post(url, json=payload, headers=hh, timeout=t)
            else:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers=hh)
                r = urllib.request.urlopen(req, timeout=t)
                body = r.read().decode("utf-8", "replace")
                return json.loads(body)
            return r.json()
        except Exception as e:
            return {"code": 0, "msg": "请求失败: %s" % e}

    def _get_text(self, url, headers=None, timeout=None, retry=2):
        """带 Referer + 重试的 GET(外部解析接口冷启动较慢)"""
        t = timeout or self.cfg.get("timeout", 30)
        hh = self._headers(headers)
        hh.setdefault("Referer", "https://www.google.com/")
        last = ""
        for i in range(max(1, retry)):
            try:
                if self._http:
                    r = self._http.get(url, headers=hh, timeout=t)
                    return r.status_code, r.text
                req = urllib.request.Request(url, headers=hh)
                resp = urllib.request.urlopen(req, timeout=t)
                return resp.getcode(), resp.read().decode("utf-8", "replace")
            except Exception as e:
                last = str(e)
                if i < retry - 1:
                    time.sleep(1.2)
        return 0, last

    # ================================================================= 会话
    def _login(self):
        r = self._post("/api/v1/user/login", {
            "Username": self.cfg.get("username"),
            "Password": self.cfg.get("password"),
            "device_id": self.device_id,
        })
        if r.get("code") == 1 and isinstance(r.get("data"), dict):
            t = r["data"].get("token")
            if t:
                self.jwt = t
                return True
        return False

    def _handshake(self):
        ch = self._get("/api/v1/security/challenge")
        if ch.get("code") != 1 or not isinstance(ch.get("data"), dict):
            return False
        challenge = ch["data"].get("challenge")
        cid = ch["data"].get("challenge_id")
        if not challenge or not cid:
            return False

        payload = {
            "challenge": challenge,
            "challenge_id": cid,
            "device_id": self.device_id,
            "token": self.jwt,
            "client_token": "",
            "timestamp": int(time.time()),
            "nonce": uuid.uuid4().hex,
            "username": self.cfg.get("username"),
            "password": self.cfg.get("password"),
        }
        payload.update(_INIT_FILLER)

        r = self._post("/api/v1/security/init", payload)
        if r.get("code") == 1 and isinstance(r.get("data"), dict):
            self.session_id = r["data"].get("session_id") or ""
            self.sign_key = r["data"].get("sign_key") or ""
            return bool(self.session_id)
        return False

    def _ensure_session(self):
        if not self.jwt and not self._login():
            return False
        if not self.session_id and not self._handshake():
            return False
        return True

    def _sign_headers(self, path, body=""):
        """基于 sign_key 的设备签名(服务端 sign_policy=observe,属扩展用途)"""
        if not self.sign_key:
            return {}
        try:
            key = bytes.fromhex(self.sign_key)
        except Exception:
            return {}
        ts = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        msg = (ts + nonce + path + (body or "")).encode("utf-8")
        sg = hmac.new(key, msg, hashlib.sha256).hexdigest()
        return {"X-Timestamp": ts, "X-Nonce": nonce, "X-Sign": sg,
                "X-Device-Sign": sg, "X-Device-Id": self.device_id}

    # ================================================================= 分类
    def _detect_types(self):
        """遍历 type 自动发现分类表"""
        found = []
        for tid in list(range(1, 31)) + [40, 50, 60, 99]:
            try:
                r = self._get("/api/v1/search", params={"wd": "*", "type": tid, "page": 1})
            except Exception:
                continue
            if r.get("code") != 1:
                continue
            hits = ((r.get("data") or {}).get("hits")) or []
            if not hits:
                continue
            h0 = hits[0]
            if h0.get("type_id") and h0.get("type_name"):
                found.append((int(h0["type_id"]), str(h0["type_name"])))
        if found:
            self._types = sorted(set(found))
        return self._types

    def homeContent(self, filter):
        self._ensure_session()
        if not self._types:
            self._types = list(KNOWN_TYPES)
        on = self.cfg.get("filter_enable", 1)
        classes, fmap = [], {}
        for t, n in self._types:
            tid = str(t)
            fl = self._filters_for(str(n)) if on else []
            c = {"type_id": tid, "type_name": str(n)}
            if fl:
                c["filters"] = fl          # 部分播放器从 class 里读
            classes.append(c)
            fmap[tid] = fl                 # 标准位置:filters[type_id]
        return {"class": classes, "filters": fmap if on else {}}

    def homeVideoContent(self):
        try:
            return self.categoryContent(self._types[0][0] if self._types else "1", 1, False, {})
        except Exception:
            return {"list": []}

    # ================================================================= 列表
    def _search(self, wd, page=1, type_id=None, extra=None):
        """search 接口限流较严,遇"请求过于频繁"自动退避重试"""
        params = {"wd": wd, "page": page}
        if type_id:
            params["type"] = type_id
        for k, v in (extra or {}).items():
            if v:
                params[k] = v
        delays = [0, 2.5, 5, 9, 15]
        r = {"code": 0}
        for i, d in enumerate(delays):
            if d:
                time.sleep(d)
            r = self._get("/api/v1/search", params=params)
            if r.get("code") == 1:
                break
            msg = str(r.get("msg") or "")
            if "频繁" not in msg and "rate" not in msg.lower():
                break
        if r.get("code") != 1:
            return [], 1, 0
        data = r.get("data") or {}
        hits = data.get("hits") or []
        total = int(data.get("total") or 0)
        pages = int(data.get("total_pages") or 1)
        return hits, pages, total

    @staticmethod
    def _item(it):
        return {
            "vod_id": str(it.get("vod_id") or ""),
            "vod_name": str(it.get("vod_name") or ""),
            "vod_pic": str(it.get("vod_pic") or ""),
            "vod_remarks": str(it.get("vod_remarks") or ""),
            "vod_year": str(it.get("vod_year") or ""),
            "vod_area": str(it.get("vod_area") or ""),
            "vod_class": str(it.get("vod_class") or ""),
            "vod_actor": str(it.get("vod_actor") or ""),
            "vod_director": str(it.get("vod_director") or ""),
            "vod_content": str(it.get("vod_blurb") or it.get("vod_content") or ""),
        }

    # ------------------------------------------------------------ 筛选项构造
    def _type_name(self, tid):
        tid = str(tid or "")
        for pool in (self._types or [], list(KNOWN_TYPES)):
            for t, n in pool:
                if str(t) == tid:
                    return str(n)
        return ""

    def _year_values(self):
        try:
            cur = int(time.strftime("%Y"))
        except Exception:
            cur = 2100
        back = int(self.cfg.get("filter_year_back", FILTER_YEAR_BACK) or 0)
        vals = [{"n": "全部", "v": ""}]
        for y in range(cur, cur - back - 1, -1):
            vals.append({"n": str(y), "v": str(y)})
        vals.append({"n": "其他", "v": "<%d" % (cur - back)})
        return vals

    def _filters_for(self, tname):
        genres = list(FILTER_GENRES_COMMON)
        genres += FILTER_GENRES_EXTRA.get(tname or "", [])
        seen, gvals = set(), []
        for g in ["全部"] + genres:
            if g and g not in seen:
                seen.add(g)
                gvals.append({"n": g, "v": "" if g == "全部" else g})
        groups = [
            {"key": "class", "name": "类型", "value": gvals},
            {"key": "area", "name": "地区",
             "value": [{"n": "全部", "v": ""}] + [{"n": a, "v": a} for a in FILTER_AREAS]},
            {"key": "year", "name": "年份", "value": self._year_values()},
        ]
        return groups

    # ------------------------------------------------------------ 筛选条件解析
    @staticmethod
    def _ext_dict(extend):
        # extend 可能是 dict,也可能是 JSON 或 "k=v,k=v" 字符串
        raw = extend
        if isinstance(extend, str) and extend.strip():
            try:
                raw = json.loads(extend)
            except Exception:
                raw = {}
                for kv in extend.split(","):
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        raw[k.strip()] = v.strip()
        if not isinstance(raw, dict):
            return {}
        out = {}
        for k, v in raw.items():
            if isinstance(v, (list, tuple)):
                v = v[0] if v else ""
            elif isinstance(v, dict):
                v = v.get("v") or v.get("n") or ""
            key = str(k).strip().lower()
            val = str(v or "").strip()
            if not val or val in ("全部", "*", "all", "ALL", "不限"):
                continue
            if key in ("class", "cate", "genre", "类型", "剧情", "sub"):
                out["class"] = val
            elif key == "area":
                out["area"] = val
            elif key == "year":
                out["year"] = val
        return out

    @staticmethod
    def _split_field(v):
        out = []
        for p in str(v or "").split(","):
            p = p.strip()
            if p and p.lower() != "none":
                out.append(p)
        return out

    @staticmethod
    def _labels_of(tokens):
        # 一条记录可以属于多个地区;"中国香港"这类写法不会算进"大陆"
        labels = set()
        for t in tokens:
            cur = set()
            for k, v in AREA_RULES:
                if k in t:
                    cur.add(v)
            if cur - {"大陆"}:
                cur -= {"大陆"}
            labels |= cur
        return labels

    def _area_labels(self, it):
        """地区归属优先看 vod_area,该字段为空才退回 class 里的地区标签。
        这样"vod_area=中国台湾 + class 含 港台"不会被误判成香港。"""
        direct = self._labels_of(self._split_field(it.get("vod_area")))
        if direct:
            return direct
        return self._labels_of(self._split_field(it.get("vod_class")))

    def _match(self, it, sel):
        # 类型只认 vod_class,避免 type_name / vod_lang 里的字带偏判定
        g = sel.get("class")
        if g and not any(t == g or g in t or t in g
                         for t in self._split_field(it.get("vod_class"))):
            return False
        a = sel.get("area")
        if a:
            labs = self._area_labels(it)
            if a == "其他":
                if labs & set(FILTER_AREAS):
                    return False
            elif a not in labs:
                return False
        y = sel.get("year")
        if y:
            yy = str(it.get("vod_year") or "").strip()
            if not (yy.isdigit() and 1900 < int(yy) < 2200):
                return False
            if y.startswith("<"):
                if int(yy) >= int(y[1:]):
                    return False
            elif yy != y:
                return False
        return True

    def _sel_params(self, sel):
        # 顺手也发给服务端(现在会被忽略,将来支持了就少翻页)
        return {"class": sel.get("class", ""), "area": sel.get("area", ""),
                "year": sel.get("year", "")}

    def _sel_sig(self, sel):
        return "%s|%s|%s" % (sel.get("class", ""), sel.get("area", ""), sel.get("year", ""))

    def _scan(self, tid, sel, need):
        # 边翻原始页边本地过滤,结果按 (分类+筛选) 缓存,翻页不重复请求
        key = (str(tid), self._sel_sig(sel))
        st = self._scan_cache.setdefault(key, {"items": [], "page": 0, "done": False, "pages": 0})
        cap = int(self.cfg.get("filter_scan_pages", 12) or 1)
        step = max(1, int(self.cfg.get("filter_page_step", 4) or 1))
        extra = self._sel_params(sel)
        while (not st["done"]) and len(st["items"]) < need and st["page"] < cap:
            stop_at = min(cap, st["page"] + step)
            for p in range(st["page"] + 1, stop_at + 1):
                hits, pages, total = self._search("*", p, str(tid), extra=extra)
                st["page"] = p
                st["pages"] = max(st["pages"], pages or 1)
                if not hits:
                    st["done"] = True
                    break
                for it in hits:
                    if self._match(it, sel):
                        st["items"].append(it)
                if pages and p >= pages:
                    st["done"] = True
                    break
            if st["page"] >= cap:
                st["done"] = st["done"] or st["page"] >= st["pages"]
        return st

    def categoryContent(self, tid, pg, filter, extend):
        self._ensure_session()
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        limit = self.cfg.get("page_size", 20)
        sel = self._ext_dict(extend) if self.cfg.get("filter_enable", 1) else {}

        # 无筛选条件:保持原逻辑,一次请求直接返回
        if not sel:
            hits, pages, total = self._search("*", pg, str(tid))
            lst = [self._item(it) for it in hits]
            return {"list": lst, "page": pg, "pagecount": pages,
                    "limit": limit, "total": total}

        st = self._scan(tid, sel, pg * limit)
        got = st["items"]
        lst = [self._item(it) for it in got[(pg - 1) * limit: pg * limit]]
        scanned_all = st["done"] or st["page"] >= max(st["pages"], 1)
        out = {
            "list": lst,
            "page": pg,
            "pagecount": int((len(got) + limit - 1) // limit) if scanned_all
                         else max(pg, (len(got) + limit - 1) // limit),
            "limit": limit,
            "total": len(got),
        }
        out["msg_data"] = {
            "filter": sel,
            "scan_pages": st["page"],
            "scan_total": scanned_all,
            "note": "" if scanned_all else
                    "本地已扫描前 %s 页(共 %s 页),更深的页码未参与筛选" % (st["page"], st["pages"]),
        }
        return out

    def searchContent(self, key, quick, pg="1"):
        self._ensure_session()
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        hits, pages, total = self._search(str(key), pg)
        lst = [self._item(it) for it in hits]
        return {"list": lst, "page": pg, "pagecount": pages, "total": total}

    # ================================================================= 详情
    @staticmethod
    def _norm(s):
        """线路名比对用的归一化:转小写、去掉空格与各类括号/分隔符"""
        t = str(s or "").lower()
        for ch in (" ", "\t", "\u3000", "-", "_", "/", "|",
                   "(", ")", "（", "）", "[", "]", "【", "】", "《", "》"):
            t = t.replace(ch, "")
        return t

    def _line_name(self, raw):
        """线路改名:线路名与 line_rename 的键完全相等才改
        (比对时忽略大小写/空格/括号,并允许省略开头的"线路"二字)。
        命中不了的一律保持服务端原名,不合并、不去重。"""
        table = self.cfg.get("line_rename") or {}
        norm = self._norm(raw)
        if not norm or not table:
            return raw
        keys = {}
        for k, v in table.items():
            keys[self._norm(k)] = v
        if norm in keys:
            return str(keys[norm])
        if norm.startswith("线路") and norm[2:] in keys:
            return str(keys[norm[2:]])
        return raw

    def _line_order(self, name):
        """排序权重:line_priority 里的线路名按序排最前,其余统一落到末位"""
        pri = self.cfg.get("line_priority") or []
        norm = self._norm(name)
        for i, p in enumerate(pri):
            if self._norm(p) == norm:
                return i
        return len(pri)

    def detailContent(self, ids):
        self._ensure_session()
        if not ids:
            return {"list": []}
        vid = str(ids[0]).split(",")[0]
        path = "/api/v1/video/detail"
        r = self._get(path, headers=self._sign_headers(path), params={"id": vid})
        if r.get("code") != 1 or not isinstance(r.get("data"), dict):
            return {"list": []}
        vi = r["data"].get("vod_info") or {}

        # 先把服务端线路收齐,再统一改名归类 + 排序(蓝光4K01/02 置顶,其余靠后)
        rows = []
        for idx, line in enumerate(vi.get("vod_url_with_player") or []):
            raw = str(line.get("name") or "")
            code = str(line.get("code") or "")
            name = self._line_name(raw)
            eps, tks = [], []
            for ep_i, seg in enumerate(str(line.get("url") or "").split("#")):
                if not seg:
                    continue
                if "$" in seg:
                    ep_name, tk = seg.split("$", 1)
                else:
                    ep_name, tk = seg, ""
                if not ep_name:
                    continue
                # 播放 id: 线路码|tk票根
                eps.append(ep_name + "$" + code + "|" + tk)
                tks.append(tk)
            if not eps:
                continue
            rows.append({"index": idx, "name": name, "raw_name": raw,
                         "code": code, "eps": eps, "tks": tks})

        # 稳定排序:命中 line_priority 的线路按优先级顺序置顶,
        # 其余线路权重相同,保持服务端原有顺序排到最后
        rows.sort(key=lambda r: self._line_order(r["name"]))

        play_from, play_url, self._lines = [], [], []
        self._tkmap = {}
        for ln in rows:
            self._lines.append({"index": ln["index"], "name": ln["name"],
                                "raw_name": ln["raw_name"],
                                "code": ln["code"], "tks": ln["tks"]})
            play_from.append(ln["name"] or ln["code"])
            play_url.append("#".join(ln["eps"]))
            for ep_i, tk in enumerate(ln["tks"]):
                self._tkmap[tk] = {"name": ln["name"], "code": ln["code"], "ep": ep_i}

        if not play_url and vi.get("vod_play_url"):
            play_from = [vi.get("vod_play_from") or "线路"]
            play_url = [vi.get("vod_play_url")]

        return {"list": [{
            "vod_id": vid,
            "vod_name": str(vi.get("vod_name") or ""),
            "vod_pic": str(vi.get("vod_pic") or ""),
            "vod_actor": str(vi.get("vod_actor") or ""),
            "vod_director": str(vi.get("vod_director") or ""),
            "vod_year": str(vi.get("vod_year") or ""),
            "vod_area": str(vi.get("vod_area") or ""),
            "vod_lang": str(vi.get("vod_lang") or ""),
            "vod_class": str(vi.get("vod_class") or ""),
            "vod_state": str(vi.get("vod_state") or ""),
            "vod_total": str(vi.get("vod_total") or ""),
            "vod_serial": str(vi.get("vod_serial") or ""),
            "vod_remarks": str(vi.get("vod_remarks") or ""),
            "vod_content": str(vi.get("vod_content") or vi.get("vod_blurb") or ""),
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }]}

    # ================================================================= 播放
    def _decode_ticket(self, ticket):
        """play_ticket 第一段是 base64url 明文 JSON"""
        try:
            seg = ticket.split(".")[0]
            seg += "=" * (-len(seg) % 4)
            return json.loads(base64.urlsafe_b64decode(seg).decode("utf-8", "replace"))
        except Exception:
            return None

    def _ticket(self, tk):
        """tk -> play_ticket"""
        r = self._post("/api/v1/vod/ticket", {"token": tk},
                       headers=self._sign_headers("/api/v1/vod/ticket"))
        if r.get("code") == 1 and isinstance(r.get("data"), dict):
            return r["data"].get("ticket")
        return None

    def _resolve(self, tk):
        """play_ticket -> 真实播放地址"""
        ticket = self._ticket(tk)
        if not ticket:
            return None, "换票失败"
        pl = self._decode_ticket(ticket)
        if not pl:
            return None, "票据解析失败"
        d = pl.get("data") or {}
        api = str(d.get("parse_api") or "").replace("\\u00026", "&")
        du = str(d.get("url") or "")
        if not api or not du:
            return None, "无解析配置"

        # ① 服务端本地解析(相对路径)
        if api.startswith("/"):
            full = self.base + api + urllib.parse.quote(du, safe="")
            code, text = self._get_text(full)
            j = self._try_json(text)
            if isinstance(j, dict):
                if j.get("url"):
                    return j["url"], ""
                msg = str(j.get("system") or j.get("msg") or "解析失败")
                return None, msg
            if code == 200 and text.startswith("http"):
                return text.strip(), ""
            return None, "解析失败(%s)" % code

        # ② 外部解析接口
        if "{md5}" in api:
            target = api.replace("{md5}", du)
        elif "url=" in api:
            target = api + urllib.parse.quote(du, safe="")
        else:
            target = api + du
        code, text = self._get_text(target)
        j = self._try_json(text)
        if isinstance(j, dict):
            if j.get("url"):
                return j["url"], ""
            return None, str(j.get("msg") or "外部解析失败")
        if code == 200 and text.startswith("http"):
            return text.strip(), ""
        return None, "外部解析失败(%s)" % code

    @staticmethod
    def _try_json(text):
        try:
            t = (text or "").strip()
            if t.startswith("{") or t.startswith("["):
                return json.loads(t)
        except Exception:
            return None
        return None

    def playerContent(self, flag, id, vipFlags=None):
        self._ensure_session()
        if not id:
            return {"parse": 0, "url": "", "header": {}}
        code, tk = "", id
        if "|" in id:
            code, tk = id.split("|", 1)

        # 1) 优先按当前线路解析
        url, err = self._resolve(tk)

        # 2) 当前线路失败(付费/失效/超时)→ 自动降级到其它线路的同一集
        if not url and self.cfg.get("auto_fallback", 1):
            cur = self._tkmap.get(tk) or {}
            ep = cur.get("ep", 0)
            for ln in self._lines:
                if ln.get("code") == code:
                    continue
                tks = ln.get("tks") or []
                if ep >= len(tks):
                    continue
                u2, _e2 = self._resolve(tks[ep])
                if u2:
                    url = u2
                    err = ""
                    break

        if url:
            return {"parse": 0, "url": url, "header": {
                "User-Agent": self.cfg.get("user_agent", "okhttp/3.12.1"),
                "Referer": "https://www.google.com/",
            }}
        return {"parse": 0, "url": "", "header": {}, "msg": err or "播放失败"}


if __name__ == "__main__":
    s = Spider()
    s.init("")
    print("name    :", s.getName())
    print("device  :", s.device_id)
    print("jwt     :", (s.jwt or "")[:36], "...")
    print("session :", s.session_id)

    h = s.homeContent(False)
    print("\n分类    :", [(c["type_id"], c["type_name"]) for c in h.get("class", [])])
    fl = (h.get("filters") or {}).get("2") or []
    print("筛选项  :", ["%s(%s项)" % (g["name"], len(g["value"])) for g in fl])
    s.cfg["filter_scan_pages"] = 5   # 自检只扫 5 页,避免打太多请求触发限流
    for ext in ({"class": "古装"}, {"area": "香港"}, {"class": "爱情", "year": "2026"}):
        f = s.categoryContent("2", 1, True, ext)
        md = f.get("msg_data") or {}
        got = ["%s[%s|%s|%s]" % (x["vod_name"][:10], x.get("vod_class"),
                                 x.get("vod_area"), x.get("vod_year"))
               for x in f.get("list", [])[:3]]
        print("筛选%s -> 命中%s条/第1页%s条 | %s" % (
            json.dumps(ext, ensure_ascii=False), f.get("total"), len(f.get("list", [])),
            "; ".join(got)))
        if md.get("note"):
            print("        ", md["note"])

    c = s.categoryContent("2", 1, False, {})
    print("连续剧  :", len(c.get("list", [])), "条 / 共", c.get("total"))
    if c.get("list"):
        print("  首条  :", c["list"][0]["vod_name"])

    s2 = s.searchContent("交锋", False)
    print("搜索交锋:", len(s2.get("list", [])), "条")

    vid = (s2.get("list") or c.get("list") or [{}])[0].get("vod_id")
    if vid:
        d = s.detailContent([vid])
        if d.get("list"):
            dd = d["list"][0]
            names = dd["vod_play_from"].split("$$$")
            eps = dd["vod_play_url"].split("$$$")
            print("\n详情    :", dd["vod_name"], "| 线路:", names)
            print("归类对照:", " | ".join(
                "%s←%s" % (x["name"], x.get("raw_name") or x["name"]) for x in s._lines))
            for i, nm in enumerate(names):
                ep = eps[i].split("#")[0]
                p = s.playerContent(nm, ep)
                u = p.get("url") or ""
                print("  [%s] → %s" % (nm, (u[:96] + "...") if len(u) > 96 else (u or p.get("msg", ""))))
