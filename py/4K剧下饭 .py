# -*- coding: utf-8 -*-
# 剧下饭 TVBox Python 爬虫 - webhomeTV 适配版 (类式规范)
# 站点: http://manian.juxiafan.com/  (内置 8 个备用域名自动轮换)
#
# 本版改动（线路置顶 + 分类筛选版）：
#   1) 详情页线路置顶：江苏4K极速专线 → 山东4K 2160P → 爱尔兰4K高码，其余线路按服务端原顺序排在后面
#   2) 线路名 江苏2K极速专线 统一改成 江苏4K极速专线
#   3) 播放 id 里写入线路位置，改名/重排后仍能精确命中用户点的那条线路（不再退回服务端第一条）
#   4) 【新增】分类筛选：homeContent 返回 filters（类型/地区/年份/语言），
#      categoryContent 接收 extend 并把 classify/area/year 传给服务端 /video/index；
#      服务端 limit 降级(只回2条)或语言/地区写法不匹配时，自动改用 /video/search 扫描 + 本地同义词匹配，
#      保证筛选后仍是完整分页列表，而不是只剩 2 条。

import json
import time
from base64 import b64encode
from urllib.request import Request, urlopen
from urllib.parse import quote_plus, unquote

try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object

BASE_URLS = [
    "http://manian.juxiafan.com",
    "http://195.225.24.128:6213",
    "http://jugaoqing.com",
    "http://jumianfei.com",
    "http://juyongjiu.com",
    "http://kuailezhuiju2.com",
    "http://zhuiju666.com",
    "http://194.147.100.155:7744",
]
AES_KEY = b"kZ6fT8oF6oM8eX6lF7eH2rJ3pW7gW0kC"
UA = "okhttp/4.12.0"

LIVE_TYPE_ID = 22023                 # 隐藏直播分类(服务端不下发, 手动补进分类栏)

# ======================= AES-256-ECB =======================

def _build_sbox():
    sbox = [0] * 256
    p = q = 1
    while True:
        p = p ^ ((p << 1) ^ (0x1B if p & 0x80 else 0)) & 0xFF
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q ^= 0x09 if (q & 0x80) else 0
        q &= 0xFF
        xformed = q ^ ((q << 1) | (q >> 7)) & 0xFF
        xformed = (xformed ^ ((q << 2) | (q >> 6))) & 0xFF
        xformed = (xformed ^ ((q << 3) | (q >> 5))) & 0xFF
        xformed = (xformed ^ ((q << 4) | (q >> 4))) & 0xFF
        sbox[p] = xformed ^ 0x63
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox

_SBOX = _build_sbox()
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36, 0x6C, 0xD8, 0xAB, 0x4D]

def _xtime(a):
    return ((a << 1) ^ (0x1B if a & 0x80 else 0)) & 0xFF

_COL2 = [_xtime(i) for i in range(256)]
_COL3 = [_xtime(i) ^ i for i in range(256)]

def _expand_key(key):
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        temp = list(w[i - 1])
        if i % nk == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[b] for b in temp]
            temp[0] ^= _RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            temp = [_SBOX[b] for b in temp]
        w.append([w[i - nk][j] ^ temp[j] for j in range(4)])
    return w, nr

def _encrypt_block(block, w, nr):
    def _rk(r):
        return [x for word in w[r * 4:(r * 4) + 4] for x in word]
    s = list(block)
    rk0 = _rk(0)
    for j in range(16):
        s[j] ^= rk0[j]
    for r in range(1, nr):
        s = [_SBOX[b] for b in s]
        s = [s[0], s[5], s[10], s[15],
             s[4], s[9], s[14], s[3],
             s[8], s[13], s[2], s[7],
             s[12], s[1], s[6], s[11]]
        t = [0] * 16
        for c in range(4):
            i = c * 4
            a0, a1, a2, a3 = s[i], s[i + 1], s[i + 2], s[i + 3]
            t[i] = _COL2[a0] ^ _COL3[a1] ^ a2 ^ a3
            t[i + 1] = a0 ^ _COL2[a1] ^ _COL3[a2] ^ a3
            t[i + 2] = a0 ^ a1 ^ _COL2[a2] ^ _COL3[a3]
            t[i + 3] = _COL3[a0] ^ a1 ^ a2 ^ _COL2[a3]
        s = t
        rk = _rk(r)
        s = [s[j] ^ rk[j] for j in range(16)]
    s = [_SBOX[b] for b in s]
    s = [s[0], s[5], s[10], s[15],
         s[4], s[9], s[14], s[3],
         s[8], s[13], s[2], s[7],
         s[12], s[1], s[6], s[11]]
    rk = _rk(nr)
    s = [s[j] ^ rk[j] for j in range(16)]
    return bytes(s)

def _aes256_ecb_encrypt(plain, key):
    w, nr = _expand_key(key)
    out = bytearray()
    for i in range(0, len(plain), 16):
        out += _encrypt_block(bytes(plain[i:i + 16]), w, nr)
    return bytes(out)

