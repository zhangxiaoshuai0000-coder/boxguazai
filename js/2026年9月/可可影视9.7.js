import req from '../../util/req.js';
import { load } from 'cheerio';

const HOST = 'https://103.51.147.112:51120';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

const classes = [
    { type_id: '1', type_name: '电影' },
    { type_id: '2', type_name: '连续剧' },
    { type_id: '3', type_name: '动漫' },
    { type_id: '4', type_name: '综艺纪录' },
    { type_id: '6', type_name: '短剧' }
];

function getVid(url) {
    if (!url) return '';
    let m = url.match(/\/detail\/(\d+)\.html/);
    if (m) return m[1];
    m = url.match(/\/play\/(\d+)-/);
    if (m) return m[1];
    return '';
}

function pageOf(value) {
    const p = Number.parseInt(value, 10);
    return Number.isFinite(p) && p > 0 ? p : 1;
}

async function getHtml(path) {
    const url = path.startsWith('http') ? path : HOST + path;
    const r = await req.get(url, {
        headers: {
            'User-Agent': UA,
            'Referer': HOST + '/'
        },
        timeout: 15000
    });
    return typeof r.data === 'string' ? r.data : String(r.data || '');
}

function parseVodItem(el, $) {
    const a = $(el).find('.v-item');
    const href = a.attr('href') || '';
    const vid = getVid(href);
    if (!vid) return null;

    // title: skip "可可影视-kekys.com" placeholder
    let title = '';
    $(el).find('.v-item-title').each((i, t) => {
        if (title) return;
        const txt = $(t).text().trim();
        if (txt && txt !== '可可影视-kekys.com') title = txt;
    });

    // pic: use data-original, skip placeholders
    let pic = '';
    $(el).find('img').each((i, img) => {
        if (pic) return;
        const src = $(img).attr('data-original') || '';
        if (src && !src.includes('placeholder') && !src.includes('logo_placeholder')) {
            pic = src;
        }
    });
    if (pic && pic.startsWith('/')) {
        pic = 'https://vres.zyxpedu.com' + pic;
    }

    // remarks
    let note = '';
    const bottom = $(el).find('.v-item-bottom span');
    if (bottom.length) note = bottom.text().trim();

    if (!title) return null;
    return { vod_id: vid, vod_name: title, vod_pic: pic, vod_remarks: note };
}

// ==================== 路由实现 ====================

async function init() {
    return {};
}

async function home() {
    return {
        class: classes,
        filters: {},
        list: []
    };
}

async function homeVod() {
    try {
        const html = await getHtml('/channel/1.html');
        const $ = load(html);
        const list = [];
        const seen = new Set();
        $('.module-item').each((i, el) => {
            const item = parseVodItem(el, $);
            if (item && !seen.has(item.vod_id)) {
                seen.add(item.vod_id);
                list.push(item);
            }
        });
        return { list: list.slice(0, 24) };
    } catch (e) {
        console.error('homeVod error:', e.message);
        return { list: [] };
    }
}

async function category(reqIn) {
    const body = reqIn?.body || {};
    const tid = body.id || '1';
    const pg = pageOf(body.page);

    try {
        const html = await getHtml(`/channel/${tid}.html?page=${pg}`);
        const $ = load(html);
        const list = [];
        $('.module-item').each((i, el) => {
            const item = parseVodItem(el, $);
            if (item) list.push(item);
        });
        return {
            page: pg,
            pagecount: list.length > 0 ? pg + 1 : pg,
            limit: list.length,
            total: list.length,
            list
        };
    } catch (e) {
        console.error('category error:', e.message);
        return { page: pg, pagecount: pg, limit: 0, total: 0, list: [] };
    }
}

async function detail(reqIn) {
    const body = reqIn?.body || {};
    const ids = Array.isArray(body.id) ? body.id : [body.id];
    const list = [];

    for (const vid of ids.filter(Boolean)) {
        try {
            const html = await getHtml(`/detail/${vid}.html`);

            // title
            let title = '';
            const titleMatch = html.match(/<title>(.+?)<\/title>/);
            if (titleMatch) {
                title = titleMatch[1].split('-')[0].trim();
                title = title.replace(/[\u{1D55C}\u{1D55C}\u{1D566}\u{1D564}\u{1D7D8}\u{1D7D9}\u{1D55C}\u{1D560}\u{1D55E}.\s]+/gu, ' ');
                title = title.replace(/\s+/g, ' ').trim();
            }

            // pic
            let pic = '';
            const ogImg = html.match(/<meta\s+property="og:image"\s+content="([^"]+)"/);
            if (ogImg) {
                pic = ogImg[1];
                if (pic.startsWith('/')) pic = 'https://vres.zyxpedu.com' + pic;
            }

            // desc
            let desc = '';
            const descMatch = html.match(/<meta\s+name="description"\s+content="([^"]+)"/);
            if (descMatch) desc = descMatch[1].trim();

            // play episodes
            const episodesBySid = {};
            const sidsInOrder = [];
            const seenSids = new Set();

            // pattern 1: href before class
            let allPlay = [...html.matchAll(/<a[^>]+href="(\/play\/\d+-(\d+)-(\d+)\.html)"[^>]+class="episode-item"[^>]*>(.*?)<\/a>/g)];
            // pattern 2: class before href
            if (allPlay.length === 0) {
                allPlay = [...html.matchAll(/<a[^>]+class="episode-item"[^>]+href="(\/play\/\d+-(\d+)-(\d+)\.html)"[^>]*>(.*?)<\/a>/g)];
            }

            for (const m of allPlay) {
                const href = m[1];
                const sid = m[2];
                const text = m[4].replace(/<[^>]+>/g, '').trim();
                if (!text) continue;
                if (!episodesBySid[sid]) episodesBySid[sid] = [];
                episodesBySid[sid].push(`${text}$${href}`);
                if (!seenSids.has(sid)) {
                    seenSids.add(sid);
                    sidsInOrder.push(sid);
                }
            }

            // source labels
            const sourceLabels = [];
            const allLabels = html.matchAll(/class="source-item-label"[^>]*>([^<]+)</g);
            for (const m of allLabels) {
                const label = m[1].trim();
                if (label) sourceLabels.push(label);
            }

            const playFroms = [];
            const playUrls = [];
            for (let i = 0; i < sidsInOrder.length; i++) {
                const sid = sidsInOrder[i];
                if (!episodesBySid[sid] || episodesBySid[sid].length === 0) continue;
                const lineName = i < sourceLabels.length ? sourceLabels[i] : `线路${sid}`;
                // skip 4K line (APP only)
                if (lineName === '4K') continue;
                playFroms.push(lineName);
                playUrls.push(episodesBySid[sid].join('#'));
            }

            list.push({
                vod_id: vid,
                vod_name: title,
                vod_pic: pic,
                type_name: '',
                vod_year: '',
                vod_area: '',
                vod_remarks: '',
                vod_actor: '',
                vod_director: '\u661F\u6CB3', // 星河 - site mark
                vod_content: desc,
                vod_play_from: playFroms.join('$$$'),
                vod_play_url: playUrls.join('$$$')
            });
        } catch (e) {
            console.error('detail error:', e.message);
        }
    }

    return { list };
}

