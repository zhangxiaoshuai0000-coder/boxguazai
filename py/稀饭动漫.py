import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from base.spider import Spider as BaseSpider

SITE = 'https://next.xifanacg.com'
API = 'https://api.xifanacg.com'
SB_KEY = 'sb_publishable_OBIVAWACIX6lPXrO98_z24_HcsmalkA'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
BRAND = '蝴蝶影视'
TG = '🦋 TG群: @tvshare23'
PER_PAGE = 24

CLASSES = [
    {'type_id': '1', 'type_name': '连载新番'},
    {'type_id': '2', 'type_name': '完结旧番'},
    {'type_id': '3', 'type_name': '剧场版'},
    {'type_id': '4', 'type_name': '美漫'},
    {'type_id': 'all', 'type_name': '全部番剧'},
    {'type_id': 'hot', 'type_name': '人气榜单'},
]

FORMATS = [('tv', 'TV 动画'), ('movie', '剧场版'), ('ova', 'OVA'),
           ('oad', 'OAD'), ('web', 'Web 动画'), ('other', '其他')]

TAGS = ['漫画改', '小说改', '奇幻', '战斗', '原创', '恋爱', '校园', '日常',
        '百合', '后宫', '科幻', '游戏改', '悬疑', '冒险', '穿越', '音乐',
        '运动', '机战', '喜剧', '少年向', '推理', '少女向', '职场', '美食', '青年向']

SORTS = [('', '默认'), ('release_date', '最新'), ('view_count', '热度'), ('bangumi_score', '评分')]


def _rows():
    fm = [{'n': '全部', 'v': ''}] + [{'n': n, 'v': v} for v, n in FORMATS]
    tg = [{'n': '全部', 'v': ''}] + [{'n': t, 'v': t} for t in TAGS]
    yr = [{'n': '全部', 'v': ''}] + [{'n': str(y), 'v': str(y)} for y in range(2026, 2004, -1)]
    st = [{'n': n, 'v': v} for v, n in SORTS]
    return [
        {'key': 'format', 'name': '类型', 'value': fm},
        {'key': 'tag', 'name': '题材', 'value': tg},
        {'key': 'year', 'name': '年份', 'value': yr},
        {'key': 'sort', 'name': '排序', 'value': st},
    ]


FILTERS = {c['type_id']: _rows() for c in CLASSES}

RE_CARD = re.compile(
    r'<a aria-label="([^"]*)"[^>]*?href="/anime/(\d+)".*?'
    r'<img[^>]*?src="([^"]+)".*?'
    r'(?:aria-label="评分 ([\d.]+)")?.*?'
    r'(?:<div class="absolute right-0 bottom-0[^"]*"[^>]*>([^<]*)</div>)?',
    re.S)
RE_PIC = re.compile(r'<img[^>]*?src="(https://img2\.[^"]+)"')
RE_REMARK = re.compile(r'<div class="absolute right-0 bottom-0[^"]*"[^>]*>([^<]+)</div>')
RE_SCORE = re.compile(r'aria-label="评分 ([\d.]+)"')
RE_SUB = re.compile(r'text-xs text-ink-muted">([^<]+)<')
RE_TOTAL = re.compile(r'共\s*(?:<!-- -->)?\s*(\d+)')
RE_FLIGHT = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')


def _flight(html):
    out = []
    for p in RE_FLIGHT.findall(html or ''):
        try:
            out.append(json.loads(p))
        except Exception:
            continue
    return ''.join(out)


def _after(text, key):
    i = text.find(key)
    if i < 0:
        return None
    j = i + len(key)
    n = len(text)
    while j < n and text[j] in ' \t\r\n':
        j += 1
    try:
        return json.JSONDecoder().raw_decode(text, j)[0]
    except Exception:
        return None


def _qs(url):
    return urllib.parse.quote(url, safe=":/?&=%#@~+,;!*'()[]")