def _aes_encrypt(plaintext, key=AES_KEY):
    """PKCS7 填充 + AES-256-ECB -> base64 (多后端, 输出一致)"""
    data = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext
    pad = 16 - len(data) % 16
    data = data + bytes([pad]) * pad
    try:
        from Crypto.Cipher import AES
        return b64encode(AES.new(key, AES.MODE_ECB).encrypt(data)).decode()
    except Exception:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher as _C
            from cryptography.hazmat.primitives.ciphers.algorithms import AES as _AES
            from cryptography.hazmat.primitives.ciphers.modes import ECB as _ECB
            from cryptography.hazmat.backends import default_backend as _B
            enc = _C(_AES(key), _ECB(), backend=_B()).encryptor()
            return b64encode(enc.update(data) + enc.finalize()).decode()
        except Exception:
            return b64encode(_aes256_ecb_encrypt(data, key)).decode()

# ======================= HTTP / 签名 =======================

def _http(method, url, body=None, content_type=None, timeout=12):
    headers = {"User-Agent": UA}
    data = None
    if body is not None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        headers["Content-Length"] = str(len(data))
    if content_type:
        headers["Content-Type"] = content_type
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")

def _sign(concat):
    return _aes_encrypt(concat)

def _fix_host(host):
    if host is None or (isinstance(host, str) and host.strip() == ""):
        host = BASE_URLS[0]
    return str(host).rstrip("/")

def _post(host, path, body=None, content_type=None):
    urls = []
    h = _fix_host(host)
    if h not in urls:
        urls.append(h)
    for b in BASE_URLS:
        if b not in urls:
            urls.append(b)
    last = "{}"
    for u in urls:
        try:
            last = _http("POST", u + path, body, content_type)
            if '"code"' in last:
                return last
        except Exception:
            continue
    return last

def _get(url, timeout=12):
    try:
        return _http("GET", url, timeout=timeout)
    except Exception:
        return "{}"

def _post_form(host, path, params):
    ts = str(int(time.time()))
    params["timestamp"] = ts
    items = sorted(params.items())
    concat = "&".join(k + "=" + quote_plus(str(v)) for k, v in items)
    ds = _sign(concat)
    form = "&".join(k + "=" + quote_plus(str(v)) for k, v in items)
    form += "&datasign=" + quote_plus(ds)
    return _post(host, path, form, "application/x-www-form-urlencoded")

def _post_json(host, path, params):
    params["timestamp"] = str(int(time.time()))
    items = sorted(params.items())
    concat = "&".join(k + "=" + str(v) for k, v in items)
    ds = _sign(concat)
    obj = dict(items)
    obj["datasign"] = ds
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return _post(host, path, body, "application/json;charset=UTF-8")

# ======================= 分类筛选参数 =======================

# 筛选栏四组(顺序即弹窗内顺序)：key 是播放器 extend 的字段名
FILTER_GROUPS = [
    ("class", "类型"),
    ("area", "地区"),
    ("year", "年份"),
    ("lang", "语言"),
]
# extend 的 key -> 服务端 /video/index 的查询参数；lang 服务端不支持, 只做本地匹配
SERVER_DIM = {"class": "classify", "area": "area", "year": "year"}

MAX_OPTIONS = 32          # 每组最多多少个候选(年份过长时截断)
PAGE_LIMIT = 20           # 返回给播放器的每页条数
SCAN_MAX_PAGE = 40        # 本地扫描模式: 同一筛选条件最多扫描多少页(40页≈1600条)
MAX_WORKERS = 10          # 并发抓页线程数
_CACHE_TTL = 180          # 扫描/页缓存有效期(秒)

# 地区同义词: 服务端 extend 写的是大区(欧美/大陆), 真实数据是国家(美国/英国/中国大陆)
AREA_SYNONYMS = {
    "欧美": ["欧美", "美国", "英国", "法国", "德国", "西班牙", "加拿大", "意大利", "俄罗斯",
             "澳大利亚", "新西兰", "瑞典", "挪威", "丹麦", "荷兰", "比利时", "奥地利", "瑞士",
             "波兰", "捷克", "希腊", "葡萄牙", "匈牙利", "爱尔兰", "芬兰"],
    "大陆": ["大陆", "内地", "中国", "国产"],
    "中国": ["中国", "中国大陆", "内地", "大陆", "国产"],
    "内地": ["内地", "大陆", "中国大陆", "国产"],
    "香港": ["香港", "中国香港", "港"],
    "中国香港": ["香港", "中国香港"],
    "澳门": ["澳门", "中国澳门"],
    "台湾": ["台湾", "中国台湾", "台湾地区", "台"],
    "中国台湾": ["台湾", "中国台湾", "台湾地区"],
    "韩国": ["韩国", "韩剧", "韩"],
    "日本": ["日本", "日"],
    "泰国": ["泰国", "泰"],
    "新加坡": ["新加坡", "新加坡"],
    "印度": ["印度"],
    "其他": ["其他", "其它", "海外"],
    "其它": ["其它", "其他"],
}
# 语言同义词: 数据里同一语言有 国语/普通话/汉语普通话 多种写法
LANG_SYNONYMS = {
    "国语": ["国语", "普通话", "汉语普通话", "中文", "汉语"],
    "英语": ["英语", "english"],
    "粤语": ["粤语", "广东话", "粤语"],
    "闽南语": ["闽南语", "闽南", "台语"],
    "韩语": ["韩语", "韩语", "朝鲜语"],
    "日语": ["日语", "日本語"],
    "其它": ["其它", "其他"],
    "其他": ["其他", "其它"],
}

