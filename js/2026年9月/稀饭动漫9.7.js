import req from '../../util/req.js';
import * as cheerio from 'cheerio';

const classes = [
    { type_id: '1', type_name: '连载新番' },
    { type_id: '2', type_name: '完结旧番' },
    { type_id: '3', type_name: '剧场版' },
    { type_id: '21', type_name: '美漫' }
];

const classFilter = [
    { n: "全部", v: "" },
    { n: "搞笑", v: "搞笑" },
    { n: "原创", v: "原创" },
    { n: "轻小说改", v: "轻小说改" },
    { n: "恋爱", v: "恋爱" },
    { n: "百合", v: "百合" },
    { n: "漫改", v: "漫改" },
    { n: "校园", v: "校园" },
    { n: "战斗", v: "战斗" },
    { n: "治愈", v: "治愈" },
    { n: "奇幻", v: "奇幻" },
    { n: "日常", v: "日常" },
    { n: "青春", v: "青春" },
    { n: "乙女向", v: "乙女向" },
    { n: "悬疑", v: "悬疑" },
    { n: "后宫", v: "后宫" },
    { n: "科幻", v: "科幻" },
    { n: "冒险", v: "冒险" },
    { n: "热血", v: "热血" },
    { n: "异世界", v: "异世界" },
    { n: "游戏改", v: "游戏改" },
    { n: "音乐", v: "音乐" },
    { n: "偶像", v: "偶像" },
    { n: "美食", v: "美食" },
    { n: "耽美", v: "耽美" }
];

const areaFilter = [
    { n: "全部", v: "" },
    { n: "日本", v: "日本" },
    { n: "中国", v: "中国" },
    { n: "欧美", v: "欧美" }
];

const yearFilter = [
    { n: "全部", v: "" },
    { n: "2026", v: "2026" },
    { n: "2025", v: "2025" },
    { n: "2024", v: "2024" },
    { n: "2023", v: "2023" },
    { n: "2022", v: "2022" },
    { n: "2021", v: "2021" },
    { n: "2020", v: "2020" },
    { n: "2019", v: "2019" },
    { n: "2018", v: "2018" },
    { n: "2017", v: "2017" },
    { n: "2016", v: "2016" },
    { n: "2015", v: "2015" }
];

const sortFilter = [
    { n: "按最新", v: "time" },
    { n: "按最热", v: "hits" },
    { n: "按评分", v: "score" }
];

const filters = {};
classes.forEach(c => {
    filters[c.type_id] = [
        { key: 'class', name: '类型', value: classFilter },
        { key: 'area', name: '地区', value: areaFilter },
        { key: 'year', name: '年份', value: yearFilter },
        { key: 'by', name: '排序', value: sortFilter }
    ];
});

async function init() {
    return {};
}

async function home() {
    return {
        class: classes,
        filters: filters
    };
}

