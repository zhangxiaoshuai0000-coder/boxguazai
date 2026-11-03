# -*- coding: utf-8 -*-
# 星梦ASMR (www.asmrzy.top) TVBox 爬虫
#
# 修复内容（相对旧版）：
# 1. 分类筛选按原站导航动态获取（中国/韩国/日本/其他/音频），失败时回退静态映射；
# 2. 列表解析修复：旧正则 `<li class="joe_list__item">(.*?)</li>` 会被列表项内部
#    嵌套的 </li>（meta 信息里的 <ul class="items">）截断，导致每页大量条目丢失，
#    改为按列表项起始位置切分，完整保留每页全部内容；
# 3. 分类全量化加载：原站分类页每页仅服务端渲染 5 条，旧版只抓第一页所以“刷新太少”。
#    现在选中分类后自动抓取全部分页并合并去重，一次性刷出该分类全部资源；
# 4. 详情页播放地址解析修复：原站视频为自定义标签 <joe-dplayer src="...m.m3u8">、
#    音频为 <joe-mp3 url="...mp3">，旧版只认 iframe/video 标签导致全部解析失败；
# 5. 首页改用站内 AJAX 接口 /joe/api（routeType=publish_list）拉取最新文章列表；
# 6. 搜索修复：原站搜索为 POST 后 302 跳转到 /search/{关键词}/，旧版用 ?s= 永远搜不到，
#    改为直接 GET /search/{关键词}/{页}/；
# 7. 播放直链附带 Referer/UA，B站、YouTube 外链解析逻辑保留作兜底。

import re
import time
import requests
from urllib.parse import quote, urljoin, unquote
from concurrent.futures import ThreadPoolExecutor

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        def init(self, extend=""): pass
        def homeContent(self, filter): return {'class': [], 'filters': {}}
        def homeVideoContent(self): return {'list': []}
        def categoryContent(self, tid, pg, filter, extend): return {'list': [], 'page': 1, 'pagecount': 1}
        def detailContent(self, ids): return {'list': []}
        def playerContent(self, flag, id, vipFlags=None): return {'parse': 0, 'url': '', 'header': {}}
        def searchContent(self, key, quick, pg='1'): return {'list': [], 'page': 1, 'pagecount': 1}