class Spider(BaseSpider):

    def init(self, extend=''):
        self._ext = extend
        self._net = getattr(self, 'net', None)
        self._mode = 'netfirst' if self._net is not None else 'auto'
        self._err = ''
        self._cache = {}
        self._dcache = {}
        self._lock = threading.Lock()
        self._host = SITE
        self._api = API
        self.brandActor = TG
        self.brandDirector = BRAND
        ext = extend
        if isinstance(ext, str) and ext.strip():
            try:
                ext = json.loads(ext)
            except Exception:
                ext = {}
        if isinstance(ext, dict):
            self._host = str(ext.get('site') or ext.get('host') or SITE).rstrip('/')
            self._api = str(ext.get('api') or API).rstrip('/')

    def getName(self):
        return BRAND

    def _format_remarks(self, tail):
        return '%s | %s' % (BRAND, tail) if tail else BRAND

    def _hdr(self, extra=None):
        h = {'User-Agent': UA, 'Accept-Encoding': 'identity', 'Accept-Language': 'zh-CN,zh;q=0.9'}
        if extra:
            h.update(extra)
        return h

    def _net_req(self, url, data, hdr, timeout):
        net = self._net
        opts = {'headers': hdr, 'timeout': int(timeout * 1000), 'method': 'POST' if data else 'GET'}
        if data is not None:
            opts['body'] = data.decode('utf-8') if isinstance(data, (bytes, bytearray)) else data
            opts['postType'] = 'json'
        last = None
        for call in (lambda: net.req(url, opts), lambda: net.req(url=url, **opts),
                     lambda: net.req(url, opts.get('method'), opts['body'] if data is not None else None, hdr)):
            try:
                return self._net_parse(call())
            except TypeError as e:
                last = e
                continue
        raise RuntimeError('net.req 调用失败: %s' % last)

    def _net_parse(self, r):
        if r is None:
            return -1, b''
        if isinstance(r, (bytes, bytearray)):
            return 200, bytes(r)
        if isinstance(r, str):
            return 200, r.encode('utf-8')
        if isinstance(r, dict):
            code = r.get('code') or r.get('status') or r.get('statusCode') or 200
            body = r.get('body')
            if body is None:
                body = r.get('data')
            if body is None:
                body = r.get('content')
            if body is None:
                body = r.get('text')
            if body is None:
                body = ''
            if isinstance(body, str):
                body = body.encode('utf-8')
            elif not isinstance(body, (bytes, bytearray)):
                body = json.dumps(body, ensure_ascii=False).encode('utf-8')
            return int(code), bytes(body)
        raise RuntimeError('无法识别的 net 响应')

    def _http(self, url, data=None, headers=None, timeout=15):
        hdr = self._hdr(headers)
        if self._net is not None and self._mode in ('net', 'netfirst'):
            try:
                code, raw = self._net_req(url, data, hdr, timeout)
                if self._mode == 'netfirst':
                    self._mode = 'net'
                return code, raw
            except Exception as e:
                self._err = 'net=%s' % e
                self._mode = 'auto'
        if self._mode == 'net' and self._net is not None:
            return self._net_req(url, data, hdr, timeout)
        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(url, data=data, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.getcode(), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except Exception as e:
            self._err = '%s: %s' % (type(e).__name__, e)
            if self._net is not None:
                try:
                    code, raw = self._net_req(url, data, hdr, timeout)
                    self._mode = 'net'
                    return code, raw
                except Exception as e2:
                    self._err = 'urllib=%s / net=%s' % (e, e2)
            return -1, b''

    def _decode(self, raw):
        if not raw:
            return ''
        for enc in ('utf-8', 'gbk'):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode('utf-8', 'replace')

    def _get(self, url, headers=None, timeout=15):
        code, raw = self._http(url, None, headers, timeout)
        if code != 200 and not raw:
            self._err = 'HTTP %s' % code
        return self._decode(raw)

    def _rpc(self, name, body, timeout=20):
        url = '%s/rest/v1/rpc/%s' % (self._api, name)
        hdr = {'apikey': SB_KEY, 'Authorization': 'Bearer %s' % SB_KEY,
               'Content-Type': 'application/json', 'Origin': self._host}
        code, raw = self._http(url, json.dumps(body).encode('utf-8'), hdr, timeout)
        txt = self._decode(raw)
        if code != 200:
            self._err = 'RPC %s HTTP %s %s' % (name, code, txt[:120])
            return None
        try:
            return json.loads(txt)
        except Exception:
            self._err = 'RPC %s 非 JSON' % name
            return None

    def _playback(self, ep_id, source_id=None, timeout=20):
        now = time.time()
        with self._lock:
            hit = self._cache.get(ep_id)
        if hit and now - hit[0] < 600:
            exp = hit[1].get('expires_at') or 0
            if not exp or now < exp - 60:
                return hit[1]
        url = '%s/functions/v1/issue-web-playback' % self._api
        body = {'action': 'fallback', 'episode_id': int(ep_id)}
        hdr = {'apikey': SB_KEY, 'Authorization': 'Bearer %s' % SB_KEY,
               'Content-Type': 'application/json', 'Origin': self._host}
        code, raw = self._http(url, json.dumps(body).encode('utf-8'), hdr, timeout)
        txt = self._decode(raw)
        if code != 200:
            self._err = '取流 HTTP %s %s' % (code, txt[:120])
            return None
        try:
            d = json.loads(txt)
        except Exception:
            self._err = '取流非 JSON'
            return None
        if not d.get('ok'):
            self._err = '取流失败 %s' % (d.get('error') or 'unknown')
            return None
        with self._lock:
            self._cache[ep_id] = (now, d)
        return d

    @staticmethod
    def _pick(data, source_id):
        cands = [c for c in (data.get('candidates') or []) if c.get('url')]
        if not cands:
            return ''
        if source_id:
            for c in cands:
                if str(c.get('source_id')) == str(source_id):
                    return c['url']
        for c in cands:
            if '.m3u8' in c['url'].split('?')[0].lower():
                return c['url']
        cands.sort(key=lambda c: 0 if '.mp4' in c['url'].split('?')[0].lower() else 1)
        return cands[0]['url']

    def _card(self, name, note, err):
        return {'vod_id': 'diag', 'vod_name': '⚠️ %s' % name, 'vod_pic': '',
                'vod_remarks': self._format_remarks(note), 'vod_content': '[诊断] %s' % err,
                'vod_tag': 'folder'}

    def _parse_cards(self, html):
        out = []
        seen = set()
        blocks = re.split(r'(?=<a aria-label=")', html or '')
        for b in blocks:
            m = re.match(r'<a aria-label="([^"]*)"[^>]*?href="/anime/(\d+)"', b)
            if not m:
                continue
            vid = m.group(2)
            if vid in seen:
                continue
            seen.add(vid)
            name = m.group(1).strip()
            pic = RE_PIC.search(b)
            sc = RE_SCORE.search(b[:4000])
            rm = RE_REMARK.search(b[:4000])
            sb = RE_SUB.search(b[:4000])
            out.append({
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': pic.group(1) if pic else '',
                'vod_remarks': (rm.group(1).strip() if rm else '') or (sb.group(1).strip() if sb else ''),
            })
        return out

    def _rpc_cards(self, rows):
        out = []
        for it in rows or []:
            try:
                vid = str(it.get('id'))
            except Exception:
                continue
            name = (it.get('title') or '').strip()
            if not vid or not name:
                continue
            cur = it.get('current_episodes') or 0
            tot = it.get('total_episodes') or 0
            if it.get('is_finished') and tot:
                tail = '全 %d 集' % tot
            elif cur and tot:
                tail = '更新至 %d/%d' % (cur, tot)
            elif cur:
                tail = '更新至 %d' % cur
            else:
                tail = str(it.get('release_year') or '')
            out.append({
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': it.get('cover_url') or '',
                'vod_remarks': self._format_remarks(tail),
            })
        return out

    def _query(self, tid, page, ext):
        body = {'search_term': '', 'page_number': int(page), 'items_per_page': PER_PAGE}
        if str(tid).isdigit():
            body['filter_type_id'] = int(tid)
        if tid == 'hot':
            body['sort_by'] = 'view_count'
            body['sort_order'] = 'desc'
        ext = ext if isinstance(ext, dict) else {}
        fmt = str(ext.get('format') or '').strip()
        tag = str(ext.get('tag') or '').strip()
        year = str(ext.get('year') or '').strip()
        sort = str(ext.get('sort') or '').strip()
        if fmt:
            body['filter_format'] = fmt
        if tag:
            body['filter_meta_tags'] = [tag]
        if year.isdigit():
            body['filter_release_year'] = int(year)
        if sort:
            body['sort_by'] = sort
            body['sort_order'] = 'desc'
        return body

    def homeContent(self, filter):
        rows = self._rpc('search_animes', {'search_term': '', 'page_number': 1,
                                           'items_per_page': 30, 'sort_by': 'release_date',
                                           'sort_order': 'desc'}) or []
        lst = self._rpc_cards(rows)
        if not lst:
            html = self._get('%s/' % self._host, None, 12)
            lst = self._parse_cards(html)[:30]
        out = {'class': [dict(c) for c in CLASSES], 'list': lst}
        if filter:
            out['filters'] = FILTERS
        return out

    def homeVideoContent(self):
        rows = self._rpc('search_animes', {'search_term': '', 'page_number': 1,
                                           'items_per_page': 30, 'sort_by': 'release_date',
                                           'sort_order': 'desc'}) or []
        lst = self._rpc_cards(rows)
        if not lst:
            html = self._get('%s/' % self._host)
            lst = self._parse_cards(html)[:30]
        return {'list': lst}

    def categoryContent(self, tid, pg, filter, extend):
        tid = str(tid)
        try:
            page = max(1, int(pg or 1))
        except Exception:
            page = 1
        rows = self._rpc('search_animes', self._query(tid, page, extend))
        if not isinstance(rows, list):
            card = self._card(tid, '第%s页' % page, self._err or '接口无返回')
            return {'list': [card], 'page': page, 'pagecount': page, 'limit': 1, 'total': 1}
        lst = self._rpc_cards(rows)
        total = 0
        if rows:
            try:
                total = int(rows[0].get('total_count') or 0)
            except Exception:
                total = 0
        if not lst:
            card = self._card(tid, '第%s页' % page, '该筛选无结果' if page == 1 else '已到末页')
            return {'list': [card], 'page': page, 'pagecount': page, 'limit': 1, 'total': 0}
        pages = max(1, (total + PER_PAGE - 1) // PER_PAGE) if total else page + 1
        return {'list': lst, 'page': page, 'pagecount': pages,
                'limit': len(lst), 'total': total or pages * PER_PAGE}

    def detailContent(self, ids):
        if not isinstance(ids, (list, tuple)):
            ids = [ids]
        ids = [str(i) for i in ids if str(i).strip()]
        out = []
        for vid in ids:
            try:
                out.append(self._detail(vid))
            except Exception as e:
                out.append({'vod_id': vid, 'vod_name': '解析异常',
                            'vod_play_from': BRAND, 'vod_play_url': '暂无片源$diag',
                            'vod_content': '[诊断] %s: %s' % (type(e).__name__, e)})
        if out:
            self._warm(out[0])
        return {'list': out}

    def _warm(self, vod):
        try:
            seg = (vod.get('vod_play_url') or '').split('$$$')[0]
            items = [x for x in seg.split('#') if '$' in x][:2]
            paths = [x.split('$', 1)[1] for x in items]
        except Exception:
            return
        if not paths:
            return

        def run():
            for p in paths:
                try:
                    ep = str(p).split('~')[0]
                    if ep.isdigit():
                        self._playback(ep)
                except Exception:
                    pass
        try:
            th = threading.Thread(target=run)
            th.daemon = True
            th.start()
        except Exception:
            pass

    def _detail(self, vid):
        out = {'vod_id': vid, 'vod_name': vid, 'vod_pic': '', 'vod_content': '',
               'vod_area': '', 'vod_year': '', 'vod_type': '', 'vod_lang': '',
               'vod_actor': self.brandActor, 'vod_director': self.brandDirector,
               'vod_remarks': ''}
        if not vid.isdigit():
            out['vod_play_from'] = BRAND
            out['vod_play_url'] = '暂无片源$diag'
            return out
        hit = self._dcache.get(vid)
        if hit and time.time() - hit[0] < 120:
            return dict(hit[1])
        html = self._get('%s/anime/%s' % (self._host, vid), None, 15)
        if not html:
            out['vod_play_from'] = BRAND
            out['vod_play_url'] = '暂无片源$diag'
            out['vod_content'] = '[诊断] 详情页 %s' % (self._err or '空')
            return out
        fly = _flight(html)
        anime = _after(fly, '"anime":') or {}
        sources = _after(fly, '"sources":') or []
        if not anime:
            m = re.search(r'<title>([^<]*)</title>', html)
            if m:
                out['vod_name'] = m.group(1).split('·')[0].strip()
        name = (anime.get('title') or '').strip()
        if name:
            out['vod_name'] = name
        out['vod_pic'] = anime.get('cover_url') or ''
        if not out['vod_pic']:
            p = RE_PIC.search(html)
            if p:
                out['vod_pic'] = p.group(1)
        out['vod_content'] = (anime.get('description') or '').strip()
        out['vod_year'] = str(anime.get('release_year') or '')
        out['vod_area'] = (anime.get('region') or '').strip()
        out['vod_type'] = (anime.get('format') or '').strip()
        d = (anime.get('director') or '').strip()
        if d:
            out['vod_director'] = d
        tags = anime.get('meta_tags') or []
        if isinstance(tags, list) and tags:
            out['vod_type'] = ' / '.join([str(t) for t in tags if t])
        score = anime.get('bangumi_score')
        if score not in (None, '', 0):
            out['vod_score'] = str(score)
        cur = anime.get('current_episodes') or 0
        tot = anime.get('total_episodes') or 0
        if anime.get('is_finished') and tot:
            tail = '全 %d 集' % tot
        elif cur and tot:
            tail = '更新至 %d/%d' % (cur, tot)
        else:
            tail = (anime.get('remarks') or '').strip() or '连载中'
        out['vod_remarks'] = self._format_remarks(tail)
        froms = []
        urls = []
        seen = set()
        for src in sources:
            sid = src.get('id')
            sname = (src.get('name') or '').strip() or '线路%s' % sid
            eps = []
            for ep in (src.get('episodes') or []):
                eid = ep.get('id')
                if not eid:
                    continue
                key = (str(eid), str(sid))
                if key in seen:
                    continue
                seen.add(key)
                num = ep.get('episode_number') or 0
                title = (ep.get('title') or '').strip()
                if num and str(anime.get('format') or '') == 'movie':
                    label = '正片'
                elif num:
                    label = '第%02d集' % int(num)
                elif title:
                    label = title
                else:
                    label = 'EP%s' % eid
                eps.append('%s$%s~%s~%s' % (label, eid, sid, vid))
            if eps:
                eps.sort(key=lambda x: int(re.sub(r'\D', '', x.split('$')[0]) or 0))
                froms.append(sname)
                urls.append('#'.join(eps))
        if froms:
            out['vod_play_from'] = '$$$'.join(froms)
            out['vod_play_url'] = '$$$'.join(urls)
        else:
            out['vod_play_from'] = BRAND
            out['vod_play_url'] = '暂无片源$diag'
            out['vod_content'] = (out['vod_content'] + '\n[诊断] 该番暂无片源').strip()
        self._dcache[vid] = (time.time(), dict(out))
        return out

    def _fallback(self, flag, raw, vid):
        play = ''
        parts = str(raw).split('~')
        if parts and parts[0].isdigit() and vid:
            play = '%s/anime/%s/play/%s' % (self._host, vid, parts[0])
            if len(parts) > 1 and parts[1]:
                play += '?source=%s' % parts[1]
        if play:
            return {'parse': 1, 'url': play, 'header': {'User-Agent': UA}}
        return {'parse': 0, 'url': play, 'header': {'User-Agent': UA}}

    def playerContent(self, flag, pid, vipFlags):
        raw = str(pid or '').strip()
        if raw.startswith('http'):
            return {'parse': 1, 'url': raw, 'header': {'User-Agent': UA}}
        parts = raw.split('~')
        ep = parts[0] if parts else ''
        sid = parts[1] if len(parts) > 1 else ''
        vid = parts[2] if len(parts) > 2 else ''
        if not ep.isdigit():
            return self._fallback(flag, raw, vid)
        data = self._playback(ep, sid if sid.isdigit() else None)
        if not data:
            return self._fallback(flag, raw, vid)
        url = self._pick(data, sid)
        if not url:
            self._err = '候选为空'
            return self._fallback(flag, raw, vid)
        return {'parse': 0, 'url': _qs(url), 'header': {'User-Agent': UA}}

    def searchContent(self, key, quick, pg='1'):
        try:
            page = max(1, int(pg or 1))
        except Exception:
            page = 1
        body = {'search_term': str(key or '').strip(), 'page_number': page,
                'items_per_page': PER_PAGE}
        rows = self._rpc('search_animes', body)
        if not isinstance(rows, list):
            return {'list': [], 'page': page}
        return {'list': self._rpc_cards(rows), 'page': page}

    def isVideoFormat(self, url):
        u = str(url or '').lower()
        return '.m3u8' in u or '.mp4' in u

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self._cache = {}
        self._dcache = {}


if __name__ == '__main__':
    import sys

    def _hr(t):
        print('\n' + '=' * 58)
        print(t)
        print('=' * 58)

    s = Spider()
    s.init('')

    _hr('分类')
    hc = s.homeContent(True)
    for c in hc['class']:
        print('  %-6s %s  (%d 组筛选)' % (c['type_id'], c['type_name'],
                                        len(hc['filters'].get(c['type_id'], []))))
    print('  首页 %d 条  首条: %s' % (len(hc.get('list') or []),
                                     (hc.get('list') or [{}])[0].get('vod_name', '-')))

    _hr('分类翻页')
    for tid in ('1', '2', '3', '4', 'all', 'hot'):
        t = time.time()
        r = s.categoryContent(tid, 1, False, {})
        l = r['list']
        print('  %-4s %2d 条 %.2fs pagecount=%-4s total=%-5s 首条: %s'
              % (tid, len(l), time.time() - t, r['pagecount'], r['total'],
                 l[0]['vod_name'][:24] if l else '-'))
    p1 = s.categoryContent('2', 1, False, {})['list']
    p2 = s.categoryContent('2', 2, False, {})['list']
    print('  翻页: p1首=%s p2首=%s -> %s'
          % (p1[0]['vod_id'] if p1 else '-', p2[0]['vod_id'] if p2 else '-',
             'OK' if p1 and p2 and p1[0]['vod_id'] != p2[0]['vod_id'] else 'FAIL'))

    _hr('子筛选')
    cases = [
        ('连载+TV动画', '1', {'format': 'tv'}),
        ('连载+奇幻', '1', {'tag': '奇幻'}),
        ('连载+2026', '1', {'year': '2026'}),
        ('连载+热度排序', '1', {'sort': 'view_count'}),
        ('完结+恋爱+2024', '2', {'tag': '恋爱', 'year': '2024'}),
        ('剧场版+2025', '3', {'year': '2025'}),
    ]
    for label, tid, ext in cases:
        r = s.categoryContent(tid, 1, False, ext)
        l = r['list']
        ok = bool(l) and l[0].get('vod_id') != 'diag'
        print('  %-16s %2d 条 total=%-5s %s %s'
              % (label, len(l), r['total'], 'OK ' if ok else 'FAIL',
                 l[0]['vod_name'][:20] if ok else ''))

    _hr('详情')
    vid = p1[0]['vod_id'] if p1 else '3468'
    t = time.time()
    d = s.detailContent([vid])['list'][0]
    print('  %s  %.2fs' % (d['vod_id'], time.time() - t))
    print('  名称: %s' % d['vod_name'])
    print('  封面: %s' % (d.get('vod_pic') or '')[:78])
    print('  类型: %s | 地区: %s | 年份: %s | 评分: %s'
          % (d.get('vod_type'), d.get('vod_area'), d.get('vod_year'), d.get('vod_score')))
    print('  演员: %s' % d.get('vod_actor'))
    print('  导演: %s' % d.get('vod_director'))
    print('  备注: %s' % d.get('vod_remarks'))
    print('  简介: %s' % (d.get('vod_content') or '')[:70])
    fl = d.get('vod_play_from', '').split('$$$')
    ul = d.get('vod_play_url', '').split('$$$')
    for i, f in enumerate(fl):
        n = len(ul[i].split('#')) if i < len(ul) else 0
        print('  线路%d: %-16s %d 集  首集: %s' % (i + 1, f, n, ul[i].split('#')[0][:40] if i < len(ul) else ''))

    _hr('取流')
    for i, f in enumerate(fl[:2]):
        if i >= len(ul):
            break
        pid = ul[i].split('#')[0].split('$', 1)[-1]
        t = time.time()
        pc = s.playerContent(f, pid, [])
        u = pc.get('url') or ''
        print('  %-16s parse=%s %.2fs' % (f, pc.get('parse'), time.time() - t))
        print('    %s' % u[:96])
        if u.startswith('http'):
            try:
                h = {'User-Agent': UA, 'Range': 'bytes=0-2047', 'Accept-Encoding': 'identity'}
                rr = urllib.request.urlopen(urllib.request.Request(
                    u, headers=h), timeout=25, context=ssl._create_unverified_context())
                head = rr.read()
                kind = 'm3u8' if head[:7] == b'#EXTM3U' else ('mp4' if b'ftyp' in head[:64] else '?')
                print('    校验 HTTP=%s %s %s size=%s'
                      % (rr.getcode(), kind, rr.headers.get('Content-Type'),
                         rr.headers.get('Content-Range') or '-'))
            except Exception as e:
                print('    校验失败 %s: %s' % (type(e).__name__, e))

    _hr('搜索')
    for kw in ('黑暗', '少女'):
        t = time.time()
        r = s.searchContent(kw, False, '1')
        l = r['list']
        print('  搜「%s」%d 条 %.2fs  首条: %s'
              % (kw, len(l), time.time() - t, l[0]['vod_name'] if l else '-'))

    _hr('结束')
    print('已完成')
