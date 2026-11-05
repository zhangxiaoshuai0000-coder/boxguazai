try:
    from base.spider import BaseSpider
except Exception:
    class BaseSpider:
        pass


import re
import html as _html
import urllib.request
import urllib.parse
import urllib.error


BASE = 'https://91crdjai.com'
UA = 'Mozilla/5.0 (Linux; Android 14; HarmonyOS; HUAWEI) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
CHANNELS = [
    ('duanju', '成人短剧'),
    ('manju', '成人漫剧'),
    ('zhenrenju', '真人剧'),
    ('shipin', '成人视频'),
]
CH_RE = r'(?:duanju|manju|zhenrenju|shipin)'
IMG_HOSTS = ('pic.drleao.cn', '91crdjai.com')


def _clean(t):
    if not t:
        return ''
    t = re.sub(r'<[^>]+>', ' ', t)
    return _html.unescape(re.sub(r'\s+', ' ', t)).strip()


def _abs(u):
    if not u:
        return ''
    u = u.strip()
    if u.startswith('//'):
        return 'https:' + u
    if u.startswith('/'):
        return BASE + u
    return u


def _fix_url(u):
    if not u:
        return ''
    u = _html.unescape(u)
    u = u.replace('\\u0026', '&').replace('\\u002F', '/').replace('\\/', '/')
    u = u.replace('&amp;', '&')
    return u.strip()


def _is_img(u):
    if not u or u.startswith('data:'):
        return False
    ul = u.lower()
    if any(h in ul for h in IMG_HOSTS):
        return True
    return bool(re.search(r'\.(?:jpe?g|png|webp|gif)(?:\?|$)', ul))