class Spider(BaseSpider):
    BASE_URL = "https://www.asmrzy.top"
    API_PATH = "/joe/api"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    # 分类 slug 与显示名称映射（导航栏顺序，动态获取失败时回退）
    CATEGORY_MAP = {
        "cn": "中国",
        "kr": "韩国",
        "jp": "日本",
        "other": "其他",
        "listen": "音频",
    }

    MAX_PAGES = 100        # 单个分类一次加载的最大分页数（防失控，可用 extend pages=N 调整）
    MAX_WORKERS = 5        # 分页并发数
    HOME_API_PAGES = 5     # 首页接口最多拉取的分页数
    HOME_PAGE_SIZE = 30    # 首页接口每页条数
    TIMEOUT = 15

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.session.verify = False
        try:
            import urllib3
            urllib3.disable_warnings()
        except Exception:
            pass

    def init(self, extend=""):
        extend = (extend or "").strip()
        if not extend:
            return None
        # 形式1：整个 extend 就是备用地址
        if extend.startswith("http"):
            self.BASE_URL = extend.rstrip("/")
            return None
        # 形式2：url=...&cookie=...&pages=N
        for part in extend.split("&"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            key, val = part.split("=", 1)
            key = key.strip().lower()
            if key in ("url", "base", "baseurl") and val.startswith("http"):
                self.BASE_URL = val.rstrip("/")
            elif key == "cookie" and val:
                self.session.headers.update({"Cookie": val})
            elif key in ("pages", "maxpages"):
                try:
                    self.MAX_PAGES = max(1, int(val))
                except Exception:
                    pass
        return None

    def getName(self):
        return "星梦ASMR"

    # ---------------- 基础请求 ----------------

    def _get(self, url):
        """GET 页面，失败时重试一次，始终返回字符串"""
        for _ in range(2):
            try:
                resp = self.session.get(url, timeout=self.TIMEOUT)
                if resp.status_code == 200 and resp.text:
                    return resp.text
            except Exception:
                pass
            time.sleep(0.2)
        return ""

    def _api_publish_list(self, page, page_size, list_type="created"):
        """站内 AJAX 接口：/joe/api  routeType=publish_list"""
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self.BASE_URL + "/",
            "Origin": self.BASE_URL,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        data = {"routeType": "publish_list", "page": page, "pageSize": page_size, "type": list_type}
        try:
            resp = self.session.post(self.BASE_URL + self.API_PATH, data=data,
                                     headers=headers, timeout=self.TIMEOUT)
            if resp.status_code != 200:
                return []
            js = resp.json()
            if isinstance(js, dict) and isinstance(js.get("data"), list):
                return js["data"]
        except Exception:
            pass
        return []

    # ---------------- 首页 ----------------

    def homeContent(self, filter):
        classes = []
        seen = set()
        # 优先从原站导航动态获取分类，保证与站点当前分类一致
        try:
            html = self._get(self.BASE_URL + "/")
            for m in re.finditer(r'<a[^>]+href="([^"]*?/category/([^/"]+)/?)"[^>]*>([^<]+)</a>', html):
                slug = m.group(2).strip()
                name = m.group(3).strip()
                if slug and name and slug not in seen:
                    seen.add(slug)
                    classes.append({"type_id": slug, "type_name": name})
        except Exception:
            pass
        if not classes:
            for slug, name in self.CATEGORY_MAP.items():
                classes.append({"type_id": slug, "type_name": name})
        return {"class": classes, "filters": {}}

    def _pick_image(self, images):
        """从接口返回的图片数组中挑一张有效封面"""
        for u in images or []:
            if not u or u.startswith("data:"):
                continue
            low = u.lower()
            if any(k in low for k in ("favicon", "logo", "lazyload", "gravatar", "avatar")):
                continue
            return u
        for u in images or []:
            if u and not u.startswith("data:"):
                return u
        return ""

    def homeVideoContent(self):
        videos = []
        seen = set()
        for page in range(1, self.HOME_API_PAGES + 1):
            items = self._api_publish_list(page, self.HOME_PAGE_SIZE)
            if not items:
                break
            added = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                permalink = item.get("permalink") or ""
                m = re.search(r"/(\d+)\.html", permalink)
                vid = m.group(1) if m else permalink
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                videos.append({
                    "vod_id": vid,
                    "vod_name": item.get("title") or "",
                    "vod_pic": self._pick_image(item.get("image") or []),
                    "vod_remarks": item.get("time") or item.get("created") or "",
                })
                added += 1
            if not added:
                break
        if not videos:
            # 接口不可用时回退到中国分类第一页
            return self.categoryContent("cn", "1", False, {})
        return {"list": videos}

    # ---------------- 列表解析 ----------------

    def _split_items(self, html):
        """把列表 HTML 拆成单条文章块（兼容列表项内部嵌套的 li/ul，避免被 </li> 截断）"""
        if not html:
            return []
        blocks = []
        starts = [m.start() for m in re.finditer(r'<li[^>]*class="[^"]*joe_list__item[^"]*"[^>]*>', html)]
        if starts:
            for i, s in enumerate(starts):
                e = starts[i + 1] if i + 1 < len(starts) else html.find("</ul>", s)
                if e == -1:
                    e = len(html)
                blocks.append(html[s:e])
            return blocks
        # 回退：按 <li> 切分，仅保留含封面的块
        for chunk in re.split(r"(?=<li[ >])", html):
            if 'class="thumbnail"' in chunk:
                blocks.append(chunk)
        return blocks

    def _parse_post_item(self, block):
        if not block:
            return None
        # 详情链接与标题（封面锚点带 title 属性）
        m = re.search(r'<a[^>]+href="([^"]+)"[^>]*class="[^"]*thumbnail[^"]*"[^>]*?title="([^"]*)"', block, re.S)
        if not m:
            m = re.search(r'<a[^>]+class="[^"]*thumbnail[^"]*"[^>]*?href="([^"]+)"[^>]*?title="([^"]*)"', block, re.S)
        if not m:
            return None
        link = urljoin(self.BASE_URL, m.group(1).strip())
        title = (m.group(2) or "").strip()
        if not title:
            t = re.search(r'<a[^>]+class="[^"]*title[^"]*"[^>]*>([^<]+)</a>', block, re.S)
            if t:
                title = t.group(1).strip()
        if not title:
            t = re.search(r'<img[^>]+alt="([^"]+)"', block)
            if t:
                title = t.group(1).strip()
        if not title:
            return None

        vm = re.search(r"/(\d+)\.html", link)
        vid = vm.group(1) if vm else link

        # 封面（data-src 为真实图片，src 多为 lazyload 占位图）
        pic = ""
        im = re.search(r'<img[^>]+data-src="([^"]+)"', block)
        if im:
            pic = im.group(1).strip()
        if not pic:
            im = re.search(r'<img[^>]+src="([^"]+)"', block)
            if im and "lazyload" not in im.group(1):
                pic = im.group(1).strip()
        if pic.startswith("data:"):
            pic = ""

        # 日期/备注
        dm = re.search(r'<time[^>]*datetime="([^"]+)"', block)
        if not dm:
            dm = re.search(r'<li>\s*(\d{4}年\d{2}月\d{2}日|\d{4}-\d{2}-\d{2})\s*</li>', block)
        remarks = dm.group(1).strip() if dm else ""

        return {
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": pic,
            "vod_remarks": remarks,
        }

    def _extract_pagecount(self, html, pg):
        m = re.search(r'<ul[^>]*class="[^"]*joe_pagination[^"]*"[^>]*>(.*?)</ul>', html, re.S)
        if m:
            nums = [int(x) for x in re.findall(r"<a[^>]*>\s*(\d+)\s*</a>", m.group(1))]
            if nums:
                return max(max(nums), pg)
        return pg

    def _fetch_category_page(self, tid, pg):
        url = f"{self.BASE_URL}/category/{tid}/" if pg <= 1 else f"{self.BASE_URL}/category/{tid}/{pg}/"
        html = self._get(url)
        if not html:
            return [], pg
        items = [p for p in (self._parse_post_item(b) for b in self._split_items(html)) if p]
        return items, self._extract_pagecount(html, pg)

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        pg = max(pg, 1)
        tid = (tid or "").strip().strip("/")
        if not tid:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}

        items, pagecount = self._fetch_category_page(tid, pg)

        # 第一页时自动加载全部分页并合并，保证选中分类后全部资源一次刷出
        if pg == 1 and pagecount > 1:
            max_page = min(pagecount, self.MAX_PAGES)
            rest = list(range(2, max_page + 1))
            fetched = {}
            try:
                with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as ex:
                    for p, res in zip(rest, ex.map(lambda x: self._fetch_category_page(tid, x), rest)):
                        fetched[p] = res
            except Exception:
                for p in rest:
                    if p not in fetched:
                        fetched[p] = self._fetch_category_page(tid, p)
            seen = {v["vod_id"] for v in items}
            for p in rest:
                page_items, _ = fetched.get(p, ([], p))
                for v in page_items:
                    if v["vod_id"] not in seen:
                        seen.add(v["vod_id"])
                        items.append(v)
            pagecount = 1

        return {
            "list": items,
            "page": 1 if pagecount == 1 else pg,
            "pagecount": pagecount,
            "limit": 20,
            "total": len(items),
        }

    # ---------------- 详情与播放 ----------------

    def _extract_media(self, html):
        """提取播放地址，返回 (url, kind)，kind 为 video / audio"""
        if not html:
            return None, None
        # 1. 原站视频组件 <joe-dplayer player="...player.php?url=" src="...m.m3u8">
        m = re.search(r'<joe-dplayer[^>]*\bsrc="([^"]+)"', html, re.I)
        if m:
            src = m.group(1).strip()
            if "player.php" in src and "url=" in src:
                pm = re.search(r'[?&]url=([^&"\']+)', src)
                if pm:
                    src = unquote(pm.group(1))
            return src, "video"
        # 2. 原站音频组件 <joe-mp3 name="..." url="...mp3">
        m = re.search(r'<joe-mp3[^>]*\burl="([^"]+)"', html, re.I)
        if m:
            return m.group(1).strip(), "audio"
        # 3. iframe（外链兜底）
        for src in re.findall(r'<iframe[^>]+src="([^"]+)"', html, re.I):
            src = src.strip()
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = urljoin(self.BASE_URL, src)
            if any(k in src for k in ("google", "trustpilot", "tree-nation")):
                continue
            return src, "video"
        # 4. video / source 标签
        for pat in (r'<video[^>]+src="([^"]+)"', r'<source[^>]+src="([^"]+)"'):
            m = re.search(pat, html, re.I)
            if m:
                return m.group(1).strip(), "video"
        # 5. 页面中的直链
        m = re.search(r'(https?://[^\s"\'<>]+\.(?:mp4|m3u8|webm|flv|mp3))', html, re.I)
        if m:
            url = m.group(1)
            return url, ("audio" if url.lower().endswith(".mp3") else "video")
        # 6. a 标签直链
        m = re.search(r'<a[^>]+href="(https?://[^"]+\.(?:mp4|m3u8|webm|mp3))"', html, re.I)
        if m:
            return m.group(1).strip(), "video"
        return None, None

    def _parse_platform(self, url):
        """识别视频平台，返回 (platform, identifier)"""
        if not url:
            return None, None
        bili = re.search(r'(?:bilibili\.com/video/|player\.bilibili\.com/player\.html\?[^"]*bvid=)([a-zA-Z0-9]+)', url, re.I)
        if bili:
            return "bilibili", bili.group(1)
        bili_aid = re.search(r'player\.bilibili\.com/player\.html\?[^"]*aid=(\d+)', url, re.I)
        if bili_aid:
            return "bilibili_aid", bili_aid.group(1)
        yt = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url, re.I)
        if yt:
            return "youtube", yt.group(1)
        return "direct", url

    def _aid_to_bvid(self, aid):
        try:
            resp = self.session.get(f"https://api.bilibili.com/x/web-interface/view?aid={aid}", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return data["data"].get("bvid")
        except Exception:
            pass
        return None

    def _get_bilibili_playurl(self, vid, is_aid=False):
        """获取 B站视频直链（兜底用）"""
        try:
            if is_aid:
                bvid = self._aid_to_bvid(vid)
                view_url = (f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}" if bvid
                            else f"https://api.bilibili.com/x/web-interface/view?aid={vid}")
            else:
                view_url = f"https://api.bilibili.com/x/web-interface/view?bvid={vid}"
            headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com"}
            resp = self.session.get(view_url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data.get("code") != 0:
                return None
            cid = data["data"]["cid"]
            bvid = data["data"]["bvid"]
            play_url = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&qn=80"
            resp = self.session.get(play_url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data.get("code") != 0:
                return None
            durl = data["data"].get("durl")
            if not durl:
                return None
            return durl[0]["url"]
        except Exception:
            return None

    def detailContent(self, ids):
        if not ids or not ids[0]:
            return {"list": []}
        vid = str(ids[0]).strip()
        detail_url = vid if vid.startswith("http") else f"{self.BASE_URL}/{vid}.html"
        html = self._get(detail_url)
        if not html:
            return {"list": []}

        tm = re.search(r"<h1[^>]*>([^<]+)</h1>", html)
        title = tm.group(1).strip() if tm else "未知"

        # 封面：原站无 og:image，分享链接里的 pics 参数即文章特色图
        pic = ""
        pm = re.search(r'pics=([^"&\s]+)', html)
        if pm:
            pic = unquote(pm.group(1))
        if not pic or pic.startswith("data:"):
            pm = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
            if pm:
                pic = pm.group(1)
        if not pic or pic.startswith("data:"):
            am = re.search(r"<article[^>]*>(.*?)</article>", html, re.S)
            if am:
                im = re.search(r'<img[^>]+(?:data-src|src)="([^"]+)"', am.group(1))
                if im:
                    pic = im.group(1)
        if pic.startswith("data:"):
            pic = ""

        em = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html)
        excerpt = em.group(1).strip() if em else ""

        media_url, media_kind = self._extract_media(html)

        if media_url:
            platform, pid = self._parse_platform(media_url)
            if platform == "bilibili":
                play_url = f"bilibili://{pid}"
            elif platform == "bilibili_aid":
                play_url = f"bilibili_aid://{pid}"
            elif platform == "youtube":
                play_url = f"youtube://{pid}"
            else:
                play_url = f"播放${media_url}"
            vod = {
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_content": excerpt,
                "vod_play_from": "星梦视频" if media_kind == "video" else "星梦音频",
                "vod_play_url": play_url,
            }
        else:
            vod = {
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_content": excerpt or "未提取到播放地址，可能需手动解析。",
                "vod_play_from": "",
                "vod_play_url": "",
            }
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags=None):
        if not id:
            return {"parse": 0, "url": "", "header": {}}
        id = str(id)
        if id.startswith("bilibili://"):
            bvid = id.split("://")[-1]
            url = self._get_bilibili_playurl(bvid)
            if url:
                return {"parse": 0, "url": url, "header": {"Referer": "https://www.bilibili.com"}}
            return {"parse": 0, "url": f"https://player.bilibili.com/player.html?bvid={bvid}", "header": {}}
        if id.startswith("bilibili_aid://"):
            aid = id.split("://")[-1]
            url = self._get_bilibili_playurl(aid, is_aid=True)
            if url:
                return {"parse": 0, "url": url, "header": {"Referer": "https://www.bilibili.com"}}
            return {"parse": 0, "url": f"https://player.bilibili.com/player.html?aid={aid}", "header": {}}
        if id.startswith("youtube://"):
            yid = id.split("://")[-1]
            return {"parse": 0, "url": f"https://www.youtube.com/embed/{yid}?autoplay=1", "header": {}}
        # 站内直链（m3u8 / mp4 / mp3）
        return {
            "parse": 0,
            "url": id,
            "header": {
                "User-Agent": self.HEADERS["User-Agent"],
                "Referer": self.BASE_URL + "/",
            },
        }

    # ---------------- 搜索 ----------------

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        pg = max(pg, 1)
        key = (key or "").strip()
        if not key:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        # 原站搜索：POST / 会 302 到 /search/{关键词}/，直接 GET 该地址
        url = f"{self.BASE_URL}/search/{quote(key)}/"
        if pg > 1:
            url += f"{pg}/"
        html = self._get(url)
        if not html:
            return {"list": [], "page": pg, "pagecount": pg, "limit": 20, "total": 0}
        items = [p for p in (self._parse_post_item(b) for b in self._split_items(html)) if p]
        pagecount = self._extract_pagecount(html, pg)
        return {
            "list": items,
            "page": pg,
            "pagecount": pagecount,
            "limit": 20,
            "total": len(items),
        }

    def isVideoFormat(self, url):
        return url and any(ext in url for ext in [".m3u8", ".mp4", ".webm", ".flv", ".mp3"])

    def localProxy(self, param):
        return [404, "text/plain", b""]
