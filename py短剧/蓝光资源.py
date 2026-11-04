#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
蓝光资源 (TVBox / CatVod Python Spider) - 改良版

相对原版的主要变更
  修正:
    * pagecount/total 解析失败不再清空整个列表
    * 查无资料时 detailContent 回传空列表,不再回传假资料
    * 不再把 null 变成字串 "None"
    * _resolve_stream 各阶段独立容错(playSources 解析失败仍会尝试 normalPlayUrl)
    * 以括号配对 + 正则取代脆弱的 `[^\\]]+`,不再依赖严格 JSON
    * domain 跟随 demo_host 设定,不再硬编码
    * URL 拼接自动判断 ? / &,参数做 quote
    * 解析失败不再回退给嗅探(parse=1),改回传空 url 让 App 明确报错
    * 保留真实演员/导演/简介,品牌字样改为可选 (brand)
    * 清除未使用的 import / 变数 / 死码
  新增:
    * 多网域备援(api / parse_host 可为字串或列表,记住上次成功者)
    * TTL 快取(首页 / 分类 / 搜寻 / 详情 / 解析结果)
    * 年份筛选(使用来源 API 的 year= 参数,由伺服器筛选)
    * 分类自动从 API (ac=list) 读取,失败时退回内建分类
    * 自动侦测 API 是否支援 limit / pagesize,支援则加大每页笔数
    * 搜寻加速:只查一次(简体),仅在无结果时才并行尝试繁体 / 原文
    * 繁简搜寻(优先使用 opencc / zhconv,否则用内建常用字对照)
    * 搜寻结果依名称相似度排序、quick 模式限制笔数
    * 首页推荐(最新更新)
    * 线路排序、集数整理(去除无效集、预告花絮排最后、重名自动编号)
    * debug 日志开关、整体解析时限、重试退避
    * action:clear_cache / check(健康检查)

init(extend) 可用设定(JSON 字串或 dict,皆为选填):
    {
      "api": "https://lgapi.xyz"  或  ["https://a", "https://b"],
      "parse_host": 同上,
      "demo_host": "https://yanshi.lgzyz.xyz",
      "host": "https://lgzyz.xyz",
      "debug": false,          # 开启后把日志写到 stderr
      "brand": false,          # true = 还原原版的品牌前缀 / 简介前缀
      "timeout": 8,            # 单次请求逾时(秒)
      "retries": 2,            # 单一网址重试次数
      "cache": true,           # 是否启用快取
      "insecure_ssl": true,    # false = 验证 SSL 凭证
      "stream_referer": "",    # 非空时,播放时附带此 Referer
      "auto_category": true,   # 自动读取 API 分类(失败会退回内建分类)
      "all_parents": ["1"],    # 这些上层分类提供「全部XX」选项(t=上层ID 会含子分类)
      "page_size": 40          # 每页笔数;0 = 不调整。仅在 API 实测支援时生效
    }