class Spider(BaseSpider):
    def getName(self):
        return '🔞91成人短剧'

    def getDependence(self):
        return []

    def init(self, extend=''):
        pass

    def destroy(self):
        pass

    def _headers(self, referer=None):
        h = {
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Cache-Control': 'no-cache',
        }
        if referer:
            h['Referer'] = referer
        else:
            h['Referer'] = BASE + '/'
        return h

    def _get(self, url, headers=None):
        h = self._headers()
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode('utf-8', 'ignore')
        except urllib.error.HTTPError as e:
            try:
                return e.read().decode('utf-8', 'ignore')
            except Exception:
                return ''
        except Exception:
            return ''

    def _extract_pic(self, body):
        if not body:
            return ''
        # 优先 data-src（懒加载真实地址）
        for m in re.finditer(r'data-src=["\']([^"\']+)["\']', body, re.I):
            cand = _fix_url(m.group(1))
            if _is_img(cand):
                return cand
        # 其次普通 src
        for m in re.finditer(r'\bsrc=["\']([^"\']+)["\']', body, re.I):
            cand = _fix_url(m.group(1))
            if _is_img(cand):
                return cand
        # 兜底：任意图片 URL
        for m in re.finditer(r'(https?://[^\s"\'<>]+?\.(?:jpe?g|png|webp)(?:\?[^\s"\'<>]*)?)', body, re.I):
            cand = _fix_url(m.group(1))
            if _is_img(cand):
                return cand
        return ''

    def _extract_remarks(self, body):
        if not body:
            return ''
        bits = []
        em = re.search(r'class=["\']eps-flag["\'][^>]*>(.*?)</span>', body, re.S | re.I)
        if em:
            t = _clean(em.group(1))
            if t:
                bits.append(t)
        bm = re.search(r'class=["\']badge[^"\']*["\'][^>]*>(.*?)</span>', body, re.S | re.I)
        if bm:
            t = _clean(bm.group(1))
            if t and t not in bits:
                bits.append(t)
        mm = re.search(r'class=["\']meta["\'][^>]*>(.*?)</div>', body, re.S | re.I)
        if mm and not bits:
            t = _clean(mm.group(1))
            # 只取集数/状态相关片段
            m2 = re.search(r'(\d+\s*集|更新中|完结|全\d+)', t)
            if m2:
                bits.append(m2.group(1))
        return ' · '.join(bits) if bits else ''

    def _cards(self, src):
        out = []
        seen = set()
        # 主匹配：带频道路径的卡片链接
        pat = re.compile(
            r'<a[^>]*href=["\'](/' + CH_RE + r'/\d+-[^"\'/]+/)["\'][^>]*>(.*?)</a>',
            re.S | re.I,
        )
        for m in pat.finditer(src or ''):
            path = m.group(1)
            if path in seen:
                continue
            seen.add(path)
            body = m.group(2)
            name = ''
            am = re.search(r'\balt=["\']([^"\']+)["\']', body, re.I)
            if am:
                name = _clean(am.group(1))
            if not name:
                hm = re.search(r'<h[1-6][^>]*>(.*?)</h[1-6]>', body, re.S | re.I)
                if hm:
                    name = _clean(hm.group(1))
            if not name:
                # data-track-item-name
                nm = re.search(r'data-track-item-name=["\']([^"\']+)["\']', m.group(0), re.I)
                if nm:
                    name = _clean(nm.group(1))
            if not name:
                continue
            pic = self._extract_pic(body)
            remarks = self._extract_remarks(body)
            out.append({
                'vod_id': path,
                'vod_name': name,
                'vod_pic': pic,
                'vod_remarks': remarks,
            })
        return out

    def homeContent(self, filter=''):
        # 分类 + 简单筛选（按更新/热度仅作展示，站点无对应 query 时仍走默认列表）
        filters = {
            'duanju': [{'key': 'order', 'name': '排序', 'value': [
                {'n': '默认', 'v': ''},
                {'n': '最新', 'v': 'new'},
                {'n': '热门', 'v': 'hot'},
            ]}],
            'manju': [{'key': 'order', 'name': '排序', 'value': [
                {'n': '默认', 'v': ''},
                {'n': '最新', 'v': 'new'},
                {'n': '热门', 'v': 'hot'},
            ]}],
            'zhenrenju': [{'key': 'order', 'name': '排序', 'value': [
                {'n': '默认', 'v': ''},
                {'n': '最新', 'v': 'new'},
                {'n': '热门', 'v': 'hot'},
            ]}],
            'shipin': [{'key': 'order', 'name': '排序', 'value': [
                {'n': '默认', 'v': ''},
                {'n': '最新', 'v': 'new'},
                {'n': '热门', 'v': 'hot'},
            ]}],
        }
        return {
            'class': [{'type_id': tid, 'type_name': name} for tid, name in CHANNELS],
            'filters': filters,
        }

    def homeVideoContent(self):
        try:
            src = self._get(BASE + '/')
            return {'list': self._cards(src)}
        except Exception:
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        tid = (tid or 'duanju').strip()
        if tid not in ('duanju', 'manju', 'zhenrenju', 'shipin'):
            tid = 'duanju'
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1

        # 解析筛选（站点无公开排序接口时忽略 order，仍返回对应分类页）
        order = ''
        if isinstance(extend, dict):
            order = (extend.get('order') or '').strip()
        elif isinstance(filter, dict):
            order = (filter.get('order') or '').strip()

        if pg == 1:
            url = BASE + '/' + tid + '/'
        else:
            url = BASE + '/' + tid + '/page/' + str(pg) + '/'
        try:
            src = self._get(url)
            items = self._cards(src)
            pages = re.findall(r'/' + re.escape(tid) + r'/page/(\d+)/', src or '')
            pagecount = max([int(p) for p in pages] + [pg]) if pages else (pg if not items else pg + 1)
            # 若首页有内容且无分页数字，至少保证能翻到下一页探测
            if pg == 1 and items and pagecount <= 1:
                pagecount = 50
            return {
                'list': items,
                'page': pg,
                'pagecount': pagecount,
                'limit': 24,
                'total': 0,
            }
        except Exception:
            return {'list': [], 'page': pg, 'pagecount': pg, 'limit': 24, 'total': 0}

    def detailContent(self, ids):
        path = ids[0] if isinstance(ids, list) else ids
        if not path:
            return {'list': []}
        if not path.startswith('http'):
            url = BASE + path if path.startswith('/') else BASE + '/' + path
        else:
            url = path
        try:
            src = self._get(url)
        except Exception:
            return {'list': []}
        if not src:
            return {'list': []}

        name = ''
        pic = ''
        # 详情页主图
        im = re.search(r'<img[^>]*class=["\'][^"\']*p-img[^"\']*["\'][^>]*>', src, re.I)
        if im:
            tag = im.group(0)
            am = re.search(r'\balt=["\']([^"\']+)["\']', tag, re.I)
            if am:
                name = _clean(am.group(1))
            pic = self._extract_pic(tag) or self._extract_pic(src)
        if not name:
            tm = re.search(r'<title[^>]*>(.*?)</title>', src, re.S | re.I)
            if tm:
                name = _clean(tm.group(1)).split(' - ')[0].split('-')[0].strip()
        if not pic:
            pic = self._extract_pic(src)

        content = ''
        dm = re.search(r'<meta\s+name=["\']description["\'][^>]*content=["\']([^"\']+)["\']', src, re.I)
        if dm:
            content = _clean(dm.group(1))
            content = content.replace('本页提供剧情简介、作品资料、标签与完整选集，点击选集进入播放页。', '').strip()
        if not content:
            cm = re.search(r'class=["\'][^"\']*desc[^"\']*["\'][^>]*>(.*?)</div>', src, re.S | re.I)
            if cm:
                content = _clean(cm.group(1))

        remarks = ''
        sm = re.search(r'<dt>\s*状态\s*</dt>\s*<dd>(.*?)</dd>', src, re.S | re.I)
        jm = re.search(r'<dt>\s*集数\s*</dt>\s*<dd>(.*?)</dd>', src, re.S | re.I)
        bits = []
        if sm:
            bits.append(_clean(sm.group(1)))
        if jm:
            bits.append(_clean(jm.group(1)))
        if not bits:
            em = re.search(r'class=["\']eps-flag["\'][^>]*>(.*?)</span>', src, re.S | re.I)
            if em:
                bits.append(_clean(em.group(1)))
        remarks = ' '.join(bits)

        # 选集
        eps = []
        seen = set()
        base_path = path if path.startswith('/') else '/' + path
        if not base_path.endswith('/'):
            base_path += '/'
        # 兼容相对与绝对
        ep_pat = re.compile(
            r'<a[^>]*href=["\'](' + re.escape(base_path) + r'\d+/)["\'][^>]*>(.*?)</a>',
            re.S | re.I,
        )
        for m in ep_pat.finditer(src):
            ep_url = m.group(1)
            txt = _clean(m.group(2))
            # 纯数字 或 “第x集”
            num = None
            if txt.isdigit():
                num = int(txt)
            else:
                nm = re.search(r'(\d+)', txt)
                if nm and ('集' in txt or len(txt) <= 4):
                    num = int(nm.group(1))
            if num is None:
                continue
            if ep_url in seen:
                continue
            seen.add(ep_url)
            eps.append((num, ep_url))
        # 若上面没抓到，再宽松匹配数字链接
        if not eps:
            for m in re.finditer(r'href=["\'](' + re.escape(base_path) + r'(\d+)/)["\']', src, re.I):
                ep_url, num_s = m.group(1), m.group(2)
                if ep_url in seen:
                    continue
                seen.add(ep_url)
                eps.append((int(num_s), ep_url))
        eps.sort(key=lambda x: x[0])
        # 去重保序
        uniq = []
        seen_n = set()
        for n, u in eps:
            if n in seen_n:
                continue
            seen_n.add(n)
            uniq.append((n, u))
        play_url = '#'.join('第%d集$%s' % (n, u) for n, u in uniq)

        vod = {
            'vod_id': path,
            'vod_name': name or '未知',
            'vod_pic': pic,
            'vod_content': content,
            'vod_remarks': remarks,
            'vod_play_from': '在线播放',
            'vod_play_url': play_url,
        }
        return {'list': [vod]}

    def searchContent(self, key, quick, pg='1'):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        # 站点搜索仅首页有效时限制；若有分页再放开
        q = urllib.parse.quote(key or '')
        if pg == 1:
            url = BASE + '/search/' + q + '/'
        else:
            url = BASE + '/search/' + q + '/page/' + str(pg) + '/'
        try:
            src = self._get(url)
            items = self._cards(src)
            return {'list': items, 'page': pg, 'pagecount': pg + (1 if items else 0), 'total': 0}
        except Exception:
            return {'list': []}

    def playerContent(self, flag, id, vipFlags):
        ep = id or ''
        if not ep.startswith('http'):
            url = BASE + ep if ep.startswith('/') else BASE + '/' + ep
        else:
            url = ep
        try:
            src = self._get(url, headers={'Referer': BASE + '/'})
        except Exception:
            src = ''
        m3u8 = ''
        # 1) 优先从页面 JSON 的 current.src 取完整地址（含 v/time/via 参数）
        m = re.search(r'"current"\s*:\s*\{[^}]*?"src"\s*:\s*"((?:[^"\\]|\\.)*)"', src or '')
        if m:
            m3u8 = _fix_url(m.group(1))
        if not m3u8:
            # 2) 任意带 \u0026 的完整 m3u8 字符串
            for m in re.finditer(r'"(https?://[^"]+\.m3u8[^"]*)"', src or '', re.I):
                cand = _fix_url(m.group(1))
                if '.m3u8' in cand.lower():
                    m3u8 = cand
                    if 'via=' in cand or 'v=' in cand:
                        break
        if not m3u8:
            # 3) 裸 URL 兜底
            for m in re.finditer(r'https?://[^\s"\'<>\\]+', src or ''):
                cand = _fix_url(m.group(0).rstrip('\\'))
                if '.m3u8' in cand.lower():
                    m3u8 = cand
                    if 'hls' in cand or 'zhqr' in cand or 'videos' in cand:
                        break
        # 补全站点要求的 query（缺 via 时补上，否则 CDN 常 403）
        if m3u8 and 'via=' not in m3u8:
            sep = '&' if '?' in m3u8 else '?'
            m3u8 = m3u8 + sep + 'v=3&time=0&via=91crdj&via_bm=dx'

        # CDN 鉴权头：优先从页面读取，失败则用已知默认值
        cdn_auth = '4aae16c3b20ec822f87518504478bb35'
        cdn_app = '158'
        am = re.search(r'"cdnAuthValue"\s*:\s*"([^"]+)"', src or '')
        if am:
            cdn_auth = am.group(1).strip()
        ap = re.search(r'"cdnApp"\s*:\s*"?([^,"}]+)"?', src or '')
        if ap:
            cdn_app = ap.group(1).strip().strip('"')

        header = {
            'User-Agent': UA,
            'Referer': BASE + '/',
            'Origin': BASE,
            'x-cdn-auth': cdn_auth,
            'x-cdn-app': cdn_app,
        }
        return {
            'parse': 0,
            'playUrl': m3u8,
            'url': m3u8,
            'header': header,
        }

    def localProxy(self, param):
        return [200, 'video/mpeg', '', '']

    def isVideoFormat(self, url):
        url = (url or '').lower()
        return (
            url.endswith('.m3u8')
            or url.endswith('.mp4')
            or '.m3u8?' in url
            or '.mp4?' in url
        )

    def manualVideoCheck(self):
        return False

    def action(self, action):
        return None
