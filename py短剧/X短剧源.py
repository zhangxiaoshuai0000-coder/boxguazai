# -*- coding: utf-8 -*-
# ══════════════════════════════════════════════════════════════
# 判型记录(卡01 第四节;跨会话可读 —— 接手先读这段,别重新判一遍)
#   RE_TARGET   : https://xduanju.net/explore
#   RE_PATH     : 服务端渲染(SSR)。列表/详情均为 HTML,播放数据由服务端写进
#                 #player-data 的 JSON;每集一条独立 m3u8,非客户端 SPA 取数。
#   RE_OBSTACLE : 无盾/无签名/无接口密文/无 wasm;18+ 门仅前端 localStorage 遮罩。
#   RE_EVIDENCE : probe=纯HTML(0.65);m3u8 直拉 200,标准 HLS + AES-128
#                 (crypt.key/seg 相对路径,ExoPlayer 原生解密);付费墙=client。
#   RE_CREATED  : 2026-11-03
# ══════════════════════════════════════════════════════════════
# TVBox 源 · X短剧(xduanju.net)
# 自检:python3 shellsim.py 本文件 --run --strict   (AUDIT_OK 才算成)

import gzip
import json
import re
import time
import urllib.parse
import urllib.request

# ──────────────────────────────────────────────────────────────
# 站点档案
# ──────────────────────────────────────────────────────────────
SITE = {
    "name": "X短剧",
    "domains": ["https://xduanju.net"],
    "home_path": "/explore",
    "tag_path": "/tag/{tid}?page={pg}",
    "search_path": "/search?q={kw}&page={pg}",
    "cookie_gate": {},
    "headers": {"Referer": "https://xduanju.net/"},
}

# 分类即站点标签,tid 直接用标签名(请求时再做 URL 编码)
TAG_NAMES = [
    "都市", "现代", "高颜值", "熟女", "大男主", "后宫", "乱伦", "剧情", "古风",
    "大女主", "绿帽", "奇幻", "校园", "职场", "逆袭", "脑洞", "甜宠", "系统",
    "穿越", "母子", "乡村", "玄幻", "仙侠", "禁忌", "虐恋", "ntr", "权谋",
    "同性", "超能力", "同学",
]
CATS = [{"type_id": n, "type_name": n} for n in TAG_NAMES]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 15
RETRY = 3
PAGE_SIZE = 30

# 卡片块:<a class="drama-card" href="/drama/xx" title=".."> .. </a>
CARD_RE = re.compile(r'(<a[^>]+class="[^"]*drama-card[^"]*"[^>]*>.*?</a>)', re.S)
HREF_RE = re.compile(r'href="([^"]+)"', re.S)
IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.S)
EP_RE = re.compile(r'class="episode-count"[^>]*>(.*?)</span>', re.S)
H3_RE = re.compile(r'<h3[^>]*>(.*?)</h3>', re.S)
P_RE = re.compile(r'<p[^>]*>(.*?)</p>', re.S)


# ──────────────────────────────────────────────────────────────
# 通用工具
# ──────────────────────────────────────────────────────────────
def _dec(raw):
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "ignore")


def http_get(path, base=None):
    """带回退重试的 GET。抖动退避重试;真吃盾就换域。"""
    if path.startswith("http"):
        urls = [path]
    else:
        bases = ([base] if base else []) + SITE["domains"]
        urls = [(b or "").rstrip("/") + path for b in bases]
    last = None
    for u in urls:
        for attempt in range(RETRY):
            try:
                req = urllib.request.Request(u)
                req.add_header("User-Agent", UA)
                for k, v in SITE["headers"].items():
                    req.add_header(k, v)
                for k, v in SITE["cookie_gate"].items():
                    req.add_header("Cookie", "%s=%s" % (k, v))
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    raw = r.read()
                    if raw[:2] == b"\x1f\x8b":
                        raw = gzip.decompress(raw)
                    return _dec(raw), r.geturl()
            except Exception as e:
                last = e
                time.sleep(0.5 * (attempt + 1))
    return "", None


def txt_of(s):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    import html as _h
    return re.sub(r"\s+", " ", _h.unescape(s)).strip()