def _uniq(seq):
    out, seen = [], set()
    for x in seq:
        x = str(x or "").strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out

def _split_list(s):
    """服务端候选串 -> 值列表(兼容中英文逗号、'·' 保留)"""
    return _uniq(str(s or "").replace("，", ",").split(","))

def _opts(values, with_all=True):
    """转成播放器筛选条目 [{n:显示, v:取值}]，首位为 全部(空值)"""
    arr = ([{"n": "全部", "v": ""}] if with_all else [])
    for v in values[:MAX_OPTIONS]:
        arr.append({"n": v, "v": v})
    return arr

def _build_filters(raw_classes):
    """由 classifies 的 extend 生成 filters: {type_id: [ {key,name,value[]} ]}"""
    filters = {}
    for c in raw_classes:
        tid = str(c.get("id") or "")
        if not tid or tid == str(LIVE_TYPE_ID):
            continue
        ext = c.get("extend") or {}
        groups = []
        for key, label in FILTER_GROUPS:
            vals = _split_list(ext.get(key))
            if key == "area":
                # 地区候选太少(只有大区)时, 补上该分类真实存在的高频国家
                vals = _uniq(vals + _EXTRA_AREA.get(tid, []))
            if key == "class" and not _split_list(ext.get("lang")) and vals:
                # 纪录片把"国语/英语"塞进 class 候选: 按语言处理才筛得动
                if sum(1 for v in vals if v in _LANG_WORDS) * 2 >= len(vals):
                    key, label = "lang", "语言"
                    vals = _uniq(vals + list(_LANG_WORDS))
            if not vals:
                continue
            groups.append({"key": key, "name": label, "value": _opts(vals)})
        if groups:
            filters[tid] = groups
    return filters

# 语言写法集合(用于识别服务端把语言塞进"类型"候选的分类)
_LANG_WORDS = {"国语", "普通话", "汉语普通话", "英语", "粤语", "闽南语", "韩语",
               "日语", "其它", "其他", "泰语", "印度语"}

# 服务端 extend 缺失、但数据里真实存在的高频地区(按分类补充, 保证筛选不空)
# 注: 只补该分类数据里确实有内容的取值, 否则会给出筛了等于空的选项
_EXTRA_AREA = {
    "22016": ["中国大陆"],
    "22017": ["美国", "英国", "法国", "德国", "加拿大", "俄罗斯", "印度", "澳大利亚", "内地"],
    "22018": ["美国", "英国", "法国", "加拿大", "中国"],
    "22019": ["内地"],
    "22020": ["中国大陆"],
    "22021": ["美国", "英国", "法国", "加拿大", "俄罗斯", "内地"],
    "22022": ["美国", "英国", "法国", "德国", "中国大陆"],
}

# ======================= 核心业务 (返回 dict) =======================

def _home(host):
    resp = _post(host, "/api/v1/video/classifies", None, None)
    try:
        data = json.loads(resp).get("data") or []
    except Exception:
        data = []
    cls = [{"type_id": str(c.get("id")), "type_name": c.get("name") or ""}
           for c in data if c.get("id") and c.get("name")]
    # 按 type_id 升序: 电视剧(22016) 电影(22017) 动漫(22018) 综艺(22019)
    # 短剧(22020) 少儿(22021) 纪录片(22022) AI漫剧(22024), 与 App 首页顺序一致
    cls.sort(key=lambda x: int(x["type_id"]) if str(x["type_id"]).isdigit() else 10 ** 9)
    # 服务端不下发隐藏直播分类(22023), 手动追加到分类栏末尾
    if str(LIVE_TYPE_ID) not in [str(c.get("type_id")) for c in cls]:
        cls.append({"type_id": str(LIVE_TYPE_ID), "type_name": "直播"})
    try:
        filters = _build_filters(data)
    except Exception:
        filters = {}
    return {"class": cls, "filters": filters}

def _item(v):
    """列表条目: 除播放器必需字段外, 附带筛选匹配用的原始字段"""
    return {
        "vod_id": str(v.get("id")),
        "vod_name": v.get("name") or "",
        "vod_pic": v.get("videoPic") or "",
        "vod_remarks": v.get("remarks") or "",
        "vod_area": v.get("area") or "",
        "vod_year": v.get("year") or "",
        "vod_class": v.get("classify") or "",
        "vod_lang": v.get("language") or "",
        "_area": v.get("area") or "",
        "_year": v.get("year") or "",
        "_classify": v.get("classify") or "",
        "_lang": v.get("language") or "",
    }

def _build_list(resp, page=1, id_desc=False):
    try:
        data = json.loads(resp).get("data") or {}
    except Exception:
        data = {}
    lst = []
    for v in data.get("list") or []:
        if not v.get("id"):
            continue
        lst.append(_item(v))
    # 本地按 id 降序: 搜索时 id 大=收录晚=越新, 最新的排在头部
    if id_desc and lst:
        try:
            lst.sort(key=lambda v: int(v.get("vod_id") or 0), reverse=True)
        except Exception:
            pass
    try:
        pg = int(page) or 1
    except (ValueError, TypeError):
        pg = 1
    try:
        pagecount = int(data.get("totalPage") or 1)
    except (ValueError, TypeError):
        pagecount = 1
    if pagecount < pg:
        pagecount = pg
    return {
        "page": pg,
        "pagecount": pagecount,
        "limit": data.get("limit") or 20,
        "total": data.get("totalCount") or 0,
        "list": lst,
    }

