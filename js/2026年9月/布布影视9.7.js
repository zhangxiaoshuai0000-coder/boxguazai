import req from '../../util/req.js';
import crypto from 'crypto';

const KEY = 'bubuzhuiju';
const NAME = '布布追剧';
const HOST = 'https://c453sddsc451azx.top';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36';

// WASM 解码常量（逆向所得）
const DECODE_FINGER = 'WF-2c064bc5b3400788f31b848849bc3a60f835423ba2dfe69d7ea93974c216e4f2';
const DECODE_ID = 'com.web.player';
const DECODE_SK = 'WEB-50a8e9c84a1dc05669a692ded99a2dac46527229e607a7be15db88dbc59059d1';

const API_HEADERS = {
    'Accept': 'application/json',
    'X-Client': '8f3d2a1c7b6e5d4c9a0b1f2e3d4c5b6a',
    'web-sign': 'f65f3a83d6d9ad6f',
    'User-Agent': UA,
};

const FALLBACK_CLASSES = [
    { type_id: '1', type_name: '电影' },
    { type_id: '2', type_name: '剧集' },
    { type_id: '3', type_name: '动漫' },
    { type_id: '4', type_name: '综艺' },
];

const CATE_NAME = { '1': '电影', '2': '剧集', '3': '动漫', '4': '综艺' };

// 解码缓存
const decodeCache = new Map();

// ==================== 工具函数 ====================

function bodyOf(reqIn) {
    return reqIn?.body || {};
}

function pageOf(value) {
    const p = Number.parseInt(value, 10);
    return Number.isFinite(p) && p > 0 ? p : 1;
}

function fixPic(url) {
    if (!url) return '';
    const raw = String(url);
    if (raw.startsWith('//')) return 'https:' + raw;
    if (raw.startsWith('/')) return HOST + raw;
    return raw;
}

function cleanTitle(raw) {
    if (!raw) return '未知标题';
    let text = String(raw).replace(/<[^>]+>/g, '');
    text = text.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
               .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&nbsp;/g, ' ');
    text = text.replace(/\s+/g, ' ').trim();
    return text || '未知标题';
}

async function getJson(path, params) {
    const res = await req.get(HOST + path, {
        params,
        headers: API_HEADERS,
        timeout: 15000,
    });
    return res.data;
}

// ==================== Protobuf 编解码 ====================

function encodeVarint(n) {
    const out = [];
    while (true) {
        const b = n % 128;
        n = Math.floor(n / 128);
        if (n) {
            out.push(b | 0x80);
        } else {
            out.push(b);
            return Buffer.from(out);
        }
    }
}

function bytesField(num, data) {
    const buf = Buffer.isBuffer(data) ? data : Buffer.from(data, 'utf8');
    return Buffer.concat([Buffer.from([num << 3 | 2]), encodeVarint(buf.length), buf]);
}

function varintField(num, val) {
    return Buffer.concat([Buffer.from([num << 3 | 0]), encodeVarint(val)]);
}

function buildDecodeRequest(url, flag, now, nonceHex) {
    if (!now) now = Math.floor(Date.now() / 1000);
    if (!nonceHex) nonceHex = crypto.randomBytes(16).toString('hex');
    const signSrc = `finger=${DECODE_FINGER}&id=${DECODE_ID}&nonce=${nonceHex}&sk=${DECODE_SK}&time=${now}&v=1`;
    const sign = crypto.createHash('sha256').update(signSrc, 'utf8').digest('hex').toUpperCase();
    return Buffer.concat([
        bytesField(1, url),
        bytesField(2, flag),
        varintField(3, now),
        bytesField(4, nonceHex),
        bytesField(5, sign),
        bytesField(6, DECODE_ID),
        varintField(7, 1),
    ]);
}

function parseProto(data) {
    const fields = {};
    let i = 0;
    while (i < data.length) {
        const tag = data[i]; i++;
        const wt = tag & 7;
        const fno = tag >> 3;
        if (wt === 2) {
            let ln = 0, mul = 1;
            while (true) {
                const x = data[i]; i++;
                ln += (x & 0x7f) * mul;
                if (!(x & 0x80)) break;
                mul *= 128;
            }
            fields[fno] = data.slice(i, i + ln);
            i += ln;
        } else if (wt === 0) {
            let v = 0, mul = 1;
            while (true) {
                const x = data[i]; i++;
                v += (x & 0x7f) * mul;
                if (!(x & 0x80)) break;
                mul *= 128;
            }
            fields[fno] = v;
        } else {
            break;
        }
    }
    return fields;
}

async function decodeUrl(code, flag) {
    const cacheKey = `${code}||${flag}`;
    if (decodeCache.has(cacheKey)) return decodeCache.get(cacheKey);
    const body = buildDecodeRequest(code, flag);
    const res = await req.post(HOST + '/api.php/web/decode/url', body, {
        headers: { 'Content-Type': 'application/x-protobuf', ...API_HEADERS },
        responseType: 'arraybuffer',
        timeout: 20000,
    });
    const data = Buffer.from(res.data);
    const fields = parseProto(data);
    if (fields[1] !== 1) return '';
    for (const v of Object.values(fields)) {
        if (Buffer.isBuffer(v)) {
            const idx = v.indexOf('http');
            if (idx >= 0) {
                const m3u8 = v.slice(idx).toString('utf8').replace(/\x00+$/, '').trim();
                decodeCache.set(cacheKey, m3u8);
                return m3u8;
            }
        }
    }
    return '';
}