async function play(reqIn) {
    const body = reqIn?.body || {};
    let playUrl = body.id || '';
    if (playUrl && !playUrl.startsWith('http')) {
        playUrl = HOST + playUrl;
    }

    try {
        const html = await getHtml(playUrl);

        let videoUrl = '';
        const patterns = [
            /src:\s*["']([^"']+\.(?:m3u8|mp4)[^"']*)["']/,
            /"url"\s*:\s*"([^"]+\.(?:m3u8|mp4)[^"]*)"/
        ];
        for (const pat of patterns) {
            const m = html.match(pat);
            if (m) { videoUrl = m[1]; break; }
        }

        if (!videoUrl) {
            const allUrls = [...html.matchAll(/https?:\/\/[^\s"'<>]+\.(?:m3u8|mp4)[^\s"'<>]*/g)];
            if (allUrls.length > 0) {
                for (const m of allUrls) {
                    const u = m[0];
                    if (u.includes('index.m3u8') || u.includes('video.m3u8') || u.includes('.mp4')) {
                        videoUrl = u;
                        break;
                    }
                }
                if (!videoUrl) videoUrl = allUrls[0][0];
            }
        }

        if (videoUrl) {
            return {
                parse: 0,
                url: videoUrl,
                header: {
                    'User-Agent': UA,
                    'Referer': HOST + '/'
                }
            };
        }
    } catch (e) {
        console.error('play error:', e.message);
    }

    // fallback: let client sniff
    return {
        parse: 1,
        url: playUrl,
        header: {
            'User-Agent': UA,
            'Referer': HOST + '/'
        }
    };
}

async function search(reqIn) {
    const body = reqIn?.body || {};
    const key = String(body.wd || '').trim();
    const pg = pageOf(body.page);

    if (!key) {
        return { page: pg, pagecount: pg, limit: 0, total: 0, list: [] };
    }

    try {
        // first request to get CSRF token
        let html = await getHtml(`/search?k=${encodeURIComponent(key)}`);
        let tMatch = html.match(/name="t" value="([^"]+)"/);
        const t = tMatch ? tMatch[1] : '';

        if (t) {
            let url = `/search?k=${encodeURIComponent(key)}&t=${encodeURIComponent(t)}`;
            if (pg > 1) url += `&page=${pg}`;
            html = await getHtml(url);
        }

        const $ = load(html);
        const list = [];
        $('.search-result-item').each((i, el) => {
            const href = $(el).attr('href') || '';
            const vid = getVid(href);
            if (!vid) return;

            // title
            let title = '';
            const titleEl = $(el).find('.title');
            if (titleEl.length) title = titleEl.text().trim();
            if (!title) {
                const img = $(el).find('img');
                if (img.length) {
                    title = (img.attr('alt') || img.attr('title') || '').trim();
                }
            }

            // pic
            let pic = '';
            $(el).find('img').each((j, img) => {
                if (pic) return;
                const src = $(img).attr('data-original') || $(img).attr('src') || '';
                if (src && !src.includes('placeholder') && !src.includes('logo_placeholder')) {
                    pic = src;
                }
            });
            if (pic && pic.startsWith('/')) pic = 'https://vres.zyxpedu.com' + pic;

            if (title) {
                list.push({ vod_id: vid, vod_name: title, vod_pic: pic, vod_remarks: '' });
            }
        });

        return {
            page: pg,
            pagecount: list.length > 0 ? pg + 1 : pg,
            limit: list.length,
            total: list.length,
            list
        };
    } catch (e) {
        console.error('search error:', e.message);
        return { page: pg, pagecount: pg, limit: 0, total: 0, list: [] };
    }
}

export default function createSpider(name, config) {
    return {
        meta: {
            key: 'kekevod',
            name: name || '可可影视',
            type: 3
        },
        api: async (fastify) => {
            fastify.post('/init', init);
            fastify.post('/home', home);
            fastify.post('/homeVod', homeVod);
            fastify.post('/category', category);
            fastify.post('/detail', detail);
            fastify.post('/play', play);
            fastify.post('/search', search);
        }
    };
}
