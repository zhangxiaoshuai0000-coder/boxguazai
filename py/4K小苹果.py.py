# -*- coding: utf-8 -*-
r"""
小苹果影视 蜘蛛源（修正版 v1.3.0）
=====================================================
相对原始脚本的改动：

1) 分类筛选补全
   - 电影/剧集/动漫：剧情(class) + 地区(area) + 语言(lang) + 年份(year) + 排序
   - 综艺/短剧：地区 + 年份 + 排序
   - 4K专区：分组(grp) + 排序
   - 奈飞专区：地区/语言/年份 + 排序
   - 服务端若不认某个筛选参数（返回空页），自动退回"只带排序"再取一次，
     保证永远不会因为筛选被静默筛空。
   - extend 兼容 dict / JSON 串 / 别名键（class_name、area_name、语言、年份…）

2) 线路"打不开"修复
   - 【核心 bug】原来线路名是 "源·画质"，播放时却把这个带画质的名字当
     vodPlayFrom 发给 /v5/videoUsableUrl，服务端认不出 → 必然空地址。
     现在播放统一用 payload 里保存的真实源名 (f)。
   - videoUsableUrl 三种参数编码方式依次重试（严格转义 / 不转义 / 保留 url 结构）
   - 分享页线路（非 maccms 直链）自动抓页面里的 m3u8（var main / json url / video src）
   - 奈飞专区（RRSP）线路优先走专用解密接口
   - token 本身是直链时直接透传，不再被 videoUsableUrl 返回空拖死
   - 会用首集做一次并发探活（默认开，可关），确认打不开的线路自动剔除
   - 播放返回的 header 按目标域名生成 Referer，减少 m3u8 403

3) 线路排序
   - 第 1 档：zijian 蓝光 4K（名字含 zijian/紫鉴 + 4K/蓝光）
   - 第 2 档：其他 4K / 2160 / UHD / 臻彩 线路
   - 第 3 档：非 4K 线路（其中蓝光、高清优先，其次直链集数多的）

4) 其他稳定性
   - 多 HOST 容灾（init 里可传 {"host": "ip:port"} 覆盖）
   - 请求超时/重试可控，列表接口失败会自动切下一个 HOST
   - 详情页分集按集数排序，避免乱序播放
   - 过滤 预告片/花絮/片花 之类的非正片条目

5) v1.2 修复：封面刷不出来 / 4K专区、奈飞专区空白
   - 封面：原来只认 http:// 且不处理 JSON 转义（https:\/\/、\u0026、&amp;、
     协议相对 //、中文路径），这类地址一律取不到 → 卡片只剩灰底。
     现在先解转义再取图，并优先挑 jpg/png/webp 等图片地址；图片字段为空时
     再扫整条记录的原始字节兜底；带中文/空格的地址会做 URL 编码。
   - 4K专区 / 奈飞专区：tag 接口按参数形态分三轮尝试（标准 / id+typeId1 /
     不带 page、tagId、pageNo），取到数据即停；全部为空时依次降级：
     4K专区 → 电影+剧集分类里挑 4K 条目 → 搜「4K」；
     奈飞专区 → 按地区取剧集 → 搜「奈飞」。三级兜底保证专区不再整片空白。
   - 列表解析加通用兜底：分组结构变化时，扫描所有子消息里带 id+名称的记录当卡片。

6) v1.3 修复：大部分封面仍然空
   - 列表里的图片字段多数是空的/不可直接用的，只靠列表拿不到封面。
     选图改成按打分挑：jpg/png/gif 优先（部分壳不认 webp/avif），
     upload/vod/poster/cover 路径加分，thumb/small/占位图扣分直接淘汰；
     并支持相对路径（/upload/...、upload/...，按接口主机补全）、
     百分号编码（https%3A%2F%2F）和 |、逗号、分号拼接的多地址。
   - 关键兜底：一页里没有封面的条目会用详情接口并发补图
     （最多 21 条、10 线程、单条 3 秒、总预算 6 秒，按 vod_id 缓存），
     列表封面与详情页保持一致。可用 PIC_FILL=False 关掉。
7) v1.4 修复：一大半封面还是灰底（电影 8/21、剧集 1/21 能刷出来）
   - 真因：列表/详情里的封面是"图片代理 + 多层 HTML 转义"——
     原值是 https://gimg0.baidu.com/gimg/app=2001&amp;amp;n=0&amp;amp;fmt=webp&amp;amp;src=真实地址#err，
     旧 _unpack 只解一层实体，剩下的 &amp; 正好撞上"URL 到分号就截断"的正则，
     最终交给壳的是 https://gimg0.baidu.com/gimg/app=2001&amp —— 必然 404。
   - 实体改成循环解码（&amp;amp;amp; 也能解干净），URL 字符集放开逗号
     （img1.baidu.com/it/u=数字,数字 截掉逗号会变 400），粘连的多个地址先拆再收。
   - 新增代理还原：src=/url=/img= 里的真实原图优先，代理链只当备选，并对
     baidu gimg / it 这类代理降权（会限流、会过期、境外不可达）。
   - 修掉"补图兜底从不触发"：_fill_pics 过去只判断封面是否为空，废地址非空
     所以永远不补；改成按可用性判断，返回前还会把残骸置空，让壳画占位图。
   - 实测：电影 21/21、剧集 21/21、综艺/动漫/短剧 21/21、4K专区 20/20、
     奈飞专区 40/40，抽样 24/24 张真实可拉取（jpg/png/webp）。

"""
import base64
import hashlib
import hmac
import json
import random
import re
import string
import time
import urllib.parse
import urllib.request
import uuid
import http.client

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad

try:
    from base.spider import Spider as _Base
except Exception:
    class _Base:
        pass

# ====================== 接口配置 ======================
HOST = '122.228.193.211'
PORT = 18008
# 容灾：第一个不通会自动尝试后面的（同名备用域名填在这里即可）
HOSTS = [
    (HOST, PORT),
]
PUB1 = 'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCduNEnfxGaLuQRk5ABzXHhPV43zi00sCHjLo8BYc+Wi6xXm2b4v0i28Sq4WlNCKhseft9fz8kO/qLr6/022o1RcuOU7e4GFL3U9WnNODwRBYSYWd+K8nqpI/tAUDmZEBGRWqjrc7x6aMl3A+xpnWkLbPCLsuhbuuUE3tv09oeOpwIDAQAB'
NATIVE = b'ed5fdsgucxumegqa'
DATAIV = b'OC1A06E197EF10CF3F6058CA7A803B5E'
DATAKEY = b'S0VNDTJHOFHHCNMRAW5IV2TOS2PBPQ=='
UA = 'okhttp/3.12.1'
REQ_TIMEOUT = 15
_RSA = PKCS1_v1_5.new(RSA.import_key(base64.b64decode(PUB1)))
UDID = uuid.uuid4().hex.upper()

# ====================== 页面分类 ======================
CATES = [('剧集', '2', 'c'), ('电影', '1', 'c'), ('综艺', '3', 'c'),
         ('动漫', '4', 'c'), ('短剧', '5', 'c'),
         ('4K专区', '117', 't'), ('奈飞专区', '115', 't')]
CATE_BY_ID = {t[1]: (t[0], t[2]) for t in CATES}

