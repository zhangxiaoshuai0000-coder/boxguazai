import req from './nodejs/src/util/req.js';

// DRPY rule object definition
const rule = {
    类型: '短剧',
    title: '星芽短剧',
    desc: '星芽短剧纯js版本',
    host: 'https://app.whjzjx.cn',
    url: '/cloud/v2/theaterfyfilter',
    filter_url: '/home_page?theater_class_id=fyclass&type=1&{{fl.type or "class2_ids=0"}}&page_num=fypage&page_size=24',
    searchUrl: '/v3/search',
    searchable: 2,
    quickSearch: 1,
    filterable: 1,
    headers: {
        'User-Agent': 'okhttp/4.10.0',
        'Accept-Encoding': 'gzip',
        'x-app-id': '7',
        'platform': '1',
        'manufacturer': 'realme',
        'version_name': '3.3.1',
        'user_agent': 'Mozilla/5.0 (Linux; Android 9; RMX1931 Build/PQ3A.190605.05081124; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/91.0.4472.114 Mobile Safari/537.36',
        'dev_token': 'BFdbZBGOEgG7QDt01ldOQNNfhO2F-rv4QcugZoFZm5_3DlPJEo_bSBeJ6dW2X3eKzxxKKWz3xJCM_u5PppGMqRuYPxcsVg9a-jriWiIoPZvHMSLbcbxTFuasqgTivTY3GabW1yP57LQSsJNQfKoX1BKYGHducrhb0bTwvigfn3gE*',
        'app_version': '3.1.0.1',
        'device_platform': 'android',
        'personalized_recommend_status': '1',
        'device_type': 'RMX1931',
        'device_brand': 'realme',
        'os_version': '9',
        'channel': 'default',
        'raw_channel': 'default',
        'oaid': '',
        'msa_oaid': '',
        'uuid': 'randomUUID_8a0324bf-03c8-4789-8ef8-12d3bcff28f5',
        'device_id': '24250683a3bdb3f118dff25ba4b1cba1a',
        'ab_id': '',
        'support_h265': '1'
    },
    timeout: 5000,
    class_name: '剧场&热播剧&会员专享&星选好剧&新剧&阳光剧场',
    class_url: '1&2&8&7&3&5',
    play_parse: true,
    class_parse: async () => {},
    预处理: async () => {
        let html = await post('https://u.shytkjgs.com/user/v1/account/login', {
            headers: {
                'User-Agent': 'okhttp/4.10.0',
                'Accept-Encoding': 'gzip',
                'Content-Type': 'application/x-www-form-urlencoded',
                'x-app-id': '7',
                'platform': '1',
                'manufacturer': 'realme',
                'version_name': '3.3.1',
                'user_agent': 'Mozilla/5.0 (Linux; Android 9; RMX1931 Build/PQ3A.190605.05081124; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/91.0.4472.114 Mobile Safari/537.36',
                'app_version': '3.3.1',
                'device_platform': 'android',
                'personalized_recommend_status': '1',
                'device_type': 'RMX1931',
                'device_brand': 'realme',
                'os_version': '9',
                'channel': 'default',
                'raw_channel': 'default',
                'oaid': '',
                'msa_oaid': '',
                'uuid': 'randomUUID_914e7a9b-deac-4f80-9247-db56669187df',
                'device_id': '24250683a3bdb3f118dff25ba4b1cba1a',
                'ab_id': '',
                'support_h265': '1'
            },
            body: "device=24250683a3bdb3f118dff25ba4b1cba1a&install_first_open=false&first_install_time=1723214205125&last_update_time=1723214205125&report_link_url="
        });
        html = JSON.parse(html);
        try {
            rule.headers['authorization'] = html.data.token;
        } catch (e) {
            rule.headers['authorization'] = html.data.data.token;
        }
        log('authorization:', rule.headers['authorization']);
    },
    推荐: async () => {
        return [];
    },
    一级: async function (tid, pg, filter, extend) {
        let {input} = this;
        let d = [];
        let html = await request(input, {headers: rule.headers});
        let data = JSON.parse(html).data.list;
        data.forEach(it => {
            let id = 'https://app.whjzjx.cn/v2/theater_parent/detail?theater_parent_id=' + it.theater.id;
            d.push({
                url: id,
                title: it.theater.title,
                img: it.theater.cover_url,
                desc: it.theater.theme,
            });
        });
        return setResult(d);
    },
    二级: async function (ids) {
        let {input} = this;
        let urls = [];
        let html = await request(input, {headers: rule.headers});
        let data = JSON.parse(html).data;
        let vod = {
            vod_id: input,
            vod_name: data.theaters.son_title || data.cover_url ? '星芽短剧' : '', 
            vod_pic: data.cover_url,
        };
        // Setup name fallback
        if (data.theaters && data.theaters.length > 0) {
            vod.vod_name = data.theaters[0].son_title || '星芽短剧';
        }
        let playFroms = [];
        let playUrls = [];
        data.theaters.forEach(it => {
            urls.push(it.num + '$' + encodeURIComponent(it.son_video_url));
        });
        playFroms.push('不知道倾情打造');
        vod.vod_play_from = playFroms.join('$$$');
        playUrls.push(urls.join('#'));
        vod.vod_play_url = playUrls.join('$$$');
        return vod;
    },
    搜索: async function (wd, quick, pg) {
        let {input, KEY} = this;
        let d = [];
        let html = await post(input, {headers: rule.headers, body: {"text": KEY}});
        let list = JSON.parse(html).data.theater.search_data;
        list.forEach(it => {
            let id = 'https://app.whjzjx.cn/v2/theater_parent/detail?theater_parent_id=' + it.id;
            d.push({
                url: id,
                title: it.title,
                desc: it.total,
                img: it.cover_url,
                content: it.introduction,
            });
        });
        return setResult(d);
    },
    lazy: async function (flag, id, flags) {
        let {input} = this;
        return {parse: 0, url: input, js: ''};
    },
};