// ==================== 路由实现 ====================

async function init() {
    return {};
}

async function home() {
    try {
        const d = await getJson('/api.php/web/index/home');
        const data = d?.data || {};
        const cats = (data.categories || []).map(c => ({
            type_id: String(c.type_id),
            type_name: c.type_name,
        }));
        return { class: cats.length ? cats : FALLBACK_CLASSES, filters: {}, list: [] };
    } catch (e) {
        console.warn(`[布布追剧] home 失败: ${e?.message || e}`);
        return { class: FALLBACK_CLASSES, filters: {}, list: [] };
    }
}

async function homeVod() {
    try {
        const d = await getJson('/api.php/web/index/home');
        const data = d?.data || {};
        const seen = new Set();
        const list = [];
        for (const c of data.categories || []) {
            for (const it of c.videos || []) {
                const vid = it.vod_id;
                if (seen.has(vid)) continue;
                seen.add(vid);
                list.push({
                    vod_id: vid,
                    vod_name: it.vod_name || '',
                    vod_pic: fixPic(it.vod_pic),
                    vod_remarks: it.vod_remarks || '',
                });
            }
        }
        return { list };
    } catch (e) {
        console.warn(`[布布追剧] homeVod 失败: ${e?.message || e}`);
        return { list: [] };
    }
}

async function category(reqIn) {
    const body = bodyOf(reqIn);
    const page = pageOf(body.page);
    const tid = String(body.id || '1');
    try {
        const params = { page, sort: 'hits' };
        const tname = CATE_NAME[tid];
        if (tname) params.type_name = tname;
        const d = await getJson('/api.php/web/filter/vod', params);
        const items = d?.data || [];
        const list = items.map(it => ({
            vod_id: it.vod_id,
            vod_name: it.vod_name,
            vod_pic: fixPic(it.vod_pic),
            vod_remarks: it.vod_remarks || '',
        }));
        const hasMore = items.length >= 18;
        return {
            page,
            pagecount: hasMore ? page + 1 : page,
            limit: 24,
            total: hasMore ? page * 24 : (page - 1) * 24 + list.length,
            list,
        };
    } catch (e) {
        console.warn(`[布布追剧] category 失败: ${e?.message || e}`);
        return { page, pagecount: page, limit: 24, total: 0, list: [] };
    }
}

async function detail(reqIn) {
    const ids = Array.isArray(reqIn?.body?.id) ? reqIn.body.id : [reqIn?.body?.id];
    const list = [];
    try {
        for (const rawId of ids.filter(Boolean)) {
            let vodId = String(rawId);
            if (vodId.startsWith('http')) {
                const m = vodId.match(/\/(\d+)\.html/);
                vodId = m ? m[1] : vodId;
            }
            const d = await getJson('/api.php/web/vod/get_detail', { vod_id: vodId });
            const items = d?.data || [];
            if (items.length > 0) {
                const item = items[0];
                list.push({
                    vod_id: String(item.vod_id || vodId),
                    vod_name: item.vod_name || '',
                    vod_pic: fixPic(item.vod_pic),
                    vod_remarks: item.vod_remarks || '',
                    vod_content: cleanTitle(item.vod_content || ''),
                    vod_year: item.vod_year || '',
                    vod_actor: item.vod_actor || '',
                    vod_director: item.vod_director || '',
                    vod_area: item.vod_area || '',
                    vod_play_from: item.vod_play_from || '',
                    vod_play_url: item.vod_play_url || '',
                });
            }
        }
    } catch (e) {
        console.warn(`[布布追剧] detail 失败: ${e?.message || e}`);
    }
    return { list };
}

async function play(reqIn) {
    const body = bodyOf(reqIn);
    const flag = String(body.flag || '');
    const id = String(body.id || '').trim();
    if (!id) return { parse: 0, url: '', header: {} };
    try {
        const m3u8 = await decodeUrl(id, flag);
        if (!m3u8) return { parse: 0, url: id, header: {} };
        return { parse: 0, url: m3u8, header: { 'User-Agent': UA } };
    } catch (e) {
        console.warn(`[布布追剧] play 失败: ${e?.message || e}`);
        return { parse: 0, url: id, header: {} };
    }
}

async function search(reqIn) {
    const body = bodyOf(reqIn);
    const page = pageOf(body.page);
    const wd = String(body.wd || '').trim();
    if (!wd) return { page, pagecount: page, limit: 24, total: 0, list: [] };
    try {
        const d = await getJson('/api.php/web/search/index', { wd });
        const items = d?.data || [];
        const list = items.map(it => ({
            vod_id: it.vod_id,
            vod_name: it.vod_name,
            vod_pic: fixPic(it.vod_pic),
            vod_remarks: it.vod_remarks || '',
        }));
        return { page, pagecount: page, limit: 24, total: list.length, list };
    } catch (e) {
        console.warn(`[布布追剧] search 失败: ${e?.message || e}`);
        return { page, pagecount: page, limit: 24, total: 0, list: [] };
    }
}

export default function createSpider() {
    return {
        meta: { key: KEY, name: NAME, type: 3 },
        api: async (fastify) => {
            fastify.post('/init', init);
            fastify.post('/home', home);
            fastify.post('/homeVod', homeVod);
            fastify.post('/category', category);
            fastify.post('/detail', detail);
            fastify.post('/play', play);
            fastify.post('/search', search);
        },
    };
}