# ====================== 线路规则 ======================
# 确认无资源的线路源（命中即丢弃，可继续往后加，注意小写匹配）
DEAD_LINES = ('youku',)
# 排第 1 档：zijian 的蓝光 4K
KW_ZIJIAN = ('zijian', 'zijian4k', '紫鉴', '紫见', '紫剑', '子健', '紫鉴蓝光')
# 4K 判定关键词
KW_4K = ('4k', '2160', 'uhd', '超高清', '臻彩', '臻享', '杜比视界')
# 蓝光/高清判定关键词
KW_BD = ('蓝光', '原盘', '高清', '1080', '超清', 'hdr', 'hd')
# 非正片条目
SKIP_WORDS = ('预告片', '花絮', '片花', '精彩片段', '拍摄花絮')

# 详情页是否做首集并发探活（True：自动剔除打不开的线路，代价是详情页多 1~4 秒）
PROBE_LINES = True
PROBE_WORKERS = 8
PROBE_TIMEOUT = 3
PROBE_BUDGET = 5
# 至少保留几条有效线路才允许剔除（防止网络抖动时把线路全删光）
PROBE_KEEP_MIN = 2

# 列表接口给的封面为空时，用详情接口补图（封面大面积刷不出来的兜底）
# 弱源（谷歌图床等境内连不到的地址）是否还要留作最后退路：默认不留，宁可有图无图也别转圈
PIC_KEEP_WEAK = False
PIC_FILL = True
PIC_FILL_MAX = 21          # 每页最多补几条，控制耗时
PIC_FILL_WORKERS = 10
PIC_FILL_TIMEOUT = 3
PIC_FILL_BUDGET = 6        # 整体耗时上限（秒）

RR_API = 'api.rrmj.plus'
RR_SS = b'ES513W0B1CsdUrR13Qk5EgDAKPeeKZY'
RR_DK = b'3b744389882a4067'
RR_IV = b'b1da7878016e4e2b'
RR_REF = 'https://mh.yichengwlkj.com/'
RR_UA = ('Mozilla/5.0 (Linux; Android 16; PJX110) AppleWebKit/537.36 '
         '(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36')


# ====================== 筛选定义 ======================
def _vals(items, all_label='全部'):
    out = [{'n': all_label, 'v': ''}]
    for x in items:
        out.append({'n': x, 'v': x})
    return out


SORT_ITEM = {'key': 'vodOrderBy', 'name': '排序',
             'value': [{'n': '最新', 'v': '最新'},
                       {'n': '最热', 'v': '最热'},
                       {'n': '评分', 'v': '评分'}]}
SORT_ITEM2 = {'key': 'vodOrderBy', 'name': '排序',
              'value': [{'n': '最新', 'v': '最新'},
                        {'n': '最热', 'v': '最热'}]}

GENRE_MOVIE = ['剧情', '喜剧', '动作', '爱情', '科幻', '悬疑', '惊悚', '恐怖', '犯罪',
               '战争', '奇幻', '冒险', '历史', '家庭', '纪录', '动画', '武侠', '灾难',
               '同性', '歌舞']
GENRE_TV = ['都市', '古装', '悬疑', '爱情', '喜剧', '家庭', '动作', '犯罪', '科幻',
            '恐怖', '战争', '历史', '青春', '武侠', '仙侠', '奇幻', '农村', '年代',
            '谍战', '职场', '校园', '剧情']
GENRE_ANIME = ['热血', '战斗', '冒险', '搞笑', '恋爱', '科幻', '奇幻', '悬疑', '治愈',
               '日常', '少儿', '剧场版']
AREAS = ['大陆', '香港', '台湾', '美国', '韩国', '日本', '英国', '法国',
         '泰国', '印度', '其它']
LANGS = ['国语', '粤语', '英语', '韩语', '日语', '泰语', '其它']
YEARS = ['2026', '2025', '2024', '2023', '2022', '2021', '2020', '2019', '2018',
         '2017', '2016', '2015', '2014', '2013', '2012', '2011', '2010', '更早']
NF_AREAS = ['美剧', '韩剧', '日剧', '英剧']

FILTERS = {
    # 电影 / 剧集：剧情 + 地区 + 语言 + 年份 + 排序
    '1': [{'key': 'class', 'name': '剧情', 'value': _vals(GENRE_MOVIE)},
          {'key': 'area', 'name': '地区', 'value': _vals(AREAS)},
          {'key': 'lang', 'name': '语言', 'value': _vals(LANGS)},
          {'key': 'year', 'name': '年份', 'value': _vals(YEARS)},
          SORT_ITEM],
    '2': [{'key': 'class', 'name': '剧情', 'value': _vals(GENRE_TV)},
          {'key': 'area', 'name': '地区', 'value': _vals(AREAS)},
          {'key': 'lang', 'name': '语言', 'value': _vals(LANGS)},
          {'key': 'year', 'name': '年份', 'value': _vals(YEARS)},
          SORT_ITEM],
    # 综艺：地区 + 年份 + 排序
    '3': [{'key': 'area', 'name': '地区', 'value': _vals(AREAS)},
          {'key': 'year', 'name': '年份', 'value': _vals(YEARS)},
          SORT_ITEM],
    # 动漫：剧情 + 地区 + 年份 + 排序
    '4': [{'key': 'class', 'name': '剧情', 'value': _vals(GENRE_ANIME)},
          {'key': 'area', 'name': '地区', 'value': _vals(AREAS)},
          {'key': 'year', 'name': '年份', 'value': _vals(YEARS)},
          SORT_ITEM],
    # 短剧：地区 + 年份 + 排序
    '5': [{'key': 'area', 'name': '地区', 'value': _vals(AREAS)},
          {'key': 'year', 'name': '年份', 'value': _vals(YEARS)},
          SORT_ITEM2],
    # 4K 专区：分组（tag 接口不支持排序，故不放排序，避免空按钮）
    '117': [{'key': 'grp', 'name': '分组',
             'value': [{'n': '全部', 'v': ''},
                       {'n': '4K大片', 'v': '4K大片'},
                       {'n': '4K好剧', 'v': '4K好剧'}]}],
    # 奈飞专区：地区 + 语言 + 年份
    '115': [{'key': 'area', 'name': '地区', 'value': _vals(NF_AREAS, '精选')},
            {'key': 'lang', 'name': '语言', 'value': _vals(LANGS)},
            {'key': 'year', 'name': '年份', 'value': _vals(YEARS)}],
}
TAG_TYPES = {'117': ('1', '2'), '115': ('2',)}
TAG_MARK = {'117': ('4K',), '115': ('美剧', '韩国', '日本', '欧美', '英剧', '美国')}


# ====================== extend 解析 ======================
ALIAS = {
    'class': ('class', 'class_name', 'type_name', 'genre', '剧情'),
    'area': ('area', 'area_name', 'region', '地区'),
    'lang': ('lang', 'lang_name', 'language', '语言'),
    'year': ('year', '年份'),
    'grp': ('grp', 'group', '分组'),
    'sort': ('vodOrderBy', 'sort', 'order', '排序'),
}