// ===================== DRPY Global Emulators =====================
function log(...args) {
    console.log("[星芽短剧]", ...args);
}

async function request(url, options = {}) {
    const headers = options.headers || {};
    const method = (options.method || 'get').toLowerCase();
    let body = options.body;

    const config = {
        method,
        url,
        headers,
        transformResponse: [(data) => data]
    };
    if (body) {
        if (typeof body === 'object') {
            config.data = body;
        } else {
            // Form URL encoded data
            config.data = body;
        }
    }
    const r = await req(config);
    return r.data;
}

async function post(url, options = {}) {
    options.method = 'post';
    return await request(url, options);
}

function setResult(arr) {
    return {
        list: arr.map(it => ({
            vod_id: it.url,
            vod_name: it.title,
            vod_pic: it.img || it.pic,
            vod_remarks: it.desc || it.remarks,
            vod_content: it.content
        }))
    };
}

// Ensure auth token initialization runs
async function ensureInit() {
    if (!rule.headers['authorization']) {
        await rule.预处理();
    }
}

// ===================== CatPawOpen Standard Interface Mapping =====================
const classes = [
    { type_id: '1', type_name: '剧场' },
    { type_id: '2', type_name: '热播剧' },
    { type_id: '8', type_name: '会员专享' },
    { type_id: '7', type_name: '星选好剧' },
    { type_id: '3', type_name: '新剧' },
    { type_id: '5', type_name: '阳光剧场' }
];

const filterValues = [
    { n: "全部", v: "class2_ids=0" },
    { n: "都市", v: "class2_ids=4" },
    { n: "古装", v: "class2_ids=5" },
    { n: "现代言情", v: "class2_ids=15" },
    { n: "战神", v: "class2_ids=24" },
    { n: "逆袭", v: "class2_ids=7" },
    { n: "穿越", v: "class2_ids=17" },
    { n: "历史", v: "class2_ids=40" },
    { n: "赘婿", v: "class2_ids=26" },
    { n: "神医", v: "class2_ids=25" },
    { n: "重生", v: "class2_ids=6" },
    { n: "甜宠", v: "class2_ids=33" },
    { n: "古代言情", v: "class2_ids=37" },
    { n: "玄幻", v: "class2_ids=35" },
    { n: "萌宝", v: "class2_ids=9" },
    { n: "脑洞", v: "class2_ids=32" },
    { n: "亲情", v: "class2_ids=41" },
    { n: "虐恋", v: "class2_ids=8" }
];

const filters = {};
classes.forEach(c => {
    filters[c.type_id] = [
        {
            key: 'type',
            name: '类型',
            value: filterValues
        }
    ];
});

async function init() {
    await ensureInit();
    return {};
}

async function home() {
    return {
        class: classes,
        filters: filters
    };
}

async function category(reqIn) {
    await ensureInit();
    const body = reqIn?.body || {};
    const tid = body.id || '1';
    const pg = body.page || 1;
    const extend = body.filters || {};

    let filterVal = extend.type || 'class2_ids=0';

    let targetUrl = rule.filter_url
        .replace('fyclass', tid)
        .replace('fypage', pg)
        .replace(/\{\{fl\.type\s+or\s+["']class2_ids=0["']\}\}/g, filterVal);

    const inputUrl = rule.host + targetUrl;

    const context = {
        input: inputUrl
    };

    const res = await rule.一级.call(context, tid, pg, null, extend);
    return {
        page: parseInt(pg),
        pagecount: 999,
        limit: 24,
        total: 9999,
        list: res.list
    };
}

async function detail(reqIn) {
    await ensureInit();
    const body = reqIn?.body || {};
    const id = Array.isArray(body.id) ? body.id[0] : body.id;

    const context = {
        input: id
    };

    const vod = await rule.二级.call(context, id);
    return {
        list: [vod]
    };
}

async function search(reqIn) {
    await ensureInit();
    const body = reqIn?.body || {};
    const wd = body.wd;
    const pg = body.page || 1;

    const inputUrl = rule.host + rule.searchUrl;
    const context = {
        input: inputUrl,
        KEY: wd
    };

    const res = await rule.搜索.call(context, wd, false, pg);
    return res;
}

async function play(reqIn) {
    await ensureInit();
    const body = reqIn?.body || {};
    const id = body.id;
    const decodedUrl = decodeURIComponent(id);

    const context = {
        input: decodedUrl
    };

    const res = await rule.lazy.call(context, null, decodedUrl, null);
    return {
        parse: res.parse || 0,
        url: res.url,
        header: res.header || {}
    };
}

export default function createSpider(name, config) {
    return {
        meta: {
            key: 'xy_duanju',
            name: name || '星芽短剧',
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