关于筛选:只保留来源 API 实测支援的「年份」(year=2025,由伺服器筛选,
结果完整、分页准确)。地区、排序等来源会忽略的参数一律不提供。
来源预设排序为「最近更新优先」。
"""

import sys
import re
import json
import time
import ssl
import hmac
import hashlib
import urllib.request
import http.cookiejar
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, quote

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"

# --------------------------------------------------------------------------
# 繁简转换:优先 opencc / zhconv,否则使用内建常用字对照
# --------------------------------------------------------------------------
_PAIRS = (
    "蓝藍 资資 线線 体體 乐樂 龙龍 时時 间間 门門 风風 电電 视視 剧劇 动動 战戰 恋戀 爱愛 国國 "
    "闪閃 离離 总總 现現 宝寶 场場 岁歲 无無 华華 万萬 与與 专專 业業 东東 丝絲 两兩 个個 为為 "
    "丽麗 义義 习習 乡鄉 书書 买買 乱亂 争爭 云雲 亚亞 产產 亲親 从從 仓倉 们們 优優 会會 传傳 "
    "伤傷 侠俠 儿兒 兰蘭 关關 兴興 养養 军軍 农農 冲衝 冻凍 凤鳳 击擊 刘劉 则則 创創 别別 剑劍 "
    "办辦 务務 劳勞 势勢 区區 医醫 单單 卖賣 卫衛 历歷 压壓 县縣 参參 发發 变變 叶葉 号號 吗嗎 "
    "员員 响響 团團 园園 图圖 圣聖 坏壞 坚堅 声聲 备備 复復 头頭 夺奪 奖獎 妇婦 妈媽 孙孫 学學 "
    "宁寧 实實 宠寵 审審 宫宮 宽寬 将將 尔爾 层層 属屬 岛島 币幣 帅帥 师師 带帶 帮幫 广廣 庆慶 "
    "库庫 应應 开開 张張 强強 归歸 当當 录錄 态態 惊驚 户戶 护護 报報 择擇 数數 断斷 旧舊 显顯 "
    "杀殺 杂雜 权權 条條 来來 杨楊 极極 标標 样樣 桥橋 欢歡 欧歐 残殘 毕畢 气氣 汉漢 没沒 济濟 "
    "满滿 灯燈 灵靈 灾災 热熱 爷爺 独獨 猎獵 环環 画畫 盘盤 码碼 确確 礼禮 种種 积積 称稱 笔筆 "
    "简簡 红紅 级級 纪紀 约約 纯純 纷紛 纸紙 终終 经經 结結 给給 绝絕 统統 继繼 绿綠 编編 网網 "
    "罗羅 职職 联聯 胜勝 艺藝 节節 苏蘇 药藥 获獲 营營 见見 观觀 规規 览覽 觉覺 计計 订訂 认認 "
    "让讓 记記 讲講 许許 设設 访訪 证證 评評 识識 诉訴 词詞 试試 诗詩 话話 该該 详詳 说說 请請 "
    "谁誰 调調 谈談 谢謝 负負 财財 败敗 货貨 质質 购購 贵貴 费費 赛賽 赢贏 转轉 轻輕 辈輩 输輸 "
    "边邊 达達 迁遷 过過 运運 还還 这這 进進 远遠 连連 适適 选選 递遞 遗遺 邮郵 针針 钱錢 铁鐵 "
    "银銀 错錯 镇鎮 镜鏡 长長 闭閉 问問 闲閒 闹鬧 闻聞 阳陽 阴陰 际際 陆陸 陈陳 险險 随隨 隐隱 "
    "难難 静靜 韩韓 页頁 顶頂 项項 顺順 须須 顾顧 预預 领領 题題 颜顏 额額 飞飛 饭飯 马馬 驱驅 "
    "验驗 鱼魚 鸟鳥 鸡雞 鸭鴨 鹤鶴 麦麥 黄黃 齐齊 龄齡 龟龜"
)
_S2T = {}
_T2S = {}
for _p in _PAIRS.split():
    if len(_p) == 2:
        _S2T[_p[0]] = _p[1]
        _T2S[_p[1]] = _p[0]

_OPENCC = {}


def _convert(text, mode):
    """mode: 't2s' 或 's2t'。回传转换后的字串。"""
    try:
        if mode not in _OPENCC:
            try:
                import opencc  # type: ignore
                _OPENCC[mode] = opencc.OpenCC(mode).convert
            except Exception:
                try:
                    from zhconv import convert as _zc  # type: ignore
                    _OPENCC[mode] = (lambda t, _m=("zh-cn" if mode == "t2s" else "zh-tw"): _zc(t, _m))
                except Exception:
                    table = _T2S if mode == "t2s" else _S2T
                    _OPENCC[mode] = (lambda t, _tb=table: "".join(_tb.get(c, c) for c in t))
        return _OPENCC[mode](text)
    except Exception:
        return text


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------
def _s(v, default=""):
    """安全转字串:None -> default,其余 strip。"""
    if v is None:
        return default
    return str(v).strip()


def _to_int(v, default=0):
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _as_list(v):
    if isinstance(v, (list, tuple)):
        return [str(x).strip().rstrip("/") for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip().rstrip("/")]
    return []


def format_remarks(brand="", meta=""):
    clean_meta = re.sub(r"[\r\n\t]+", " ", _s(meta)).strip()
    if brand and clean_meta:
        return "%s | %s" % (brand, clean_meta)
    return clean_meta or brand


_TAG_RE = re.compile(r"<[^>]+>")
_TRAILER_RE = re.compile(r"预告|預告|花絮|片段|trailer|teaser", re.I)


class Spider(SpiderBase):
    VERSION = "2026.11.03-f"

    def __init__(self):
        super(Spider, self).__init__()
        self.siteName = "蓝光资源"
        self.host = "https://lgzyz.xyz"
        self.apiHosts = ["https://lgapi.xyz"]
        self.parseHosts = ["https://vv00.xyz"]
        self.demo_host = "https://yanshi.lgzyz.xyz"
        self.brandActor = "🦋 TG群: @tvshare23"
        self.brandDirector = "🦋 蝴蝶影视"
        self._ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        # 可由 init 调整
        self.debug = False
        self.brand = False
        self.timeout = 8
        self.retries = 2
        self.use_cache = True
        self.insecure_ssl = True
        self.stream_referer = ""
        self.resolve_deadline = 25
        self.auto_category = True
        self.all_parents = {"1"}
        self.page_size = 40
        self._dyn = None          # (过期时间, classes, filters)
        self._limit_qs = None     # None=未侦测, ""=不支援, "&limit=40"=支援

        self._cache = {}
        self._pref = {"api": 0, "parse": 0}
        self.ctx = self._make_ctx()
        self._jar = http.cookiejar.CookieJar()
        self._opener = self._make_opener()

        self._classes = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "13", "type_name": "连续剧"},
            {"type_id": "53", "type_name": "动漫"},
            {"type_id": "57", "type_name": "综艺"},
            {"type_id": "61", "type_name": "体育赛事"},
            {"type_id": "65", "type_name": "短剧"},
            {"type_id": "51", "type_name": "电影解说"},
            {"type_id": "52", "type_name": "预告片"}
        ]

        self._sub_filters = {
            "1": ("1", [
                ("全部电影", "1"), ("动作片", "6"), ("喜剧片", "7"), ("科幻片", "8"),
                ("恐怖片", "9"), ("爱情片", "10"), ("剧情片", "11"), ("战争片", "12"),
                ("惊悚片", "36"), ("悬疑片", "37"), ("家庭片", "38"), ("犯罪片", "39"),
                ("灾难片", "40"), ("古装片", "41"), ("历史片", "42"), ("纪录片", "20"),
                ("动画片", "21")]),
            "13": ("13", [
                ("国产剧", "13"), ("欧美剧", "14"), ("香港剧", "15"), ("韩国剧", "16"),
                ("台湾剧", "22"), ("日本剧", "23"), ("海外剧", "24"), ("泰国剧", "25")]),
            "53": ("53", [
                ("国产动漫", "53"), ("日韩动漫", "54"), ("欧美动漫", "55"),
                ("海外动漫", "56"), ("港台动漫", "73"), ("动漫电影", "75")]),
            "57": ("57", [
                ("大陆综艺", "57"), ("港台综艺", "58"), ("日韩综艺", "59"), ("欧美综艺", "60")]),
            "61": ("61", [
                ("足球赛事", "61"), ("篮球赛事", "62"), ("斯诺克", "63"), ("网球赛事", "64")]),
            "65": ("65", [
                ("重生民国", "65"), ("穿越年代", "66"), ("反转爽剧", "67"), ("女恋总裁", "70"),
                ("闪婚离婚", "69"), ("都市脑洞", "71"), ("古装仙侠", "72"), ("现代言情", "74")]),
        }
        self._filters = self._build_filters(self._classes, self._sub_filters)

    # ------------------------------------------------------------------
    # 基础设施
    # ------------------------------------------------------------------
    def _make_ctx(self):
        ctx = ssl.create_default_context()
        if self.insecure_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _make_opener(self):
        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar),
            urllib.request.HTTPSHandler(context=self.ctx))

    def _log(self, *args):
        if self.debug:
            try:
                sys.stderr.write("[%s] %s\n" % (self.siteName, " ".join(str(a) for a in args)))
            except Exception:
                pass

    def _build_filters(self, classes, sub_filters):
        year_now = time.localtime().tm_year
        years = [{"n": "全部", "v": ""}] + [
            {"n": str(y), "v": str(y)} for y in range(year_now, year_now - 12, -1)]
        result = {}
        for c in classes:
            tid = c["type_id"]
            flt = []
            if tid in sub_filters:
                init_v, items = sub_filters[tid]
                flt.append({"key": "class_sub", "name": "分类", "init": init_v,
                            "value": [{"n": n, "v": v} for n, v in items]})
            flt.append({"key": "year", "name": "年份", "init": "", "value": years})
            result[tid] = flt
        return result

    def init(self, extend=""):
        if extend:
            try:
                cfg = json.loads(extend) if isinstance(extend, str) else extend
                if isinstance(cfg, dict):
                    if cfg.get("host"):
                        self.host = _s(cfg["host"]).rstrip("/")
                    apis = _as_list(cfg.get("api"))
                    if apis:
                        self.apiHosts = apis
                    parses = _as_list(cfg.get("parse_host"))
                    if parses:
                        self.parseHosts = parses
                    if cfg.get("demo_host"):
                        self.demo_host = _s(cfg["demo_host"]).rstrip("/")
                    if "debug" in cfg:
                        self.debug = bool(cfg["debug"])
                    if "brand" in cfg:
                        self.brand = bool(cfg["brand"])
                    if "timeout" in cfg:
                        self.timeout = max(2, _to_int(cfg["timeout"], 8))
                    if "retries" in cfg:
                        self.retries = max(1, _to_int(cfg["retries"], 2))
                    if "cache" in cfg:
                        self.use_cache = bool(cfg["cache"])
                    if "insecure_ssl" in cfg:
                        self.insecure_ssl = bool(cfg["insecure_ssl"])
                        self.ctx = self._make_ctx()
                        self._opener = self._make_opener()
                    if "auto_category" in cfg:
                        self.auto_category = bool(cfg["auto_category"])
                    if "all_parents" in cfg:
                        self.all_parents = set(str(x) for x in (cfg["all_parents"] or []))
                    if "page_size" in cfg:
                        self.page_size = max(_to_int(cfg["page_size"], 40), 0)
                    if cfg.get("stream_referer"):
                        self.stream_referer = _s(cfg["stream_referer"])
                    self._pref = {"api": 0, "parse": 0}
                    self._dyn = None
                    self._limit_qs = None
            except Exception as e:
                self._log("init config error:", e)
        return True

    def getName(self):
        return self.siteName

    def isVideoFormat(self, url):
        if not url:
            return False
        clean = url.split("?")[0].lower()
        return any(clean.endswith(ext) for ext in (".m3u8", ".mp4", ".ts"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self._cache = {}
        self._dyn = None
        self._limit_qs = None

    # ------------------------------------------------------------------
    # 快取
    # ------------------------------------------------------------------
    def _cget(self, key):
        if not self.use_cache:
            return None
        entry = self._cache.get(key)
        if entry:
            if entry[0] > time.time():
                return entry[1]
            self._cache.pop(key, None)
        return None

    def _cset(self, key, value, ttl):
        if not self.use_cache or ttl <= 0 or not value:
            return
        if len(self._cache) >= 500:
            now = time.time()
            for k in [k for k, v in self._cache.items() if v[0] <= now]:
                self._cache.pop(k, None)
            if len(self._cache) >= 500:
                for k in sorted(self._cache, key=lambda x: self._cache[x][0])[:250]:
                    self._cache.pop(k, None)
        self._cache[key] = (time.time() + ttl, value)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def _http(self, url, data=None, headers=None, timeout=None, retries=None):
        h = {"User-Agent": self._ua, "Accept-Encoding": "identity"}
        if data is not None:
            h["Content-Type"] = "application/json"
        if headers:
            h.update(headers)
        timeout = timeout or self.timeout
        retries = retries or self.retries
        for attempt in range(retries):
            t0 = time.time()
            try:
                req = urllib.request.Request(url, data=data, headers=h)
                with self._opener.open(req, timeout=timeout) as resp:
                    text = resp.read().decode("utf-8", "ignore")
                self._log("OK  %.2fs %s" % (time.time() - t0, url))
                return text
            except Exception as e:
                self._log("ERR %.2fs %s -> %s" % (time.time() - t0, url, e))
                if attempt + 1 < retries:
                    time.sleep(0.3 * (attempt + 1))
        return ""

    def _http_get(self, url, headers=None, timeout=None, retries=None):
        return self._http(url, None, headers, timeout, retries)

    def _http_post_json(self, url, data_dict, headers=None, timeout=None):
        body = json.dumps(data_dict, separators=(",", ":")).encode("utf-8")
        return self._http(url, body, headers, timeout)

    @staticmethod
    def _loads(txt):
        if not txt:
            return None
        try:
            return json.loads(txt.lstrip("\ufeff"))
        except Exception:
            return None

    def _ordered(self, hosts, kind):
        if not hosts:
            return []
        i = self._pref.get(kind, 0) % len(hosts)
        return hosts[i:] + hosts[:i]

    def _mark_ok(self, hosts, kind, host):
        try:
            self._pref[kind] = hosts.index(host)
        except ValueError:
            pass

    def _api(self, path, ttl=0, retries=None, timeout=None):
        """依序尝试各 API 网域,取得 JSON(dict)。成功会记住该网域。"""
        ck = "api:" + path
        cached = self._cget(ck)
        if cached is not None:
            return cached
        for base in self._ordered(self.apiHosts, "api"):
            data = self._loads(self._http_get(base + path, timeout=timeout, retries=retries))
            if isinstance(data, dict):
                self._mark_ok(self.apiHosts, "api", base)
                self._cset(ck, data, ttl)
                return data
        return {}

    # ------------------------------------------------------------------
    # 列表 / 卡片
    # ------------------------------------------------------------------
    def _brand_prefix(self):
        return self.brandDirector if self.brand else ""

    @staticmethod
    def _year_of(it):
        for field in ("vod_year", "vod_pubdate"):
            m = re.search(r"(?:19|20)\d{2}", _s(it.get(field)))
            if m:
                return int(m.group(0))
        return 0

    def _match(self, it, year):
        """年份校验:来源若忽略 year 参数,避免混入其他年份。"""
        if not year:
            return True
        return str(self._year_of(it)) == year

    def _build_cards(self, items, year=""):
        cards = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            v_id = _s(it.get("vod_id"))
            v_name = _s(it.get("vod_name"))
            if not v_id or not v_name:
                continue
            if not self._match(it, year):
                continue
            cards.append({
                "vod_id": v_id,
                "vod_name": v_name,
                "vod_pic": _s(it.get("vod_pic")),
                "vod_remarks": format_remarks(self._brand_prefix(), it.get("vod_remarks")),
                "style": {"type": "rect", "ratio": 0.75}
            })
        return cards

    @staticmethod
    def _page_result(data, page, cards):
        if not cards:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}
        pagecount = max(_to_int(data.get("pagecount"), page), 1)
        total = _to_int(data.get("total"), 0)
        if total <= 0:
            total = pagecount * len(cards)
        return {"list": cards, "page": page, "pagecount": pagecount,
                "limit": len(cards), "total": total}

    @staticmethod
    def _page_num(pg):
        return max(_to_int(pg, 1), 1)

    def _load_categories(self):
        """从 ac=list 建立分类;回传 (classes, sub_filters) 或 None。"""
        if not self.auto_category:
            return None
        data = self._api("/api.php/provide/vod/?ac=list&pg=1", ttl=21600, retries=1, timeout=6)
        rows = data.get("class") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return None
        nodes = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            tid, name = _s(r.get("type_id")), _s(r.get("type_name"))
            pid = _s(r.get("type_pid")) or "0"
            if tid and name:
                nodes.append((tid, pid, name))
        if len(nodes) < 3:
            return None
        ids = set(n[0] for n in nodes)
        children = {}
        for tid, pid, name in nodes:
            children.setdefault(pid, []).append((name, tid))   # (名称, ID)

        classes, subs = [], {}
        for tid, pid, name in nodes:
            if pid != "0" and pid in ids:
                continue                      # 非顶层
            kids = children.get(tid, [])
            if not kids:
                classes.append({"type_id": tid, "type_name": name})
                continue
            if tid in self.all_parents:
                entry, items = tid, [("全部" + name, tid)] + kids
            else:
                entry, items = kids[0][1], kids
            classes.append({"type_id": entry, "type_name": name})
            subs[entry] = (entry, items)
        return (classes, subs) if len(classes) >= 3 else None

    def _ensure_categories(self):
        now = time.time()
        if self._dyn and self._dyn[0] > now:
            return self._dyn[1], self._dyn[2]
        res = None
        try:
            res = self._load_categories()
        except Exception as e:
            self._log("load categories error:", e)
        if res:
            classes, subs = res
            self._dyn = (now + 21600, classes, self._build_filters(classes, subs))
            self._log("分类来源: API (%d 个顶层分类)" % len(classes))
        else:
            self._dyn = (now + 300, self._classes, self._filters)
            self._log("分类来源: 内建")
        return self._dyn[1], self._dyn[2]

    def _detect_limit(self):
        """侦测 API 是否支援 limit / pagesize;回传查询字串(含开头 &)或 ""。"""
        if self._limit_qs is not None:
            return self._limit_qs
        self._limit_qs = ""
        n = self.page_size
        if n <= 0:
            return ""
        try:
            base = self._api("/api.php/provide/vod/?ac=detail&t=1&pg=1", ttl=300, retries=1, timeout=6)
            n0 = len(base.get("list") or [])
            pc0 = _to_int(base.get("pagecount"), 0)
            if n0 == 0 or n <= n0:
                return ""
            for param in ("limit", "pagesize"):
                d = self._api("/api.php/provide/vod/?ac=detail&t=1&pg=1&%s=%d" % (param, n),
                              ttl=300, retries=1, timeout=6)
                ln = len(d.get("list") or [])
                if ln <= n0 or ln > n:
                    continue
                pc, total = _to_int(d.get("pagecount"), 0), _to_int(d.get("total"), 0)
                expected = -(-total // ln) if total else 0
                # 页数必须随每页笔数一起变化,否则翻页会错乱
                if pc and expected and abs(pc - expected) <= 1 and (not pc0 or pc < pc0):
                    self._limit_qs = "&%s=%d" % (param, n)
                    self._log("每页笔数参数: %s (实际 %d 笔/页)" % (self._limit_qs, ln))
                    break
            if not self._limit_qs:
                self._log("API 不支援 limit / pagesize,维持预设每页笔数")
        except Exception as e:
            self._log("detect limit error:", e)
        return self._limit_qs

    def homeContent(self, filter):
        with ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(self._ensure_categories)
            f2 = ex.submit(self._detect_limit)
            classes, filters = f1.result()
            f2.result()
        result = {"class": classes}
        if filter:
            result["filters"] = filters
        return result

    def homeVideoContent(self):
        data = self._api("/api.php/provide/vod/?ac=detail&pg=1", ttl=300)
        cards = self._build_cards(data.get("list"))
        return {"list": cards[:20]}

    def categoryContent(self, tid, pg, filter, extend):
        page = self._page_num(pg)
        target = _s(tid)
        year = ""
        if isinstance(extend, dict):
            sub = _s(extend.get("class_sub"))
            if sub.isdigit():
                target = sub
            year = _s(extend.get("year"))
            if not year.isdigit():
                year = ""

        path = "/api.php/provide/vod/?ac=detail&t=%s&pg=%d" % (quote(target, safe=""), page)
        if year:
            path += "&year=%s" % year
        path += self._detect_limit()
        data = self._api(path, ttl=300)
        cards = self._build_cards(data.get("list"), year)
        return self._page_result(data, page, cards)

    # ------------------------------------------------------------------
    # 详情
    # ------------------------------------------------------------------
    def _organize_lines(self, raw_from, raw_url):
        froms = raw_from.split("$$$") if raw_from else []
        urls = raw_url.split("$$$") if raw_url else []
        if len(froms) != len(urls):
            self._log("play_from/play_url 数量不一致:", len(froms), len(urls))

        lines = []
        for name, group in zip(froms, urls):
            name = name.strip() or "线路"
            if "lgzym3u8" in name.lower():
                name = "蝴蝶专线"
            eps = []
            for ep in group.split("#"):
                ep = ep.strip()
                if not ep:
                    continue
                if "$" in ep:
                    ep_name, ep_url = ep.split("$", 1)
                    ep_name = ep_name.strip() or "正片"
                else:
                    ep_name, ep_url = "正片", ep
                ep_url = ep_url.strip()
                if not ep_url:
                    continue
                eps.append((ep_name, ep_url))
            if not eps:
                continue
            # 预告 / 花絮排最后(稳定排序,不动其他集数顺序)
            eps.sort(key=lambda x: 1 if _TRAILER_RE.search(x[0]) else 0)
            lines.append((name, eps))

        # 线路:蝴蝶专线优先
        lines.sort(key=lambda x: 0 if x[0] == "蝴蝶专线" else 1)

        # 线路重名自动编号
        seen = {}
        out_from, out_url = [], []
        for name, eps in lines:
            seen[name] = seen.get(name, 0) + 1
            shown = name if seen[name] == 1 else "%s%d" % (name, seen[name])
            out_from.append(shown)
            out_url.append("#".join("%s$%s" % (n, u) for n, u in eps))
        return "$$$".join(out_from), "$$$".join(out_url)

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        raw_id = _s(raw_id).split(",")[0].strip()
        if not raw_id:
            return {"list": []}

        data = self._api("/api.php/provide/vod/?ac=detail&ids=%s" % quote(raw_id, safe=""), ttl=1800)
        items = data.get("list") if isinstance(data, dict) else None
        if not items or not isinstance(items[0], dict):
            return {"list": []}
        item = items[0]

        v_name = _s(item.get("vod_name"))
        if not v_name:
            return {"list": []}
        v_pic = _s(item.get("vod_pic"))

        desc = _TAG_RE.sub("", _s(item.get("vod_content"))).strip()
        if desc == "暂无简介":
            desc = ""
        if self.brand:
            if desc:
                desc = "🦋 蝴蝶影视专线直连 | %s | 官方交流群: @tvshare23" % desc
            else:
                desc = "🦋 蝴蝶影视专线加速播放 | 官方TG交流群:@tvshare23"

        play_from, play_url = self._organize_lines(
            _s(item.get("vod_play_from")), _s(item.get("vod_play_url")))

        vod = {
            "vod_id": raw_id,
            "vod_name": v_name,
            "vod_pic": v_pic,
            "vod_bg": v_pic,
            "vod_background": v_pic,
            "vod_banner": v_pic,
            "type_name": _s(item.get("type_name")),
            "vod_year": _s(item.get("vod_year")),
            "vod_area": _s(item.get("vod_area")),
            "vod_actor": _s(item.get("vod_actor")) or self.brandActor,
            "vod_director": _s(item.get("vod_director")) or self.brandDirector,
            "vod_remarks": format_remarks(self._brand_prefix(), item.get("vod_remarks")),
            "vod_content": desc,
            "vod_play_from": play_from,
            "vod_play_url": play_url
        }
        return {"list": [vod]}

    # ------------------------------------------------------------------
    # 解析播放地址
    # ------------------------------------------------------------------
    @staticmethod
    def _balanced(text, start, open_ch="[", close_ch="]"):
        """从 text[start] (应为 open_ch) 起做括号配对,回传含括号的子字串。"""
        if start < 0 or start >= len(text) or text[start] != open_ch:
            return ""
        depth = 0
        quote_ch = ""
        i = start
        while i < len(text):
            c = text[i]
            if quote_ch:
                if c == "\\":
                    i += 1
                elif c == quote_ch:
                    quote_ch = ""
            elif c in ("'", '"'):
                quote_ch = c
            elif c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
            i += 1
        return ""

    def _resolve_stream(self, target_url):
        ck = "play:" + target_url
        cached = self._cget(ck)
        if cached:
            return cached

        deadline = time.time() + self.resolve_deadline
        for base in self._ordered(self.parseHosts, "parse"):
            if time.time() >= deadline:
                self._log("resolve deadline reached")
                break
            try:
                url = self._resolve_with_host(base, target_url, deadline)
            except Exception as e:
                self._log("resolve error on", base, e)
                url = ""
            if url:
                self._mark_ok(self.parseHosts, "parse", base)
                self._cset(ck, url, 1800)
                return url
        return ""

    def _resolve_with_host(self, base, target_url, deadline):
        def tmo():
            return max(2, min(self.timeout, int(deadline - time.time())))

        def expired():
            return time.time() >= deadline

        page_url = "%s?url=%s" % (base, quote(target_url, safe=""))
        html = self._http_get(page_url, headers={"Referer": self.demo_host + "/"}, timeout=tmo())
        if not html:
            return ""

        sess_m = re.search(r"hishow\.php\?session=([a-fA-F0-9]+)", html)
        if not sess_m:
            self._log("no session in parse page")
            return ""
        sess = sess_m.group(1)
        if expired():
            return ""

        js_url = "%s/godoo/hishow.php?session=%s" % (base, sess)
        js_txt = self._http_get(js_url, headers={"Referer": page_url}, timeout=tmo())
        if not js_txt:
            return ""

        if not self._verify_guard(base, page_url, js_txt, sess, tmo):
            self._log("guard verify not accepted (continue anyway)")
        if expired():
            return ""

        vpath = ""
        vurl_m = re.search(r'videoUrl:\s*"([^"]+)"', html)
        if vurl_m:
            vpath = vurl_m.group(1)
        else:
            vj = re.search(r'"videoUrl"\s*:\s*"((?:[^"\\]|\\.)*)"', js_txt)
            if vj:
                vpath = vj.group(1).replace("\\/", "/")
        if not vpath:
            self._log("no videoUrl")
            return ""
        playback_url = vpath if vpath.startswith("http") else base + vpath
        if expired():
            return ""

        pb_html = self._http_get(playback_url, headers={"Referer": page_url}, timeout=tmo())
        if not pb_html:
            return ""

        sep = "&" if "?" in playback_url else "?"

        # 阶段一:specialPlayConfig(独立容错,失败不影响阶段二)
        try:
            url = self._try_special_sources(pb_html, playback_url, sep, tmo)
            if url:
                return url
        except Exception as e:
            self._log("special sources failed:", e)

        # 阶段二:normalPlayUrl
        norm_m = re.search(r"normalPlayUrl:\s*['\"]([^'\"]+)['\"]", pb_html)
        if norm_m:
            norm_url = norm_m.group(1).strip()
            if norm_url.startswith("http"):
                return norm_url
        return ""

    def _verify_guard(self, base, page_url, js_txt, sess, tmo):
        """送出 boom.php 验证。新版:{payload, nonce};旧版:{payload, signature}(HMAC)。"""
        rand_keys, core_keys = [], []
        for name, out in (("RANDOM_INDICATORS", rand_keys), ("CORE_INDICATORS", core_keys)):
            idx = js_txt.find(name)
            if idx >= 0:
                arr = self._balanced(js_txt, js_txt.find("[", idx))
                out.extend(re.findall(r"['\"]([^'\"]+)['\"]", arr))

        getters = {
            "plugins": "PDF Viewer,Chrome PDF Viewer,Chromium PDF Viewer,Microsoft Edge PDF Viewer,WebKit built-in PDF",
            "mimeTypes": 2,
            "timezone": -480,
            "language": "zh-CN",
            "hardwareConcurrency": 8,
            "deviceMemory": 8,
            "platform": "Win32",
            "audioFingerprint": "48000:2",
            "fontList": "Arial,Helvetica,Times New Roman,Courier New,Segoe UI,Tahoma,Verdana,Microsoft YaHei,SimSun",
            "canvasNoise": "kHCsGeVhQ3Zq0aEw2xBn8m1rTt7yUoPlJd4fS6gXcZ9iNvAeWbMqLhRkYuIoP3sD5tGjHnCvBmXzQwErTyUiOpAsDfGhJkLzXcVbNm" + "MqWeRtYuIoPaSdFgHjKlZxCvBnMASUVORK5CYII=",
            "webglVendor": "WebKit",
            "webglRenderer": "Google Inc. (NVIDIA) / ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 (0x00001F82) Direct3D11 vs_5_0 ps_5_0, D3D11)",
            "touchSupport": 0,
            "screenInfo": "1920x1080x24",
        }
        random_data = {k: getters.get(k, "") for k in rand_keys}
        core_data = {k: getters.get(k, "") for k in core_keys}

        sec_m = re.search(r"var SECRET\s*=\s*['\"]([a-fA-F0-9]+)['\"]", js_txt)
        nonce_m = re.search(r"var NONCE\s*=\s*['\"]([^'\"]+)['\"]", js_txt)
        tok_m = re.search(r"var DEVICE_TOKEN\s*=\s*['\"]([^'\"]+)['\"]", js_txt)

        payload = {
            "sessionId": sess,
            "isTop": True,
            "isRealBrowser": True,
            "isTrusted": False,
            "deviceId": "-1827491203",
        }
        if tok_m:
            payload["deviceToken"] = tok_m.group(1)
        payload["domain"] = urlparse(self.demo_host).netloc
        if core_keys:
            payload["coreIndicators"] = core_data
        payload["randomIndicators"] = random_data

        if nonce_m:
            body = {"payload": payload, "nonce": nonce_m.group(1)}
        elif sec_m:
            payload_str = json.dumps(payload, separators=(",", ":"))
            sig = hmac.new(sec_m.group(1).encode("utf-8"), payload_str.encode("utf-8"),
                           hashlib.sha256).hexdigest()
            body = {"payload": payload, "signature": sig}
        else:
            self._log("guard: neither NONCE nor SECRET found")
            return False

        resp = self._http_post_json(
            "%s/godoo/boom.php" % base, body,
            headers={"Referer": page_url, "Origin": base}, timeout=tmo())
        self._log("boom.php ->", (resp or "")[:200])
        data = self._loads(resp)
        return bool(isinstance(data, dict) and data.get("success"))

    def _try_special_sources(self, pb_html, playback_url, sep, tmo):
        idx = pb_html.find("specialPlayConfig")
        if idx < 0:
            return ""
        sub = pb_html[idx:]
        k = sub.find("playSources")
        if k < 0:
            return ""
        arr = self._balanced(sub, sub.find("[", k))
        if not arr:
            return ""

        macs = []
        for m in re.findall(r"mac_play_source['\"]?\s*:\s*['\"]([^'\"]+)['\"]", arr):
            if m and m not in macs:
                macs.append(m)

        for mac_src in macs:
            if mac_src == "dujia":
                res_url = "%s%sresolve_dujia_plain=1" % (playback_url, sep)
            else:
                res_url = "%s%sresolve_special_plain=1&resolve_source=%s" % (
                    playback_url, sep, quote(mac_src, safe=""))
            res_txt = self._http_get(
                res_url, headers={"Referer": playback_url, "Accept": "application/json"},
                timeout=tmo())
            res_json = self._loads(res_txt)
            if isinstance(res_json, dict):
                stream_url = _s(res_json.get("url"))
                if stream_url.startswith("http"):
                    return stream_url
        return ""

    def playerContent(self, flag, id, vipFlags):
        raw_url = _s(id)
        headers = {"User-Agent": self._ua}
        if self.stream_referer:
            headers["Referer"] = self.stream_referer

        if raw_url.startswith(("http://", "https://")):
            if self.isVideoFormat(raw_url):
                return {"parse": 0, "playUrl": "", "url": raw_url, "header": headers}
            if "lgvideo.xyz" in raw_url:
                resolved = ""
                try:
                    resolved = self._resolve_stream(raw_url)
                except Exception as e:
                    self._log("playerContent resolve error:", e)
                if resolved:
                    return {"parse": 0, "playUrl": "", "url": resolved, "header": headers}
                # 解析失败:明确回传空 url,不要把非网页地址丢给嗅探
                self._log("resolve failed for", raw_url)
                return {"parse": 0, "playUrl": "", "url": "", "header": headers}
            if ".m3u8" in raw_url.lower() or ".mp4" in raw_url.lower():
                return {"parse": 0, "playUrl": "", "url": raw_url, "header": headers}

        return {"parse": 1, "playUrl": "", "url": raw_url, "header": headers}

    # ------------------------------------------------------------------
    # 搜寻
    # ------------------------------------------------------------------
    @staticmethod
    def _rank(name, key_variants):
        n = name.lower()
        best = 3
        for k in key_variants:
            kl = k.lower()
            if n == kl:
                return 0
            if n.startswith(kl):
                best = min(best, 1)
            elif kl in n:
                best = min(best, 2)
        return best

    def searchContent(self, key, quick, pg="1"):
        page = self._page_num(pg)
        key = _s(key)
        if not key:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

        t0 = time.time()

        def spath(kw):
            return "/api.php/provide/vod/?ac=detail&wd=%s&pg=%d" % (quote(kw, safe=""), page)

        # 来源标题几乎都是简体:先只查一次简体(最快)
        primary = _convert(key, "t2s") or key
        variants = [primary]
        results = [self._api(spath(primary), ttl=300, retries=1)]

        # 没结果才并行尝试原文 / 繁体(少见情况,不拖慢一般搜寻)
        if not self._build_cards(results[0].get("list")):
            extra = []
            for v in (key, _convert(key, "s2t")):
                if v and v not in variants and v not in extra:
                    extra.append(v)
            if extra:
                with ThreadPoolExecutor(max_workers=len(extra)) as ex:
                    results += list(ex.map(lambda kw: self._api(spath(kw), ttl=300, retries=1), extra))
                variants += extra

        merged = []
        seen = set()
        pagecount = 1
        total = 0
        for data in results:
            pagecount = max(pagecount, _to_int(data.get("pagecount"), 1))
            total = max(total, _to_int(data.get("total"), 0))
            for card in self._build_cards(data.get("list")):
                if card["vod_id"] not in seen:
                    seen.add(card["vod_id"])
                    merged.append(card)
        self._log("搜寻 %s: %d 笔, %.2fs" % (key, len(merged), time.time() - t0))

        merged.sort(key=lambda c: self._rank(c["vod_name"], variants))  # 稳定排序
        if quick and merged:
            merged = merged[:10]

        if not merged:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}
        return {"list": merged, "page": page, "pagecount": max(pagecount, 1),
                "limit": len(merged), "total": total if total > 0 else len(merged)}

    # ------------------------------------------------------------------
    # 自订动作 / 其他
    # ------------------------------------------------------------------
    def _health_check(self):
        lines = ["版本: %s" % self.VERSION]
        classes, _ = self._ensure_categories()
        src = "API" if self._dyn and self._dyn[1] is not self._classes else "内建"
        lines.append("分类: %s(%d 个): %s" % (src, len(classes), ",".join(c["type_name"] for c in classes)))
        lines.append("每页笔数参数: %s" % (self._detect_limit() or "不支援/未启用"))
        for base in self.apiHosts:
            t0 = time.time()
            data = self._loads(self._http_get(base + "/api.php/provide/vod/?ac=detail&pg=1"))
            ok = isinstance(data, dict) and bool(data.get("list"))
            lines.append("API %s: %s (%.1fs)" % (base, "正常" if ok else "异常", time.time() - t0))
        for base in self.parseHosts:
            t0 = time.time()
            ok = bool(self._http_get(base))
            lines.append("解析 %s: %s (%.1fs)" % (base, "可连线" if ok else "无法连线", time.time() - t0))
        return "\n".join(lines)

    def action(self, action):
        name = _s(action).lower()
        if name in ("clear_cache", "clear", "清除快取", "清除缓存"):
            self._cache = {}
            self._dyn = None
            self._limit_qs = None
            return {"msg": "快取已清除"}
        if name in ("check", "health", "检查", "健康检查"):
            return {"msg": self._health_check()}
        return {"msg": "ok"}

    def liveContent(self):
        return ""

    def localProxy(self, params):
        return [404, "text/plain; charset=utf-8", "Proxy not configured"]