def _ex_dict(extend):
    if not extend:
        return {}
    if isinstance(extend, dict):
        return extend
    try:
        d = json.loads(extend)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _ex_get(ex, name):
    for k in ALIAS.get(name, (name,)):
        if k not in ex:
            continue
        v = ex[k]
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (list, tuple)):
            # 部分壳把筛选项传成数组
            v = v[0] if v else ''
        s = str(v).strip()
        if s and s not in ('全部', 'null', 'None', 'undefined'):
            return s
    return ''


# ====================== 工具函数 ======================
def _rnd(n):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


def _varint(n):
    b = b''
    while True:
        x = n & 0x7f
        n >>= 7
        if n:
            b += bytes([x | 0x80])
        else:
            return b + bytes([x])


def _f(num, wire, payload):
    t = _varint((num << 3) | wire)
    if wire == 2:
        return t + _varint(len(payload)) + payload
    return t + payload


def _pb(buf):
    out, i, n = [], 0, len(buf)
    while i < n:
        try:
            tag = 0
            sh = 0
            while True:
                b = buf[i]
                i += 1
                tag |= (b & 0x7f) << sh
                sh += 7
                if not b & 0x80:
                    break
            fn, wt = tag >> 3, tag & 7
            if wt == 0:
                v = 0
                sh = 0
                while True:
                    b = buf[i]
                    i += 1
                    v |= (b & 0x7f) << sh
                    sh += 7
                    if not b & 0x80:
                        break
                out.append((fn, wt, v))
            elif wt == 2:
                ln = 0
                sh = 0
                while True:
                    b = buf[i]
                    i += 1
                    ln |= (b & 0x7f) << sh
                    sh += 7
                    if not b & 0x80:
                        break
                out.append((fn, wt, buf[i:i + ln]))
                i += ln
            elif wt == 5:
                out.append((fn, wt, buf[i:i + 4]))
                i += 4
            elif wt == 1:
                out.append((fn, wt, buf[i:i + 8]))
                i += 8
            else:
                break
        except Exception:
            break
    return out


def _txt(b):
    try:
        return b.decode('utf-8', 'replace')
    except Exception:
        return ''


def _flat(g):
    m = {}
    for fn, wt, v in _pb(g):
        if wt == 0:
            m[fn] = v
        elif wt == 2:
            m[fn] = _txt(v)
    return m


# 图片地址：兼容 http(s)、协议相对 //、转义 \/ 、实体 &amp; 、中文路径、百分号编码
# 逗号不能当截断字符: 百度图链 u=数字,数字 里逗号是参数本体, 截掉就变 400
_PIC_RE = re.compile(r'(?:https?:)?//[^\s"\'\x00-\x1f<>\\|;()\[\]{}]+')
# 多个地址用逗号紧贴拼接时, 先按逗号拆开再逐个收
_PIC_JOIN = re.compile(r',(?=(?:https?:)?//)')
_PIC_EXT = re.compile(r'\.(?:jpe?g|png|webp|gif|bmp|avif|heic)(?:[?#]|$)', re.I)
# 明显是占位图/头像，不能当封面
_PIC_BAD = ('placeholder', 'noimage', 'no_image', 'no-pic', 'nopic', 'default.',
            'blank.', 'loading.', 'transparent.', 'spacer.', 'avatar', 'icon.')
# 图片代理主机：能拿到原图就不用代理（会限流、会过期、境外还常被墙）
_PIC_PROXY = ('baidu.com/gimg', 'baidu.com/image', 'image.baidu.com',
              'baidu.com/it/', 'images.weserv.nl', 'imageproxy', '/proxy?')
_SRC_KEY = re.compile(r'[?&](?:src|url|img|image|imageUrl|pic|thumb)=([^\s"\'<>]+)', re.I)
_HOSTISH = re.compile(r'^[\w-]+(?:\.[\w-]+)+/\S+\.(?:jpe?g|png|webp|gif|avif)', re.I)
# 一眼就是没解干净的残骸：含 &amp、或以 & = ? 结尾
_PIC_DEAD = re.compile(r'&amp|%3[bB]amp|[?&=]$', re.I)
# 播放地址被当成封面捞出来的情况（m3u8/mp4 这类一定不是图）
_PIC_VIDEO = re.compile(r'\.(?:m3u8|mp4|flv|ts|m4s|mkv|avi|mov|wmv|rmvb|mpd)(?:[?#/]|$)|'
                        r'/\d+\.\d+/index|m3u8\?|/player/|/play\?', re.I)
# 相对路径的图片按这个前缀补全（同源，默认就是接口主机）
PIC_BASE = 'http://%s:%d' % (HOST, PORT)
# 站点脏数据：示例/测试域名，请求必然拿不到图
_PIC_JUNK = ('img.test.com', 'test.com/', 'example.com', 'yourdomain', 'xxx.com/',
             'thisisapicture')
# 弱源：谷歌图床/缓存，境内网络基本连不上；有别的就不用它，实在没有再退回来用
_PIC_WEAK = ('encrypted-tbn', 'gstatic.com', 'googleusercontent',
             'googleapis.com', 'ggpht.com')


_ENT_MAP = {'&amp;': '&', '&quot;': '"', '&lt;': '<', '&gt;': '>',
            '&#39;': "'", '&apos;': "'", '&#x27;': "'"}
_ENT_RE = re.compile(r'&(?:amp|quot|lt|gt|#39|apos|#x27);', re.I)


def _ent(s):
    """HTML 实体解码：封面地址会被转义 1~3 层，&amp;amp; 就是两层"""
    for _ in range(5):
        new = s
        for k, v in _ENT_MAP.items():
            new = new.replace(k, v)
        if _ENT_RE.search(new):
            new = _ENT_RE.sub(lambda mo: _ENT_MAP.get(mo.group(0).lower(), ''), new)
        if new == s:
            break
        s = new
    return s


def _unpack(s):
    """还原被 JSON/protobuf/HTML 转义过的字符串（反复解到不再变化为止）"""
    s = str(s or '')
    for _ in range(4):
        old = s
        s = (s.replace('\\/', '/').replace('\\u0026', '&')
             .replace('\\u003d', '=').replace('\\u003f', '?')
             .replace('\\u002f', '/'))
        s = _ent(s)
        if s == old:
            break
    if '%3A%2F%2F' in s.upper() or '%2F%2F' in s.upper():
        try:
            d = urllib.parse.unquote(s)
            if '//' in d:
                s = d
        except Exception:
            pass
    return s


def _quote_url(u):
    """把带中文/空格的地址安全编码，避免壳直接请求失败"""
    try:
        p = urllib.parse.urlsplit(u)
        path = urllib.parse.quote(p.path, safe="/%~:@!$&'()*+,;=-._")
        query = urllib.parse.quote(p.query, safe="=&%:/?+,-._~'()*;[]")
        return urllib.parse.urlunsplit((p.scheme, p.netloc, path, query, ''))
    except Exception:
        return u


def _unwrap_pic(u):
    """图片代理链 -> 真实原图地址（百度 gimg 把原图塞在 src= 里，尾部还会挂 #err）"""
    cur = str(u or '').split('#err')[0]
    for _ in range(3):
        mt = _SRC_KEY.search(cur)
        if not mt:
            break
        v = urllib.parse.unquote(mt.group(1)).strip().split('#err')[0]
        v = v.rstrip('\\,;:)]}>"\'.')
        if v.startswith('//'):
            v = 'https:' + v
        elif not v.lower().startswith('http'):
            if not _HOSTISH.match(v):
                break
            v = 'https://' + v
        if not v or v == cur:
            break
        cur = v
    return cur