def abs_url(u, base):
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return urllib.parse.urljoin(base or SITE["domains"][0], u)
    return u


def parse_cards(html, base):
    out, seen = [], set()
    for block in CARD_RE.findall(html or ""):
        mh = HREF_RE.search(block)
        if not mh:
            continue
        vid = abs_url(mh.group(1), base)
        if vid in seen:
            continue
        seen.add(vid)
        mi = IMG_RE.search(block)
        me = EP_RE.search(block)
        m3 = H3_RE.search(block)
        mp = P_RE.search(block)
        name = txt_of(m3.group(1)) if m3 else ""
        out.append({
            "vod_id": vid,
            "vod_name": name[:80],
            "vod_pic": abs_url(mi.group(1), base) if mi else "",
            "vod_remarks": txt_of(me.group(1)) if me else "",
            "vod_content": txt_of(mp.group(1)) if mp else "",
        })
    return out


# ──────────────────────────────────────────────────────────────
# TVBox 源接口
# ──────────────────────────────────────────────────────────────
class Spider:
    def getName(self):
        return SITE["name"]

    def init(self, extend=""):
        try:
            self.ext = json.loads(extend) if extend else {}
        except Exception:
            self.ext = {}

    def isVideoFormat(self, url):
        return bool(re.search(r"\.(?:m3u8|mp4|ts)(?:\?|$)", url or "", re.I))

    def manualVideoCheck(self):
        return False

    def homeContent(self, filter):
        html, base = http_get(SITE["home_path"])
        return {"class": CATS, "list": parse_cards(html, base)}

    def homeVideoContent(self):
        html, base = http_get(SITE["home_path"])
        return {"list": parse_cards(html, base)}

    def categoryContent(self, tid, pg, filter, extend):
        path = SITE["tag_path"].format(tid=urllib.parse.quote(str(tid), safe=""),
                                       pg=int(pg))
        html, base = http_get(path)
        items = parse_cards(html, base)
        # 30 条/页:本页满额则假定还有下一页,否则收口
        pagecount = int(pg) + 1 if len(items) >= PAGE_SIZE else int(pg)
        return {"list": items, "page": int(pg), "pagecount": pagecount,
                "limit": len(items), "total": 0}

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else ids
        html, base = http_get(vid)
        info = {"vod_id": vid, "vod_name": "", "vod_pic": "", "vod_content": "",
                "vod_play_from": "短剧", "vod_play_url": ""}

        m = re.search(r"<h1[^>]*>(.*?)</h1>", html or "", re.S)
        if m:
            info["vod_name"] = txt_of(m.group(1))
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html or "")
        if m:
            info["vod_pic"] = abs_url(m.group(1), base)
        m = re.search(r'id="drama-desc"[^>]*>(.*?)</div>', html or "", re.S)
        if m:
            info["vod_content"] = txt_of(m.group(1))

        # 播放数据:服务端渲染的 JSON,每集 {seq, src}
        m = re.search(r'id="player-data"[^>]*>(.*?)</script>', html or "", re.S)
        eps = []
        if m:
            try:
                eps = json.loads(txt_of(m.group(1)))
            except Exception:
                eps = []
        play = []
        for ep in eps:
            src = abs_url(ep.get("src", ""), base)
            seq = ep.get("seq", "")
            if src:
                play.append("第%s集$%s" % (seq, src))
        info["vod_play_url"] = "#".join(play) if play else "暂无播放$"
        return {"list": [info]}

    def searchContent(self, key, quick=False, pg="1"):
        path = SITE["search_path"].format(kw=urllib.parse.quote(str(key)),
                                          pg=int(pg))
        html, base = http_get(path)
        return {"list": parse_cards(html, base), "page": int(pg)}

    def playerContent(self, flag, id, vipFlags):
        # m3u8 为标准 HLS(AES-128 相对密钥),ExoPlayer 直接播;补头交给本地代理,
        # 不把整片代过服务器(机房 IP 易被源站 403)。
        head = "User-Agent: %s\n" % UA
        for k, v in SITE["headers"].items():
            head += "%s: %s\n" % (k, v)
        return {"parse": 0, "url": id, "header": head}