async function category(reqIn) {
    const body = reqIn?.body || {};
    const tid = body.id || '1';
    const pg = body.page || 1;
    const extend = body.filters || {};

    const sort = extend.by || 'time';
    const className = extend.class || '';
    const areaName = extend.area || '';
    const yearName = extend.year || '';

    // Build URL encoded post body
    const params = [];
    params.push(`type=${encodeURIComponent(tid)}`);
    params.push(`page=${encodeURIComponent(pg)}`);
    params.push(`by=${encodeURIComponent(sort)}`);
    if (className) params.push(`class=${encodeURIComponent(className)}`);
    if (areaName) params.push(`area=${encodeURIComponent(areaName)}`);
    if (yearName) params.push(`year=${encodeURIComponent(yearName)}`);

    const u = 'https://anime.xifanacg.com/index.php/ds_api/vod';
    const r = await req.post(u, params.join('&'), {
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-Requested-With': 'XMLHttpRequest',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    });

    const data = r.data;
    if (data.code === 1 && data.list) {
        const list = data.list.map(it => ({
            vod_id: it.url, // e.g. "/bangumi/3511.html"
            vod_name: it.vod_name,
            vod_pic: it.vod_pic,
            vod_remarks: it.vod_remarks || ''
        }));
        return {
            page: parseInt(pg),
            pagecount: data.pagecount || 1,
            limit: data.limit || 40,
            total: data.total || list.length,
            list
        };
    }

    return {
        page: parseInt(pg),
        pagecount: 1,
        limit: 40,
        total: 0,
        list: []
    };
}

async function detail(reqIn) {
    const body = reqIn?.body || {};
    const id = Array.isArray(body.id) ? body.id[0] : body.id; // e.g. "/bangumi/3511.html"

    const targetUrl = `https://anime.xifanacg.com${id}`;
    const r = await req.get(targetUrl, {
        headers: {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    });

    const $ = cheerio.load(r.data);
    const vod_name = $('.detail-info h3').text().trim();
    const vod_pic = $('.detail-pic img').attr('data-src') || $('.detail-pic img').attr('src');
    const vod_content = $('#height_limit').text().trim();

    let vod_director = '';
    let vod_actor = '';
    let vod_class = '';
    let vod_year = '';
    let vod_area = '';

    $('.detail-info .partition').each((i, el) => {
        const txt = $(el).text();
        if (txt.includes('导演')) {
            vod_director = txt.replace('导演 :', '').replace(/\s+/g, '').trim();
        } else if (txt.includes('演员')) {
            vod_actor = txt.replace('演员 :', '').replace(/\s+/g, '').trim();
        } else if (txt.includes('类型')) {
            vod_class = txt.replace('类型 :', '').replace(/\s+/g, '').trim();
        }
    });

    const yearText = $('.slide-info-remarks a[href*="/year/"]').text().trim();
    if (yearText) vod_year = yearText;
    const areaText = $('.slide-info-remarks a[href*="/area/"]').text().trim();
    if (areaText) vod_area = areaText;

    const playFroms = [];
    const playUrls = [];

    $('.anthology-tab .swiper-wrapper a').each((i, el) => {
        const name = $(el).text().replace(/\d+$/, '').replace(/\s+/g, '').trim();
        playFroms.push(name || `线路${i + 1}`);
    });

    $('.anthology-list .anthology-list-box').each((i, boxEl) => {
        const episodes = [];
        $(boxEl).find('li a').each((j, aEl) => {
            const epName = $(aEl).text().trim();
            const epHref = $(aEl).attr('href');
            if (epName && epHref) {
                episodes.push(`${epName}$${epHref}`);
            }
        });
        playUrls.push(episodes.join('#'));
    });

    const vod = {
        vod_id: id,
        vod_name,
        vod_pic,
        vod_content,
        vod_director,
        vod_actor,
        vod_class,
        vod_year,
        vod_area,
        vod_play_from: playFroms.join('$$$'),
        vod_play_url: playUrls.join('$$$')
    };

    return {
        list: [vod]
    };
}

async function search(reqIn) {
    const body = reqIn?.body || {};
    const wd = body.wd;

    // Use search suggest bypass endpoint to bypass captcha protection
    const u = `https://anime.xifanacg.com/index.php/ajax/suggest?mid=1&wd=${encodeURIComponent(wd)}`;
    const r = await req.get(u, {
        headers: {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    });

    const data = r.data;
    if (data.code === 1 && data.list) {
        const list = data.list.map(it => ({
            vod_id: `/bangumi/${it.id}.html`,
            vod_name: it.name,
            vod_pic: it.pic,
            vod_remarks: ''
        }));
        return { list };
    }

    return { list: [] };
}

async function play(reqIn) {
    const body = reqIn?.body || {};
    const id = body.id; // e.g. "/watch/3511/1/1.html"

    const targetUrl = `https://anime.xifanacg.com${id}`;
    const r = await req.get(targetUrl, {
        headers: {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    });

    const match = r.data.match(/var\s+player_aaaa\s*=\s*(.*?)(?:<\/script>|;)/);
    if (match) {
        const playerJson = JSON.parse(match[1]);
        const playUrl = playerJson.url;
        return {
            parse: 0,
            url: playUrl,
            header: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        };
    }

    throw new Error('未找到视频播放配置');
}

export default function createSpider(name, config) {
    return {
        meta: {
            key: 'xifan_anime',
            name: name || '稀饭动漫',
            type: 3,
        },
        api: async (fastify) => {
            fastify.post('/init', init);
            fastify.post('/home', home);
            fastify.post('/category', category);
            fastify.post('/detail', detail);
            fastify.post('/play', play);
            fastify.post('/search', search);
        },
    };
}