def _pic_junk(u):
    """站点自己填的测试域名/示例图"""
    low = str(u or '').lower()
    return any(k in low for k in _PIC_JUNK)


def _pic_video(u):
    """是播放地址而不是图片（捞封面时会从整条记录里一起扫出来）"""
    return bool(_PIC_VIDEO.search(str(u or '')))


def _pic_weak(u):
    """境内多半刷不出来、但总比没有强的地址（谷歌图床）"""
    low = str(u or '').lower()
    return bool(low) and any(k in low for k in _PIC_WEAK)


def _pic_ok(u):
    """封面地址是否可用：http 开头、没被截断、不是占位图/脏数据/弱源"""
    s = str(u or '')
    if not s.lower().startswith('http') or _PIC_DEAD.search(s):
        return False
    low = s.lower()
    if any(k in low for k in _PIC_BAD) or _pic_junk(s) or _pic_video(s):
        return False
    return PIC_KEEP_WEAK or not _pic_weak(s)


def _all_pics(text):
    """从一个字符串里捞出所有可能是图片的地址（含相对路径）

    服务端封面有两种坑：
      1) 地址被 HTML 转义多层，只解一层时 URL 会在 &amp; 的分号处被截断，
         剩下 "https://gimg0.baidu.com/gimg/app=2001&amp" 这种必然 404 的残骸；
      2) 给的是图片代理，真实原图在 src= 参数里。
    先还原完整地址，再把代理拆成原图；原图排前面优先采用，代理留作备选。"""
    src = _unpack(text)
    out = []

    def _add(u):
        for one in _PIC_JOIN.split(str(u or '').split('#err')[0]):
            one = one.rstrip('\\,;:)]}>"\'.')
            if one.startswith('//'):
                one = 'https:' + one
            if (not one.lower().startswith('http') or _PIC_DEAD.search(one)
                    or _pic_video(one) or _pic_junk(one)):
                continue                 # 残骸丢掉，别让它占位挡住后面的补图
            one = _quote_url(one)
            if one not in out:
                out.append(one)

    for raw in _PIC_RE.findall(src):
        real = _unwrap_pic(raw)
        if real != raw:
            _add(real)
        _add(raw)
    if not out:
        # 相对路径：/upload/vod/xxx.jpg、upload/vod/xxx.jpg
        for p in re.findall(r'(/?upload/[^\s"\'<>,]+?\.(?:jpe?g|png|webp|gif|bmp))',
                            src, re.I):
            _add(PIC_BASE + '/' + p.lstrip('/'))
    return out


def _score_pic(u):
    """给候选图打分：正片海报优先，占位图直接淘汰"""
    low = u.lower()
    if any(k in low for k in _PIC_BAD):
        return -999
    s = 0
    if re.search(r'\.(jpe?g|png|gif|bmp)(?:[?#]|$)', low):
        s += 40                     # 壳普遍能显示的格式优先
    elif re.search(r'\.(webp|avif|heic)(?:[?#]|$)', low):
        s += 12                     # webp/avif 部分壳不支持，排后面
    else:
        s += 4
    for k in ('upload', '/vod/', 'poster', 'cover', 'images'):
        if k in low:
            s += 8
    if any(k in low for k in _PIC_PROXY):
        s -= 8                      # 有原图就不用代理链（代理会限流、会过期）
    if _pic_video(u):
        return -999                 # 播放地址绝不是封面
    if _pic_weak(u):
        if not PIC_KEEP_WEAK:
            return -999             # 境内连不到的谷歌图床，宁可不给让壳画占位图
        s -= 10                     # 开关打开时才把它排到最后当退路
    if 'thumb' in low or '/small' in low or '_s.' in low:
        s -= 6
    if 'x-oss-process' in low or 'image/format' in low:
        s -= 3
    s += min(len(u), 240) / 240.0
    return s


def _best_pic(cands):
    best, bscore = '', -999.0
    for u in cands:
        sc = _score_pic(u)
        if sc > bscore:
            best, bscore = u, sc
    return best if bscore > 0 else ''


def _pick_pic(text, allow_any=True):
    return _best_pic(_all_pics(text))


def _pic_from(raw, field2=''):
    """封面：图片字段 + 整条记录原始字节一起挑，按格式/路径打分取最优"""
    cands = _all_pics(field2)
    if raw:
        cands += _all_pics(_txt(raw))
    return _best_pic(cands)


def _norm(s):
    return re.sub(r'[\s\u3000·\-_]+', '', (s or '')).lower()


def _skipped(name):
    low = str(name or '')
    for w in SKIP_WORDS:
        if w in low:
            return True
    return False


def _grp_match(gname, want):
    gn = _norm(gname)
    if not gn or not want:
        return True
    return gn == want or want in gn or gn in want


def _fourk_card(c):
    t = ('%s %s' % (c.get('vod_name', ''), c.get('vod_remarks', ''))).lower()
    return any(k in t for k in ('4k', '2160', 'uhd', '杜比', '臻彩', '臻享', '蓝光'))


def _merge(*lists):
    out, seen = [], set()
    for lst in lists:
        for c in (lst or []):
            if c.get('vod_id') not in seen:
                seen.add(c['vod_id'])
                out.append(c)
    return out


def _card(m, raw=None):
    vid = str(m.get(3, ''))
    name = str(m.get(5, '') or '')
    if not vid or not name:
        return None
    if _skipped(name):
        return None
    return {'vod_id': vid, 'vod_name': name,
            'vod_pic': _pic_from(raw, m.get(2, '')),
            'vod_remarks': m.get(13, '') or m.get(26, '')}


def _ep_no(name):
    mm = re.search(r'(\d+)', name or '')
    return int(mm.group(1)) if mm else 10 ** 6


def _line_tier(name):
    """线路分档：0 = zijian 蓝光 4K；1 = 其他 4K；2 = 非 4K"""
    low = _norm(name)
    is4k = any(k in low for k in KW_4K) or ('4k' in low) or ('2160' in low)
    is_zd = any(k in low for k in KW_ZIJIAN)
    if is_zd and (is4k or '蓝光' in (name or '')):
        return 0
    if is4k:
        return 1
    return 2


def _line_key(item):
    name = item['name']
    tier = _line_tier(name)
    # 探活结果：0 有效 / 1 未知 / 2 失效
    ok = item.get('ok', 1)
    okrank = 0 if ok == 1 else (1 if ok == 2 else 2)
    low = _norm(name)
    bd = 0 if any(k in low for k in KW_BD) else 1
    return (tier, okrank, bd, -len(item['eps']), item['idx'])


def _clean_url(u):
    """把播放 token 修成可用地址"""
    s = (u or '').strip()
    if not s:
        return ''
    if '|' in s:
        s = s.split('|')[0].strip()
    if s.startswith('//'):
        s = 'https:' + s
    if not s.startswith('http') and '%' in s:
        try:
            d = urllib.parse.unquote(s)
            if d.startswith('http'):
                s = d
        except Exception:
            pass
    if s.startswith('http'):
        return s
    return ''