def _pack(lst, pg, total=None, pagecount=None):
    """统一分页返回"""
    try:
        pg = int(pg) or 1
    except (ValueError, TypeError):
        pg = 1
    n = len(lst or [])
    if pagecount is None:
        pagecount = int((total or n) / PAGE_LIMIT) + 1
    return {
        "page": pg,
        "pagecount": max(int(pagecount or 1), pg),
        "limit": PAGE_LIMIT,
        "total": int(total if total is not None else n),
        "list": lst or [],
    }

# ---------------- 筛选值归一化 / 匹配 ----------------

def _norm_extend(extend):
    """播放器 extend -> {'class':[值...], 'area':[...], ...} (只保留非空, 兼容多选/列表)"""
    wants = {}
    if not extend:
        return wants
    for key, _label in FILTER_GROUPS:
        raw = extend.get(key)
        if raw is None:
            continue
        vals = raw if isinstance(raw, (list, tuple)) else [raw]
        out = []
        for one in vals:
            out += _split_list(one)
        out = _uniq(out)
        if out:
            wants[key] = out
    return wants

def _tokens(s):
    return _uniq(str(s or "").replace("，", ",").replace("/", ",").split(","))

def _syn(want):
    """筛选值的同义写法(地区大区 / 语言多种写法), 供本地匹配使用"""
    pool = list(AREA_SYNONYMS.get(want) or [])
    for x in (LANG_SYNONYMS.get(want) or []):
        if x not in pool:
            pool.append(x)
    return pool

def _hit(want, fields):
    """某个筛选值是否命中条目: 先精确分词, 再同义词包含, 最后子串"""
    pool = _syn(want)
    for f in fields:
        toks = _tokens(f)
        if want in toks:
            return True
        low = str(f or "")
        for alt in [want] + pool:
            if alt and alt in low:
                return True
    return False

def _match(v, wants):
    """条目是否满足全部已选筛选条件(组内多选为 OR)"""
    for key, vals in wants.items():
        if key == "area":
            ok = any(_hit(w, [v.get("_area"), v.get("_classify")]) for w in vals)
        elif key == "lang":
            ok = any(_hit(w, [v.get("_lang"), v.get("_classify")]) for w in vals)
        elif key == "year":
            yr = str(v.get("_year") or "")
            ok = any(yr == w or (len(w) == 4 and yr.startswith(w)) for w in vals)
        else:  # class / 类型: 兼容纪录片把语言塞进 class 候选的写法
            ok = any(_hit(w, [v.get("_classify"), v.get("_lang"), v.get("_area")]) for w in vals)
        if not ok:
            return False
    return True

# ---------------- 服务端页缓存 / 本地扫描缓存 ----------------
_PAGES = {}      # (分类, 筛选参数, 服务端页码) -> (时间, data)
_SPAGES = {}     # (分类, 搜索页码) -> (时间, data)
_SCAN = {}       # (分类, 已选条件) -> 扫描进度与命中列表

def _pages_of(total):
    """服务端总条数 -> 播放器总页数"""
    try:
        total = int(total or 0)
    except (ValueError, TypeError):
        total = 0
    return max(1, (total + PAGE_LIMIT - 1) // PAGE_LIMIT)

def _index_page(host, tid, dims, spage):
    """取 /video/index 指定页(带筛选参数), TTL 缓存, 供拼页与回看复用"""
    ck = (str(tid), json.dumps(dims or {}, sort_keys=True, ensure_ascii=False), int(spage))
    e = _PAGES.get(ck)
    if e and time.time() - e[0] < _CACHE_TTL:
        return e[1]
    params = {"pageNum": int(spage), "typeId": int(tid)}
    params.update(dims or {})
    try:
        data = json.loads(_post_json(host, "/api/v1/video/index", params)).get("data") or {}
    except Exception:
        data = {}
    if len(_PAGES) > 600:                 # 防止长期占用内存
        _PAGES.clear()
    _PAGES[ck] = (time.time(), data)
    return data

def _index_rows(host, tid, dims, sp0, sp1):
    """并发抓服务端第 sp0..sp1 页并按页序合并(结果按 id 去重)"""
    sp0, sp1 = int(sp0), int(sp1)
    if sp1 < sp0:
        sp1 = sp0
    sp1 = min(sp1, sp0 + MAX_WORKERS * 2 - 1)
    pages = list(range(sp0, sp1 + 1))
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(pages))) as ex:
            datas = list(ex.map(lambda p: _index_page(host, tid, dims, p), pages))
    except Exception:
        datas = [_index_page(host, tid, dims, p) for p in pages]
    out, seen = [], set()
    for data in datas:
        for v in (data or {}).get("list") or []:
            if not v.get("id") or str(v.get("id")) in seen:
                continue
            seen.add(str(v.get("id")))
            out.append(_item(v))
    return out

def _refilter(items, wants, strict=False):
    """本地复核服务端已过滤的列表。
    strict=True(语言这类服务端不支持的条件)只认本地命中;
    否则命中数太少说明口径不一致, 保留服务端结果不误杀。"""
    if not wants:
        return list(items or [])
    kept = [v for v in items if _match(v, wants)]
    if strict:
        return kept
    return kept if len(kept) >= max(3, len(items) // 3) else list(items or [])

def _search_page(host, tid, spage):
    """取 /video/search 空关键词指定页(40条/页), TTL 缓存, 供扫描模式并发翻页复用"""
    ck = (str(tid), int(spage))
    e = _SPAGES.get(ck)
    if e and time.time() - e[0] < _CACHE_TTL:
        return e[1]
    try:
        data = json.loads(_post_json(host, "/api/v1/video/search",
                    {"keyword": "", "typeId": int(tid), "pageNum": int(spage)})).get("data") or {}
    except Exception:
        data = {}
    if len(_SPAGES) > 800:
        _SPAGES.clear()
    _SPAGES[ck] = (time.time(), data)
    return data

def _search_pages(host, tid, sp0, sp1):
    """并发抓服务端搜索页 sp0..sp1(每页 40 条)"""
    sp0 = max(1, int(sp0))
    sp1 = min(max(int(sp1), sp0), SCAN_MAX_PAGE)
    pages = list(range(sp0, sp1 + 1))
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(pages))) as ex:
            return list(ex.map(lambda p: _search_page(host, tid, p), pages))
    except Exception:
        return [_search_page(host, tid, p) for p in pages]

def _scan_filtered(host, tid, pg, wants):
    """服务端筛选不命中/不支持(如只选语言)时的兜底:
    并发翻 /video/search(40条/页) + 本地同义词匹配, 攒够当前页再切片返回。"""
    ck = (str(tid), json.dumps(wants, sort_keys=True, ensure_ascii=False))
    e = _SCAN.get(ck)
    if not e or time.time() - e.get("ts", 0) > _CACHE_TTL:
        e = {"hit": [], "seen": 0, "total": 0, "done": False, "ts": time.time()}
    try:
        need = int(pg) * PAGE_LIMIT
    except (ValueError, TypeError):
        need = PAGE_LIMIT
    while (not e["done"]) and len(e["hit"]) < need and e["seen"] < SCAN_MAX_PAGE:
        sp1 = min(e["seen"] + MAX_WORKERS, SCAN_MAX_PAGE)
        datas = _search_pages(host, tid, e["seen"] + 1, sp1)
        e["seen"] = sp1
        for data in datas:
            data = data or {}
            raw = data.get("list") or []
            e["total"] = int(data.get("totalCount") or e["total"] or 0)
            tp = int(data.get("totalPage") or 0)
            if not raw or (tp and e["seen"] >= tp):
                e["done"] = True
            ids = {x["vod_id"] for x in e["hit"]}
            picked = []
            for v in raw:
                if not v.get("id") or str(v.get("id")) in ids:
                    continue
                it = _item(v)
                if _match(it, wants):
                    picked.append(it)
                    ids.add(it["vod_id"])
            e["hit"] += picked
    if len(_SCAN) > 16:
        _SCAN.clear()
    _SCAN[ck] = e
    start = (int(pg) - 1) * PAGE_LIMIT
    if e["done"]:                          # 扫到头了, 按命中率折算真实规模
        rate = len(e["hit"]) / max(e["seen"] * 40, 1)
        total = e["total"] if rate >= 0.95 else max(len(e["hit"]), start, int(e["total"] * rate))
    else:                                  # 还在往下扫, 页数别提前见底, 让播放器继续翻
        total = max(e["total"], start)
    return _pack(e["hit"][start:start + PAGE_LIMIT], pg, total, _pages_of(total))

def _filtered_category(host, tid, pg, wants):
    """带筛选的分类页, 三级策略:
    A. 服务端 /video/index 过滤, 并按服务端真实页宽对齐分页(页宽被压成 2 条也不会漏内容)
    B. 播放器一页跨多个服务端页时并发抓取, 结果按 (筛选, 页码) 缓存, 回翻不重复请求
    C. 服务端筛不动或口径不一致(欧美这类大区写法、只选语言) -> /video/search 扫描 + 本地匹配"""
    dims = {}
    for k, sv in SERVER_DIM.items():
        if wants.get(k):
            dims[sv] = wants[k][0]        # 服务端只认单值, 取第一个, 其余靠本地匹配
    strict = bool(wants.get("lang"))      # 语言服务端不支持, 只能本地过滤
    if not dims:                          # 只有服务端不支持的条件
        return _scan_filtered(host, tid, pg, wants)

    probe = _index_page(host, tid, dims, 1)      # 先探服务端页宽与总数
    try:
        width = int(probe.get("limit") or 0)
    except (ValueError, TypeError):
        width = 0
    if width < 1:
        width = len([v for v in (probe.get("list") or []) if v.get("id")]) or PAGE_LIMIT
    width = max(1, min(width, 40))
    total = int(probe.get("totalCount") or 0)
    area_want = (wants.get("area") or [""])[0]

    # C-1: 服务端筛出 0 条, 或"欧美"这类大区只认出几十条 -> 本地扫描更准
    if not total:
        return _scan_filtered(host, tid, pg, wants)
    if total < PAGE_LIMIT * 2 and len(_syn(area_want)) > 2:
        return _scan_filtered(host, tid, pg, wants)

    # A/B: 播放器页 -> 服务端页区间
    try:
        off = (int(pg) - 1) * PAGE_LIMIT
    except (ValueError, TypeError):
        off = 0
    sp0 = off // width + 1
    sp1 = (off + PAGE_LIMIT - 1) // width + 1
    rows = _index_rows(host, tid, dims, sp0, sp1)
    win = rows[off % width: off % width + PAGE_LIMIT]
    out = _refilter(win, wants, strict) if strict else win
    if strict and len(out) < 8:
        # 语言只能本地过滤, 服务端页里凑不满一页 -> 交给扫描模式攒够
        return _scan_filtered(host, tid, pg, wants)
    if not out and int(pg or 1) <= 1:
        return _scan_filtered(host, tid, pg, wants)
    return _pack(out, pg, total, _pages_of(total))