def _video_like(u):
    if not u:
        return False
    return bool(re.search(r'\.(m3u8|mp4|mkv|flv|ts|m4s|avi|mov)(\?|$)|\.mp4|'
                          r'/m3u8/|/hls/|m3u8\?|\.m3u8', u))


def _hdr(u, ua=None):
    try:
        o = urllib.parse.urlsplit(u or '')
        origin = '%s://%s' % (o.scheme, o.netloc) if o.netloc else ''
    except Exception:
        origin = ''
    h = {'User-Agent': ua or UA}
    if origin:
        h['Referer'] = origin + '/'
    return h


# ====================== 蜘蛛主体 ======================
class Spider(_Base):
    def getName(self):
        return '小苹果'

    def init(self, extend=''):
        self._url_cache = {}
        self._hosts = list(HOSTS)
        try:
            cfg = json.loads(extend) if extend and str(extend).strip().startswith('{') else None
            if isinstance(cfg, dict) and cfg.get('host'):
                hp = str(cfg['host']).split(':')
                nh = (hp[0], int(hp[1]) if len(hp) > 1 and hp[1].isdigit() else PORT)
                self._hosts = [nh] + self._hosts
        except Exception:
            pass
        return

    # ---------- 加密与请求 ----------
    def _pd(self, ts):
        r16 = base64.b64encode(_rnd(12).encode()).decode()
        sig = base64.b64encode(_RSA.encrypt((str(ts) + r16 + '1003').encode())).decode()
        b = base64.b64encode(AES.new(DATAIV, AES.MODE_ECB).encrypt(
            pad((str(ts) + r16).encode(), 16))).decode()
        J = {'country': 'CN', 'vName': '1.0.0.3', 'cpuId': '', 'young': 0,
             'facturer': 'OnePlus', 'pkg': 'com.juechufsh.android.xpg1',
             'uuid': UDID, 'resolution': '1080x2256',
             'mac': '02%3A00%3A00%3A00%3A00%3A00', 'sig': sig, 'abid': '2557',
             'model': 'PJX110', 'plat': 'android', 'udid': UDID, 'dpi': '480',
             'net': '1', 'lang': 'zh', 'random_str': r16, 'brand': 'OnePlus',
             'timestamp': ts, 'density': '3.0',
             'appName': '%E5%B0%8F%E8%8B%B9%E6%9E%9C%E5%BD%B1%E8%A7%86',
             'cpu': 'arm64-v8a', 'chid': '10000', 'carrier': '%E8%81%94%E9%80%9A',
             'sig2': b[:8], 'v': 1, 'sig3': b[8:], 'tenantId': 'xpg',
             '_vOsCode': '36', 'vOs': '16', 'vApp': '1003', 'device': 0,
             'androidID': UDID[:16].lower()}
        return AES.new(NATIVE, AES.MODE_CBC, NATIVE).encrypt(
            pad(json.dumps(J, separators=(',', ':')).encode(), 16)).hex()

    def _headers(self, ts):
        return {'User-Agent': UA, 'Cache-Control': 'no-cache',
                'Accept': 'application/x-protobuf',
                'Content-Type': 'application/x-protobuf',
                'publicParams': json.dumps({'paramsData': self._pd(ts)},
                                           separators=(',', ':'))}

    def _body(self, kvs, ts):
        f8 = _rnd(8)
        sb = '&'.join('%s=%s' % (k, v) for k, v in kvs.items() if str(v))
        aes = f8 + base64.b64encode(AES.new(DATAKEY, AES.MODE_ECB).encrypt(
            pad((sb + str(ts)).encode(), 16))).decode()
        return (_f(1, 2, aes[:20].encode()) + _f(2, 2, aes[20:].encode()) +
                _f(3, 2, _rnd(20).encode()) + _f(4, 0, _varint(ts)) +
                _f(5, 2, f8.encode()))

    def _req(self, method, ep, body=None, timeout=None, retry=1):
        """多 HOST 容灾 + 可调超时/重试"""
        hosts = getattr(self, '_hosts', HOSTS)
        to = timeout or REQ_TIMEOUT
        for h, p in hosts:
            for _ in range(max(1, retry)):
                try:
                    ts = int(time.time() * 1000)
                    conn = http.client.HTTPConnection(h, p, timeout=to)
                    conn.request(method, ep, body=body, headers=self._headers(ts))
                    r = conn.getresponse()
                    d = r.read()
                    conn.close()
                    if d:
                        return d
                except Exception:
                    continue
        return b''

    def _get(self, ep, timeout=None, retry=1):
        return self._req('GET', ep, timeout=timeout, retry=retry)

    def _post(self, ep, kvs, timeout=None, retry=1):
        return self._req('POST', ep, self._body(kvs, int(time.time() * 1000)),
                         timeout=timeout, retry=retry)

    def _data(self, raw):
        for fn, wt, v in _pb(raw):
            if fn == 3 and wt == 2:
                return v
        return b''

    # ---------- 列表解析 ----------
    def _scan_cards(self, data, seen=None):
        """通用兜底：只要子消息里带 id(3) + 名称(5) 就当卡片，抗 schema 变动"""
        out = []
        seen = seen if seen is not None else set()

        def _take(g):
            if not g or len(g) < 12:
                return
            c = _card(_flat(g), g)
            if c and c['vod_id'] not in seen:
                seen.add(c['vod_id'])
                out.append(c)

        for _fn, wt, g in _pb(data):
            if wt != 2:
                continue
            _take(g)
            for _f2, w2, gg in _pb(g):
                if w2 == 2:
                    _take(gg)
        return out

    def _v5list(self, raw):
        vids = []
        seen = set()
        data = self._data(raw)
        for fn, wt, g in _pb(data):
            if fn == 1 and wt == 2:
                c = _card(_flat(g), g)
                if c and c['vod_id'] not in seen:
                    seen.add(c['vod_id'])
                    vids.append(c)
        if not vids:
            vids = self._scan_cards(data, seen)
        return vids

    def _v4list(self, raw, grp=''):
        vids = []
        seen = set()
        want = _norm(grp)
        data = self._data(raw)
        for fn, wt, g in _pb(data):
            if fn != 31 or wt != 2:
                continue
            gname = ''
            items = []
            for f2, w2, item in _pb(g):
                if f2 == 1 and w2 == 2:
                    gname = _txt(item)
                elif f2 == 5 and w2 == 2:
                    items.append(item)
            if want and not _grp_match(gname, want):
                continue
            for item in items:
                c = _card(_flat(item), item)
                if c and c['vod_id'] not in seen:
                    seen.add(c['vod_id'])
                    vids.append(c)
        if not vids and not want:
            # 分组结构变了（或接口返回了另一种 schema）时走通用兜底
            vids = self._scan_cards(data, seen)
        return vids

    # ---------- 各类取数入口 ----------
    def _cat_list(self, type_id, page, extra=None, sort='最新'):
        base = {'pagesize': '21', 'typeId1': str(type_id),
                'page': str(page), 'vodOrderBy': sort or '最新'}
        if extra:
            kvs = dict(base)
            kvs.update(extra)
            vids = self._v5list(self._post('/api/proto/v5/drama/category', kvs))
            if vids:
                return vids
        return self._v5list(self._post('/api/proto/v5/drama/category', base))

    def _tag_list(self, tid, page, grp=''):
        """tag 专区：按参数形态分三轮尝试，取到数据即停，支持分页"""
        vids = []
        seen = set()

        def _one(path):
            raw = self._get(path, retry=2)
            if not raw:
                return
            got = self._v4list(raw, grp)
            if not got and grp:
                got = self._v4list(raw, '')
            for c in got:
                if c['vod_id'] not in seen:
                    seen.add(c['vod_id'])
                    vids.append(c)

        # 第一轮：标准形态（和 App 首页一致）
        _one('/api/proto/v4/tag/list/detail?pagesize=21&id=%s&page=%d' % (tid, page))
        # 第二轮：补上类型（4K专区=电影+剧集，奈飞=剧集），做多轮合并
        if not vids:
            for t in TAG_TYPES.get(str(tid), ()):
                _one('/api/proto/v4/tag/list/detail?pagesize=21&id=%s&typeId1=%s&page=%d'
                     % (tid, t, page))
        # 第三轮：老版本/换字段的接口形态
        if not vids:
            if page == 1:
                _one('/api/proto/v4/tag/list/detail?pagesize=21&id=%s' % tid)
            _one('/api/proto/v4/tag/list/detail?tagId=%s&pagesize=21&page=%d'
                 % (tid, page))
            if page > 1:
                _one('/api/proto/v4/tag/list/detail?pagesize=21&id=%s&pageNo=%d'
                     % (tid, page))
        return vids

    def _search_list(self, key, page=1):
        return self._v5list(self._post('/api/proto/v5/drama/search',
                                       {'searchKeys': key, 'page': str(page),
                                        'pagesize': '21'}))

    def _ret(self, vids, page):
        for c in vids or []:
            if _pic_ok(c.get('vod_pic')):
                continue
            if _pic_weak(c.get('vod_pic')):
                c['_weak_pic'] = c['vod_pic']   # 弱源先收着，补不到再退回用它
            c['vod_pic'] = ''                   # 残骸置空，壳画占位图而不是转圈
        vids = self._fill_pics(vids)
        for c in vids or []:
            w = c.pop('_weak_pic', '')
            if w and PIC_KEEP_WEAK and not c.get('vod_pic'):
                c['vod_pic'] = w        # 需要时再退回弱源，默认丢弃让壳画占位图
        full = len(vids) >= 21
        return {'list': vids, 'page': page,
                'pagecount': 9999 if full else max(page, 1),
                'limit': 21,
                'total': page * 21 if full else (page - 1) * 21 + len(vids)}

    def _fill_pics(self, vids):
        """列表没给封面时，用详情接口把封面补上（有上限、有总耗时预算）"""
        if not PIC_FILL or not vids:
            return vids
        cache = getattr(self, '_pic_cache', None)
        if cache is None:
            self._pic_cache = {}
            cache = self._pic_cache

        todo = []
        for c in vids:
            # 注意：以前只看"空不空"，被截断的废地址非空，补图永远不会触发
            if _pic_ok(c.get('vod_pic')):
                continue                      # 弱源/脏数据在 _ret 里已置空，会进队列
            cid = c.get('vod_id')
            if not cid:
                continue
            if cid in cache:
                if cache[cid]:
                    c['vod_pic'] = cache[cid]
                continue
            if len(todo) < PIC_FILL_MAX:
                todo.append(c)
        if not todo:
            return vids

        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
        except Exception:
            return vids

        def _one(vid):
            try:
                data = self._data(self._post('/api/proto/v5/drama/getDetail',
                                             {'id': vid},
                                             timeout=PIC_FILL_TIMEOUT, retry=1))
                for fn, wt, v in _pb(data):
                    if fn == 2 and wt == 2:
                        p = _all_pics(_txt(v))
                        pic = _best_pic(p)
                        if pic:
                            return pic
                # 图片不在字段 2 时，扫整条详情
                return _pick_pic(_txt(data))
                return ''
            except Exception:
                return ''

        try:
            with ThreadPoolExecutor(max_workers=PIC_FILL_WORKERS) as pool:
                futs = {pool.submit(_one, c['vod_id']): c for c in todo}
                for fu in as_completed(futs, timeout=PIC_FILL_BUDGET):
                    c = futs[fu]
                    try:
                        pic = fu.result(timeout=1) or ''
                    except Exception:
                        pic = ''
                    cache[c['vod_id']] = pic or ''
                    if pic and _pic_ok(pic) and not _pic_ok(c.get('vod_pic')):
                        c['vod_pic'] = pic
        except Exception:
            pass
        return vids

    # ---------- 首页 ----------
    def homeContent(self, filter=False):
        return {'class': [{'type_id': t[1], 'type_name': t[0]} for t in CATES],
                'filters': FILTERS}

    def homeVideoContent(self):
        try:
            return {'list': self._tag_list('117', 1)}
        except Exception:
            return {'list': []}

    # ---------- 分类 ----------
    def categoryContent(self, tid, pg, filter=False, extend=None):
        tid = str(tid)
        page = int(pg) if str(pg).isdigit() and int(pg) > 0 else 1
        mode = CATE_BY_ID.get(tid, ('', 'c'))[1]
        ex = _ex_dict(extend)
        srt = _ex_get(ex, 'sort') or '最新'
        cls = _ex_get(ex, 'class')
        area = _ex_get(ex, 'area')
        lang = _ex_get(ex, 'lang')
        year = _ex_get(ex, 'year')
        grp = _ex_get(ex, 'grp')

        extra = {}
        if cls:
            extra['vodClass'] = cls
        if area:
            extra['vodArea'] = area
        if lang:
            extra['vodLang'] = lang
        if year:
            extra['vodYear'] = year

        def _ret(vids):
            return self._ret(vids, page)

        try:
            if mode == 't' and tid == '117':
                # 4K 专区：tag 接口 -> 电影/剧集分类里挑 4K -> 搜「4K」，三级兜底保证不空
                vids = self._tag_list('117', page, grp)
                if not vids:
                    pool = _merge(self._cat_list('1', page, extra, srt),
                                  self._cat_list('2', page, extra, srt))
                    vids = [c for c in pool if _fourk_card(c)] or pool
                if not vids:
                    vids = self._search_list('4K', page)
                return _ret(vids)

            if mode == 't' and tid == '115':
                # 奈飞专区：tag 接口 -> 按地区取剧集 -> 搜「奈飞」
                vids = self._tag_list('115', page)
                if not vids:
                    if area or lang or year:
                        vids = self._cat_list('2', page, extra, srt)
                    else:
                        a = NF_AREAS[(page - 1) % len(NF_AREAS)]
                        sp = (page - 1) // len(NF_AREAS) + 1
                        vids = self._cat_list('2', sp, {'vodArea': a}, srt)
                if not vids:
                    vids = self._search_list('奈飞', page)
                return _ret(vids)

            # 普通分类
            vids = self._cat_list(tid, page, extra, srt)
            if not vids:
                vids = self._cat_list(tid, page, None, srt)
            return _ret(vids)
        except Exception:
            return {'list': [], 'page': page, 'pagecount': max(page, 1),
                    'limit': 21, 'total': 0}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick=False, pg='1'):
        page = int(pg) if str(pg).isdigit() and int(pg) > 0 else 1
        try:
            return self._ret(self._search_list(key, page), page)
        except Exception:
            return {'list': [], 'page': page, 'pagecount': 0, 'limit': 21, 'total': 0}

    # ---------- 详情 ----------
    def detailContent(self, ids):
        try:
            data = self._data(self._post('/api/proto/v5/drama/getDetail',
                                         {'id': ids[0]}))
            if not data:
                return {'list': []}
            head = {}
            eps = []
            pic = ''
            for fn, wt, v in _pb(data):
                if fn == 29 and wt == 2:
                    eps.append(_flat(v))
                elif wt == 2:
                    if fn == 2:
                        p = _all_pics(_txt(v))
                        pic = _best_pic(p)
                    elif fn in (5, 6, 9, 12, 15, 25, 26):
                        head[fn] = _txt(v)
                elif wt == 0 and fn == 18:
                    head[18] = str(v)

            lines = []          # 线路列表
            idx_map = {}        # (源, 画质) -> 线路下标
            for e in eps:
                src = e.get(9) or 'Ksvideo'
                if any(d in str(src).lower() for d in DEAD_LINES):
                    continue
                tok = e.get(4) or ''
                if not tok:
                    # 修复：token 缺失时，在其它字段里找现成的播放地址
                    for _k, _v in e.items():
                        if isinstance(_v, str) and _v.startswith('http'):
                            tok = _v
                            break
                if not tok:
                    continue
                q = e.get(10) or ''
                key = (src, q)
                if key not in idx_map:
                    idx_map[key] = len(lines)
                    lines.append({'src': src, 'q': q,
                                  'name': ('%s·%s' % (src, q)) if q else src,
                                  'eps': [], 'idx': len(lines), 'ok': 1})
                lines[idx_map[key]]['eps'].append(
                    (e.get(3) or str(len(lines[idx_map[key]]['eps']) + 1), tok))
            if not lines:
                return {'list': []}

            # 分集按集数排序，避免乱序
            for ln in lines:
                ln['eps'].sort(key=lambda x: _ep_no(x[0]))

            # 探活：确认打不开的线路剔除（失败则保留）
            if PROBE_LINES:
                self._probe(lines)

            # 排序：zijian蓝光4K -> 其他4K -> 非4K
            lines.sort(key=_line_key)

            # 剔除确认失效的线路
            good = [l for l in lines if l.get('ok') != 0]
            if len(good) >= PROBE_KEEP_MIN:
                lines = good

            order = [l['name'] for l in lines]
            play_url = []
            for l in lines:
                items = []
                for nm, tok in l['eps']:
                    payload = base64.b64encode(json.dumps(
                        {'f': l['src'], 'q': l['q'], 'u': tok},
                        separators=(',', ':')).encode()).decode()
                    items.append('%s$%s' % (nm, payload))
                play_url.append('#'.join(items))

            return {'list': [{'vod_id': ids[0], 'vod_name': head.get(9, ''),
                              'vod_pic': pic or _pick_pic(_txt(data)),
                              'vod_year': head.get(18, ''),
                              'vod_area': head.get(5, ''),
                              'vod_remarks': head.get(26, ''),
                              'vod_actor': head.get(25, ''),
                              'vod_director': head.get(12, ''),
                              'vod_content': re.sub(r'<[^>]+>', '', head.get(6, '')),
                              'vod_play_from': '$$$'.join(order),
                              'vod_play_url': '$$$'.join(play_url)}]}
        except Exception:
            return {'list': []}

    # ---------- 线路探活 ----------
    def _probe(self, lines):
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
        except Exception:
            return
        tasks = []
        for ln in lines:
            ln['ok'] = 2  # 未知
            if ln['eps']:
                tasks.append(ln)
        if not tasks:
            return

        def _check(line):
            try:
                u = self._vuu(line['src'], line['eps'][0][1], fast=True,
                              timeout=PROBE_TIMEOUT)
                if not u:
                    u = self._clean_direct(line['eps'][0][1])
                return bool(u)
            except Exception:
                return None

        deadline = time.time() + PROBE_BUDGET
        try:
            with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
                futs = {pool.submit(_check, ln): ln for ln in tasks}
                for f in as_completed(futs, timeout=PROBE_BUDGET):
                    if time.time() > deadline:
                        break
                    ln = futs[f]
                    try:
                        r = f.result(timeout=1)
                    except Exception:
                        r = None
                    ln['ok'] = 2 if r is None else (1 if r else 0)
        except Exception:
            pass

    # ---------- 播放地址解析 ----------
    def _vuu(self, pf, pu, fast=False, timeout=None):
        """把 (源名, 播放token) 换成真实地址；pf 必须是原始源名，不能带画质后缀"""
        if not pf and not pu:
            return ''
        cache = getattr(self, '_url_cache', None)
        if cache is None:
            self._url_cache = {}
            cache = self._url_cache
        ck = ('vuu', pf, pu)
        if ck in cache:
            return cache[ck]

        cands = [{'vodPlayFrom': urllib.parse.quote(pf),
                  'playUrl': urllib.parse.quote(pu, safe='')}]
        if not fast:
            cands.append({'vodPlayFrom': pf, 'playUrl': pu})
            cands.append({'vodPlayFrom': urllib.parse.quote(pf, safe=''),
                          'playUrl': urllib.parse.quote(pu, safe=':/?&=#')})
        for kv in cands:
            raw = self._post('/api/proto/v5/videoUsableUrl', kv,
                             timeout=timeout, retry=1)
            u = self._pull_url(raw)
            if u:
                cache[ck] = u
                return u
        return ''

    def _pull_url(self, raw):
        if not raw:
            return ''
        for buf in (self._data(raw), raw):
            if not buf:
                continue
            for fn, wt, v in _pb(buf):
                if wt == 2 and isinstance(v, (bytes, bytearray)):
                    t = v.decode('utf-8', 'replace')
                    m = re.search(r'https?://[^\x00-\x20"\'\\]+', t)
                    if m:
                        return self._fix_url(m.group(0))
            m = re.search(rb'https?://[^\x00-\x20"\'\\]+', buf)
            if m:
                return self._fix_url(m.group(0).decode('utf-8', 'replace'))
        return ''

    def _fix_url(self, u):
        s = (u or '').strip().strip('"').strip("'")
        s = s.replace('\\u0026', '&').replace('&amp;', '&').replace('\\/', '/')
        if s.startswith('//'):
            s = 'https:' + s
        if not s.startswith('http'):
            return ''
        return s

    def _clean_direct(self, pu):
        u = _clean_url(pu)
        if u and _video_like(u):
            return u
        return ''

    def _resolve(self, pf, pu):
        """完整解析链：奈飞专用 -> videoUsableUrl -> token 直链 -> 分享页抓取"""
        key = ('res', pf, pu)
        cache = getattr(self, '_url_cache', None)
        if cache is None:
            self._url_cache = {}
            cache = self._url_cache
        if key in cache:
            return cache[key]

        u = ''
        # 1) 奈飞专区（RRSP）
        if str(pf).upper().startswith('RR') or 'yichengwlkj.com' in (pu or ''):
            u = self._rrsp(pu)
        # 2) 官方可用地址接口
        if not u:
            u = self._vuu(pf, pu)
        # 3) token 本身是直链
        if not u:
            u = self._clean_direct(pu)
        # 4) 分享页：抓页面里的 m3u8
        if not u:
            page = _clean_url(pu)
            if page and not _video_like(page):
                u = self._share(page)
        if u:
            cache[key] = u
        return u

    def _fetch(self, url, referer=None, timeout=12):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': RR_UA, 'Accept': '*/*',
                'Referer': referer or _hdr(url)['Referer']})
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception:
            return b''

    def _share(self, page):
        """分享页/网页播放页里挖 m3u8（maccms 的 var main、json url、video src 都覆盖）"""
        try:
            body = self._fetch(page).decode('utf-8', 'replace')
            if not body:
                return ''
            body = body.replace('&amp;', '&').replace('\\/', '/')
            pats = [r'var\s+main\s*=\s*"([^"]+)"',
                    r'"url"\s*:\s*"(https?:[^"]+)"',
                    r'"m3u8"\s*:\s*"(https?:[^"]+)"',
                    r'<video[^>]+src="([^"]+)"',
                    r'source\s*:\s*"([^"]+)"',
                    r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)']
            for p in pats:
                mm = re.search(p, body)
                if not mm:
                    continue
                u = mm.group(1).strip()
                if u.startswith('//'):
                    u = 'https:' + u
                if u.startswith('http'):
                    return u
                if u.startswith('/'):
                    return urllib.parse.urljoin(page, u)
            return ''
        except Exception:
            return ''

    def _rr_call(self, path, params):
        try:
            ts = int(time.time() * 1000)
            dev = uuid.uuid4().hex
            qs = '&'.join('%s=%s' % (k, params[k]) for k in sorted(params))
            s = 'GET\naliId:%s\nct:web_applet\ncv:1.0.0\nt:%s\n%s?%s' % (
                dev, ts, path, qs)
            sg = base64.b64encode(hmac.new(RR_SS, s.encode(),
                                           hashlib.sha256).digest()).decode()
            req = urllib.request.Request(
                'https://%s%s?%s' % (RR_API, path, qs),
                headers={'x-ca-sign': sg, 't': str(ts), 'aliId': dev,
                         'umid': dev, 'deviceId': dev, 'clientVersion': '1.0.0',
                         'cv': '1.0.0', 'clientType': 'web_applet',
                         'ct': 'web_applet', 'uet': '9', 'User-Agent': RR_UA,
                         'Origin': RR_REF[:-1], 'Referer': RR_REF})
            body = urllib.request.urlopen(req, timeout=20).read()
            try:
                return json.loads(unpad(AES.new(RR_DK, AES.MODE_ECB).decrypt(
                    base64.b64decode(body)), 16).decode())
            except Exception:
                return json.loads(body.decode('utf-8', 'replace'))
        except Exception:
            return {}

    def _rrsp(self, pu):
        try:
            mm = re.search(r'/drama/(\d+)', pu or '')
            if not mm:
                return ''
            did = mm.group(1)
            m2 = re.search(r'episodeNo=(\d+)', pu)
            eno = int(m2.group(1)) if m2 else 1
            pg = self._rr_call('/m-station/drama/page',
                               {'hsdrOpen': 0, 'isAgeLimit': 0, 'dramaId': did,
                                'pageNum': 1, 'pageSize': 200})
            eps = ((pg.get('data') or {}).get('episodeList') or [])
            sid = ''
            for e in eps:
                if int(e.get('episodeNo') or 0) == eno:
                    sid = e.get('sid')
                    break
            if not sid and eps:
                sid = eps[0].get('sid')
            if not sid:
                return ''
            last = ''
            for _ in range(8):
                for q in ('HD', 'SD'):
                    pl = self._rr_call('/m-station/drama/play',
                                       {'hsdrOpen': 0, 'dramaId': did,
                                        'episodeSid': sid, 'quality': q,
                                        'hevcOpen': 0, 'tria4k': 0})
                    pd = pl.get('data') or {}
                    m3 = pd.get('m3u8') or {}
                    ns = pd.get('newSign') or ''
                    if not m3.get('url') or len(ns) < 20:
                        continue
                    u = unpad(AES.new(ns[4:20].encode(), AES.MODE_CBC,
                                      RR_IV).decrypt(
                        base64.b64decode(m3['url'])), 16).decode()
                    if 'auth_key=' in u:
                        return u
                    last = u
            return last
        except Exception:
            return ''

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags):
        pf, pu = flag or '', ''
        try:
            j = json.loads(base64.b64decode(id + '=' * (-len(id) % 4)).decode())
            pf = j.get('f') or pf      # 关键修复：用真实源名，不再用 "源·画质"
            pu = j.get('u') or ''
        except Exception:
            pu = id or ''
        # 兼容旧缓存/其它来源的 "源·画质" 线路名：取真实源名
        if '·' in str(pf):
            pf = str(pf).split('·')[0].strip()

        try:
            if str(pf).upper().startswith('RR') or 'yichengwlkj.com' in pu:
                u = self._rrsp(pu)
                if u:
                    return {'parse': 0, 'url': u,
                            'header': {'User-Agent': RR_UA, 'Referer': RR_REF}}

            u = self._resolve(pf, pu)
            if u:
                if _video_like(u):
                    return {'parse': 0, 'url': u, 'header': _hdr(u)}
                # 非视频直链：交给壳嗅探，比返回空地址（黑屏）有意义
                return {'parse': 1, 'url': u, 'header': _hdr(u)}

            page = _clean_url(pu)
            if page:
                return {'parse': 1, 'url': page, 'header': _hdr(page)}
            return {'parse': 0, 'url': '', 'header': {'User-Agent': UA}}
        except Exception:
            return {'parse': 0, 'url': '', 'header': {'User-Agent': UA}}

    def isVideoFormat(self, url):
        return _video_like(url or '')

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return [200, 'text/plain', '']


# ====================== 本地自检（可删） ======================
if __name__ == '__main__':
    s = Spider()
    s.init('')
    print('分类:', [c['type_name'] for c in s.homeContent(True)['class']])
    for tid in ('2', '1', '4', '3', '5', '117', '115'):
        r = s.categoryContent(tid, '1', True, {})
        print('分类 %-4s 第1页 %d 条' % (tid, len(r['list'])))
        if r['list']:
            print('   示例:', r['list'][0]['vod_name'])
    # 筛选抽查
    for tid, ex in (('2', {'class': '都市', 'area': '大陆', 'year': '2025'}),
                    ('1', {'class': '动作', 'lang': '英语'}),
                    ('4', {'class': '热血', 'area': '日本'})):
        r = s.categoryContent(tid, '1', True, ex)
        print('筛选 %s %s -> %d 条' % (tid, ex, len(r['list'])))
    # 详情 + 线路顺序
    rr = s.categoryContent('2', '1', True, {})
    if rr['list']:
        d = s.detailContent([rr['list'][0]['vod_id']])
        if d['list']:
            item = d['list'][0]
            print('详情:', item['vod_name'])
            print('线路顺序:', item['vod_play_from'].replace('$$$', ' | '))
            flags = item['vod_play_from'].split('$$$')
            urls = item['vod_play_url'].split('$$$')
            for f, u in zip(flags[:3], urls[:3]):
                pid = u.split('#')[0].split('$')[1]
                print('播放测试', f, '->', s.playerContent(f, pid, None).get('url', '')[:90])
#（注：内容由AI生成）