def _category(host, tid, pg, extend=None):
    page = 1
    try:
        page = int(pg or 1)
    except Exception:
        pass
    try:
        type_id = int(tid)
    except Exception:
        type_id = 0
    # ---- 直播分类 22023: 服务端不下发, 走 liveVideo 接口返回直播分组 ----
    if type_id == LIVE_TYPE_ID:
        lst = []
        try:
            r = _get(_fix_host(host) + "/api/v1/video/liveVideo")
            data = (json.loads(r).get("data") or {})
            for v in data.get("list") or []:
                if not v.get("id"):
                    continue
                it = _item(v)
                it["vod_remarks"] = it.get("vod_remarks") or ("直播" if v.get("typeId") else "")
                lst.append(it)
        except Exception:
            pass
        return {"page": 1, "pagecount": 1, "limit": len(lst), "total": len(lst), "list": lst}
    # ---- 分类筛选: 播放器把选中的条件放进 extend 传进来 ----
    try:
        wants = _norm_extend(extend)
    except Exception:
        wants = {}
    if wants:
        try:
            return _filtered_category(host, type_id, page, wants)
        except Exception:
            pass
    # 默认走 /video/index(与前面版本一致, 保留服务端原始顺序)。
    # 注意: 服务端忽略 page 参数, 必须用 pageNum 才能真正翻页(否则滑到底内容不变/跳动)。
    resp = _post_json(host, "/api/v1/video/index", {"pageNum": page, "typeId": type_id})
    res = _build_list(resp, page, False)
    # 服务端把部分分类(如电视剧22016)降级为只返回2条(limit=2),
    # 此时自动改用 /video/search 空关键词+typeId 兜底, 拿完整列表(40条/页, 最新在前)。
    if len(res.get("list") or []) < 10:
        resp2 = _post_json(host, "/api/v1/video/search", {"keyword": "", "typeId": type_id, "pageNum": page})
        res = _build_list(resp2, page, True)
    return res

def _search(host, key, pg="1"):
    key = (key or "").strip().strip('"').strip("'")
    if not key:
        return {"page": 1, "pagecount": 0, "limit": 20, "total": 0, "list": []}
    # 兼容播放器传入 URL 编码关键词 (如 %E6%96%97%E7%BD%97...)
    # 服务端 % 会当作通配符, 编码形态会搜出大量无关结果, 必须先解码回原文
    if "%" in key:
        try:
            dec = unquote(key)
            if dec and dec != key:
                key = dec.strip()
        except Exception:
            pass
    # 兼容 \uXXXX 转义形态的关键词 (如备份 \u6597\u7f57...)
    if key and "\\u" in key and all(ord(ch) < 128 for ch in key):
        try:
            dec = key.encode("ascii").decode("unicode_escape")
            if dec and dec != key:
                key = dec
        except Exception:
            pass
    try:
        page = int(pg or 1)
    except (ValueError, TypeError):
        page = 1
    if page < 1:
        page = 1
    resp = _post_json(host, "/api/v1/video/search", {"keyword": key, "pageNum": page})
    return _build_list(resp, page, True)

def _reco(host):
    """首页推荐: 电视剧分类第一页, 失败返回空"""
    try:
        c = _category(host, "22016", "1")
        return (c or {}).get("list") or []
    except Exception:
        return []

def _fetch_detail(host, vid):
    resp = _post_form(host, "/api/v1/video/videoDetails", {"id": str(vid)})
    try:
        return json.loads(resp).get("data") or {}
    except Exception:
        return {}

# ======================= 线路排序 / 改名 =======================

# 置顶线路（严格按这个顺序排最前面）
LINE_PRIORITY = ["江苏4K极速专线", "山东4K 2160P", "爱尔兰4K高码"]


def _nname(s):
    """线路名归一化：去空格、点、横线，统一小写，便于模糊匹配"""
    return (str(s or "").replace("\u3000", "").replace("·", "")
            .replace(" ", "").replace("-", "").replace("_", "").strip().lower())


def _line_name(src):
    """线路显示名：江苏2K极速专线 统一显示为 江苏4K极速专线"""
    raw = str(src.get("sourceName") or "").strip() or "剧下饭"
    low = _nname(raw)
    if "江苏" in raw and "极速专线" in raw and "2k" in low:
        return "江苏4K极速专线"
    return raw


def _line_rank(src):
    """置顶名次的序号；不在置顶名单里返回 99"""
    n = _nname(_line_name(src))
    for i, key in enumerate(LINE_PRIORITY):
        k = _nname(key)
        if not k:
            continue
        if n == k or k in n or n in k:      # 兼容 "山东4K" / "山东 4K 2160P" 这类写法差异
            return i
    return 99


def _ordered_sources(sources):
    """置顶三条线路放最前，其余保持服务端原始顺序"""
    srcs = list(sources or [])
    return [srcs[i] for i in sorted(range(len(srcs)),
                                    key=lambda i: (_line_rank(srcs[i]), i))]

def _detail(host, vid):
    data = _fetch_detail(host, vid)
    if not data:
        return {"list": []}
    sources = _ordered_sources(data.get("playerSource") or [])
    from_names, from_urllists = [], []
    seen = {}
    for pos, src in enumerate(sources):
        eps = src.get("episodes") or []
        if not eps:
            continue
        name = _line_name(src)      # 江苏2K极速专线 -> 江苏4K极速专线
        if name in seen:          # 同名线路加序号区分
            seen[name] += 1
            name = name + str(seen[name])
        else:
            seen[name] = 1
        segs = []
        for i, ep in enumerate(eps, 1):
            ep_name = (ep.get("episodeName") or "") or ("第" + str(i) + "集")
            ep_name = ep_name.replace("$", "_").replace("#", "_")
            # id 里带上线路位置，改名/重排后播放仍能精确命中这一条
            segs.append(ep_name + "$" + str(vid) + "|" + str(pos) + "|" + str(i))
        from_names.append(name)
        from_urllists.append("#".join(segs))
    if not from_urllists:
        return {"list": []}
    play_from = "$$$".join(from_names)     # 多线路: 名字用 $$$ 分隔
    play_url = "$$$".join(from_urllists)   # 线路内集数用 # 分隔
    return {"list": [{
        "vod_id": str(data.get("id") or vid),
        "vod_name": data.get("name") or "",
        "vod_pic": data.get("videoPic") or "",
        "vod_actor": data.get("actor") or "",
        "vod_director": data.get("director") or "",
        "vod_remarks": data.get("remarks") or "",
        "vod_content": data.get("content") or "",
        "vod_year": data.get("year") or "",
        "vod_area": data.get("area") or "",
        "vod_play_from": play_from,
        "vod_play_url": play_url,
    }]}

def _analysis_url(host, source_code, pc):
    """调用服务端 /api/v1/player/analysisUrl 把加密 playerCode 解析成真实播放地址。
    直播(sourceCode=zhibo/difang/huya)与点播加密码(co_xxx)均由此返回秒播地址。
    返回解析成功后的 URL 字符串, 失败返回空串。"""
    if not source_code or not pc:
        return ""
    try:
        r = _post_form(host, "/api/v1/player/analysisUrl", {"from": source_code, "code": pc})
        u = (json.loads(r).get("data") or "")
        if str(u).startswith("http"):
            return str(u)
    except Exception:
        pass
    return ""

def _parse_pid(pid):
    """兼容两种播放 id：新格式 vid|线路位置|集数，旧格式 vid_集数"""
    s = str(pid or "").strip()
    if "|" in s:
        parts = s.split("|")
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
    if "_" in s:
        a, b = s.rsplit("_", 1)
        return a, "", b
    return s, "", "1"


def _play(host, flag, pid):
    try:
        vid, sidx, ep = _parse_pid(pid)
        ep = int(ep)
    except Exception:
        return {"parse": 0, "url": pid, "header": {"User-Agent": UA}}
    data = _fetch_detail(host, vid)
    sources = _ordered_sources(data.get("playerSource") or [])
    # 先锁定用户点的那条线路：优先用 id 里的位置，其次按线路名，其余线路作为备选
    first = -1
    if str(sidx).isdigit() and 0 <= int(sidx) < len(sources):
        first = int(sidx)
    if first < 0:
        flag_s = str(flag or "").strip()
        for i, src in enumerate(sources):
            if _line_name(src) == flag_s or str(src.get("sourceName") or "").strip() == flag_s:
                first = i
                break
    order = ([first] if first >= 0 else []) + \
            [i for i in range(len(sources)) if i != first]
    for i in order:
        src = sources[i]
        eps = src.get("episodes") or []
        if not eps or ep > len(eps):
            continue
        pc = (eps[ep - 1] or {}).get("playerCode") or ""
        parse_url = src.get("parseUrl") or ""
        source_code = src.get("sourceCode") or ""
        if parse_url and pc:
            j = _get(parse_url + pc)
            try:
                u = json.loads(j).get("url") or ""
            except Exception:
                u = ""
            if u:
                return {"parse": 0, "url": u, "header": {"User-Agent": UA}}
        # 直播/加密码: 优先走服务端 analysisUrl 秒播解析 (zb-xxx / 数字房间号 / co_xxx)
        if pc and not str(pc).startswith("http"):
            u = _analysis_url(host, source_code, pc)
            if u:
                headers = {"User-Agent": UA}
                if source_code == "huya":
                    headers["Referer"] = "https://www.huya.com/"
                return {"parse": 0, "url": u, "header": headers}
            # 解析失败: 仍把 code 原样返回, 交由播放器自行尝试
            return {"parse": 0, "url": pc, "header": {"User-Agent": UA}}
        elif pc:
            return {"parse": 0, "url": pc, "header": {"User-Agent": UA}}
    return {"parse": 0, "url": "", "header": {"User-Agent": UA}}

# ======================= 类式接口 (class Spider) =======================

class Spider(_BaseSpider):
    """webhomeTV 类式规范: 各方法返回 dict, searchContent 三参数。
    与咕噜咕噜可搜索版(样板) 结构一致。"""

    def __init__(self, *args, **kwargs):
        self._host = BASE_URLS[0]
        if kwargs.get("host"):
            self._host = _fix_host(kwargs["host"])
        if kwargs.get("extend") is not None:
            self.init(kwargs["extend"])

    def init(self, extend=None):
        if extend:
            s = str(extend).strip()
            if s.startswith("http"):
                self._host = _fix_host(s)
            elif s.startswith("base="):
                self._host = _fix_host(s[5:])

    def getName(self):
        return "剧下饭4K影视"

    def homeContent(self, filter=True):
        result = _home(self._host)
        # 去掉推荐: 只返回纯分类列表, 各分类(含电视剧)均以分类页展示
        result["list"] = []
        return result

    def homeVideoContent(self):
        # 去掉推荐: 分类页保持纯分类列表, 不再渲染"精选/推荐"卡
        return {"list": []}

    def categoryContent(self, tid, pg="1", filter=None, extend=None):
        return _category(self._host, tid, pg, extend)

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        return _detail(self._host, ids[0])

    # ---------- 搜索 (关键: 三参数签名, 兼容 webhomeTV) ----
    def searchContent(self, key, quick, pg="1"):
        """webhomeTV 搜索入口 - key 关键词, quick 快速标记, pg 页码"""
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick, pg="1"):
        """分页搜索 - 支持真正翻页、异常兜底"""
        try:
            return _search(self._host, key, pg)
        except Exception:
            return {"page": 1, "pagecount": 1, "limit": 0, "total": 0, "list": []}

    def playerContent(self, flag, id, vipFlags=""):
        return _play(self._host, flag, id)

    def manualVideoCheck(self):
        return False

    def isVideoFormat(self, url):
        return False

    def localProxy(self, param):
        return {"list": [], "parse": 0, "url": ""}

    def liveContent(self, url):
        return {"list": []}


# ======================= 函数式接口 (模块级函数) =======================

_HOST = BASE_URLS[0]

def init(extend=None):
    global _HOST
    if extend:
        s = str(extend).strip()
        if s.startswith("http"):
            _HOST = _fix_host(s)
        elif s.startswith("base="):
            _HOST = _fix_host(s[5:])

def homeContent(filter=True):
    try:
        r = _home(_HOST)
        r["list"] = []
    except Exception:
        r = {"class": [], "filters": {}, "list": []}
    return json.dumps(r, ensure_ascii=False)

def homeVideoContent():
    return json.dumps({"list": []}, ensure_ascii=False)

def categoryContent(tid, pg="1", filter=False, extend=None):
    return json.dumps(_category(_HOST, tid, pg, extend), ensure_ascii=False)

def detailContent(ids):
    if not ids:
        return '{"list":[]}'
    return json.dumps(_detail(_HOST, ids[0]), ensure_ascii=False)

def searchContent(key, quick=False, pg="1"):
    return json.dumps(_search(_HOST, key, pg), ensure_ascii=False)

def playerContent(flag, id, vipFlags=None):
    return json.dumps(_play(_HOST, flag, id), ensure_ascii=False)

def manualVideoCheck():
    return False

def isVideoFormat(url):
    return False


# ======================= 本地自测 =======================

if __name__ == "__main__":
    def show(label, s, n=220):
        txt = json.dumps(s, ensure_ascii=False) if not isinstance(s, str) else s
        print("== " + label + " ==")
        print(txt if len(txt) <= n else txt[:n])
        print()

    sp = Spider()
    hm = sp.homeContent(True)
    show("Spider.homeContent.class", hm.get("class"))
    show("Spider.homeContent.filters(电视剧)", hm.get("filters", {}).get("22016"), 500)
    show("Spider.categoryContent 无筛选", sp.categoryContent("22016", "1", False, None))
    show("Spider.category 电视剧+都市", sp.categoryContent("22016", "1", True, {"class": "都市"}))
    show("Spider.category 电影+欧美", sp.categoryContent("22017", "1", True, {"area": "欧美"}))
    show("Spider.category 电视剧+内地+2024", sp.categoryContent("22016", "1", True, {"area": "内地", "year": "2024"}))
    show("Spider.category 纪录片+国语", sp.categoryContent("22022", "1", True, {"class": "国语"}))
    show("Spider.categoryLive", sp.categoryContent("22023", "1", False, None))
    show("Spider.searchContent", sp.searchContent("斗罗大陆", True))
    show("Spider.detailContent", sp.detailContent(["621119"]))
    show("Spider.playerContent ep1", sp.playerContent("剧下饭", "621119_1", None))
    show("Spider.playerContent ep2", sp.playerContent("剧下饭", "621119_2", None))
    show("Spider.liveDetail", sp.detailContent(["366473"]))
    show("Spider.livePlay", sp.playerContent("直播频道", "366473_1", None))
    show("Spider.huyaPlay", sp.playerContent("虎牙直播", "370855_1", None))
#（注：内容由AI生成）
