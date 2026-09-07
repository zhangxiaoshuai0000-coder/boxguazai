// 歪比巴卜 JS 站源

import req from '../../util/req.js';
import CryptoJS from 'crypto-js';

// ===== 常量(对应 Python L27-39) =====
const HOST = 'https://wbbb1.com';
// 调试日志开关: 排查问题时设 true, 生产环境设 false
const DEBUG = true;
function log(...args) { if (DEBUG) console.log('[wbb]', ...args); }
function logErr(...args) { if (DEBUG) console.error('[wbb]', ...args); }
const PHOST = 'xn--qvr2v.850088.xyz';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';
const CATES = [['1', '电影'], ['2', '剧集'], ['3', '动漫'], ['4', '综艺']];
const SEGS = 12;
const IDX = { area: 1, class: 3, lang: 4, letter: 5, page: 8, year: 11 };
// 这些图床带 Referer 会 403, 需走代理剥离 Referer(项目图片代理后续接入)
const REF_BLOCK = ['iqiyipic.com', 'hdslb.com', 'bwcgee.cn', 'imgurl.ggvip.click', 'meilinvps.com'];

// ===== HTTP 会话层(对应 Python L41-109: init/_throttle/fetch/post) =====
// req.js 是裸 axios 实例, 不自动管 cookie/限流, 这里自己封装
let lastReq = 0;
const GAP = 0.6;  // 限流间隔(秒)
const cookies = new Map();
let filtersCache = {};  // 分类筛选缓存(对应 self.filters_cache)

function extractCookies(setCookie) {
  if (!setCookie) return;
  const list = Array.isArray(setCookie) ? setCookie : [setCookie];
  for (const item of list) {
    const m = String(item || '').match(/^([^=]+)=([^;]*)/);
    if (m) cookies.set(m[1].trim(), m[2].trim());
  }
}

function cookieHeader() {
  return [...cookies.entries()].map(([k, v]) => `${k}=${v}`).join('; ');
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

// 限流: 对应 _throttle(), 保证两次请求间隔 >= GAP 秒
async function throttle() {
  const d = Date.now() - lastReq;
  const gapMs = GAP * 1000;
  if (d < gapMs) await sleep(gapMs - d);
  lastReq = Date.now();
}

// GET 请求(对应 Python fetch(url, ref, tries=5, need=None))
// 成功: code==200 && (need 为空 || text 含 need || text 长度 > 20000)
// 429/403 退避 1.2*(i+1)s, 其他失败 0.4s, 失败返回最后 text
async function fetch(url, ref, tries = 5, need) {
  // 浏览器 sec-* headers: 模拟真实 Chrome, 绕过 CF 对 vplay 页的 WAF
  const headers = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': ref || (HOST + '/'),
    'Cookie': cookieHeader(),
    'sec-ch-ua': '"Chromium";v="120", "Not?A_Brand";v="24", "Google Chrome";v="120"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'same-origin',
    'Upgrade-Insecure-Requests': '1',
  };
  let last = '';
  for (let i = 0; i < tries; i++) {
    await throttle();
    let code = 0;
    try {
      const res = await req.get(url, {
        headers,
        timeout: 25000,
        validateStatus: () => true,
        maxRedirects: 5,
        responseType: 'text',
      });
      extractCookies(res.headers['set-cookie']);
      code = res.status;
      last = typeof res.data === 'string' ? res.data : String(res.data || '');
      if (code === 200 && (need === undefined || need === null || last.includes(need) || last.length > 20000)) {
        return last;
      }
      // 滑块验证页直接返回, 不重试(避免加剧限流, 让 solve_slider 处理)
      if (code === 403 && last.includes('滑动验证')) {
        log('fetch: 检测到滑块验证页, 直接返回(不重试)');
        return last;
      }
      logErr('fetch: 重试', i + 1, '/', tries, 'url=', url.slice(0, 80), 'code=', code, 'len=', last.length, '含need=', need ? last.includes(need) : 'N/A');
      // 403/429 时打印响应前 500 字符, 诊断 CF 拦截类型
      if (code === 403 || code === 429) logErr('fetch: 响应内容=', last.slice(0, 500));
    } catch (e) {
      logErr('fetch: 异常', i + 1, '/', tries, 'url=', url.slice(0, 80), e.message);
    }
    // 429/403 退避加长: 2s * (i+1), 避免短时间大量请求加剧限流
    const backoff = (code === 403 || code === 429) ? 2000 * (i + 1) : 400;
    if (i < tries - 1) await sleep(backoff);
  }
  logErr('fetch: 全部', tries, '次重试失败, 返回最后一次, url=', url.slice(0, 80), 'len=', last.length);
  return last;
}

// POST 请求
// 单次不重试, 失败返回 ""
async function post(url, data, ref) {
  const headers = {
    'User-Agent': UA,
    'Referer': ref || (HOST + '/'),
    'X-Requested-With': 'XMLHttpRequest',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Cookie': cookieHeader(),
    'Content-Type': 'application/x-www-form-urlencoded',
  };
  try {
    const isObj = data && typeof data === 'object' && !Buffer.isBuffer(data);
    const body = isObj ? new URLSearchParams(data).toString() : (data || '');
    const res = await req.post(url, body, {
      headers,
      timeout: 25000,
      validateStatus: () => true,
      maxRedirects: 0,
      responseType: 'text',
    });
    extractCookies(res.headers['set-cookie']);
    const r = typeof res.data === 'string' ? res.data : String(res.data || '');
    if (res.status !== 200 || !r) logErr('post: 状态异常 code=', res.status, 'url=', url.slice(0, 80), '返回长度=', r.length);
    return r;
  } catch (e) {
    logErr('post: 异常 url=', url.slice(0, 80), e.message);
    return '';
  }
}

// ===== 加密链路=====

function md5hex(s) {
  return CryptoJS.MD5(s).toString();
}


function calc(x) {
  return (md5hex(x) + ' P').slice(-22);
}


function rc4(key, data) {
  const s = Array.from({ length: 256 }, (_, i) => i);
  let j = 0;
  const kl = key.length;
  for (let i = 0; i < 256; i++) {
    j = (j + s[i] + key.charCodeAt(i % kl)) % 256;
    [s[i], s[j]] = [s[j], s[i]];
  }
  const out = Buffer.alloc(data.length);
  let ii = 0;
  let jj = 0;
  for (let k = 0; k < data.length; k++) {
    ii = (ii + 1) % 256;
    jj = (jj + s[ii]) % 256;
    [s[ii], s[jj]] = [s[jj], s[ii]];
    out[k] = data[k] ^ s[(s[ii] + s[jj]) % 256];
  }
  return out;
}

function b64d(s) {
  s = String(s || '').replace(/-/g, '+').replace(/_/g, '/');
  const pad = (4 - (s.length % 4)) % 4;
  return Buffer.from(s + '='.repeat(pad), 'base64');
}



function enplay(seed, x) {
  const filtered = String(x).replace(/[^\x00-\xff]/g, '');
  const data = Buffer.from(filtered, 'latin1');
  const enc = rc4(calc(seed), data);
  return Buffer.from(enc).toString('base64');
}


// rc4(calc(seed), b64d(x)).decode("latin-1")
function deplay(seed, x) {
  const data = b64d(x);
  const dec = rc4(calc(seed), data);
  return Buffer.from(dec).toString('latin1');
}



function aes_dec(b64, key, iv) {
  try {
    const s = String(b64 || '').replace(/-/g, '+').replace(/_/g, '/');
    const padded = s + '='.repeat((4 - (s.length % 4)) % 4);
    const k = CryptoJS.enc.Utf8.parse(String(key).slice(0, 16));
    const v = CryptoJS.enc.Utf8.parse(String(iv).slice(0, 16));
    const decrypted = CryptoJS.AES.decrypt(padded, k, {
      iv: v,
      mode: CryptoJS.mode.CBC,
      padding: CryptoJS.pad.Pkcs7,
    });
    return decrypted.toString(CryptoJS.enc.Utf8);
  } catch (e) {
    return '';
  }
}


function stringtoHex(acSTR) {
  var val = '';
  for (var i = 0; i <= acSTR.length - 1; i++) {
    var str = acSTR.charAt(i);
    var code = str.charCodeAt();
    val += parseInt(code) + 1;
  }
  return val;
}

// solve_slider: 纯 HTTP 模拟滑块验证 (不模拟拖动, 直接提交固定参数)
// 服务端只校验 key/value/type 三个参数, 不校验拖动轨迹
// 返回 true 表示验证通过, 验证后的 cookie 已存入 cookie jar
async function solve_slider(sliderHtml, refUrl) {
  log('solve_slider: 开始滑块验证');
  // 1. 从 HTML 提取 JS 路径
  const jsMatch = sliderHtml.match(/src="(\/huadong_[^"]+\.js[^"]*)"/);
  if (!jsMatch) { logErr('solve_slider: 未找到滑块 JS 路径'); return false; }
  const jsPath = jsMatch[1];
  log('solve_slider: JS 路径', jsPath);

  // 2. 请求 JS, 提取 key/value/type 和验证 API 路径
  const jsCode = await fetch(HOST + jsPath, refUrl, 2);
  if (!jsCode || jsCode.length < 100) { logErr('solve_slider: JS 请求失败, 长度=', jsCode.length); return false; }

  const keyMatch = jsCode.match(/key\s*=\s*"([^"]+)"/);
  const valueMatch = jsCode.match(/value\s*=\s*"([^"]+)"/);
  const typeMatch = jsCode.match(/type=([a-f0-9]+)/);
  // 验证 API 路径: /a20be899_xxx_yanzheng_huadong.php
  const apiPathMatch = jsCode.match(/c\.get\("([^"]*yanzheng_huadong\.php)/);
  if (!keyMatch || !valueMatch || !typeMatch || !apiPathMatch) {
    logErr('solve_slider: 提取 key/value/type/apiPath 失败');
    return false;
  }
  const key = keyMatch[1];
  const value = valueMatch[1];
  const type = typeMatch[1];
  const apiPath = apiPathMatch[1];
  log('solve_slider: key=', key, 'value=', value, 'apiPath=', apiPath);

  // 3. 计算验证 value: md5(stringtoHex(value))
  const finalValue = CryptoJS.MD5(stringtoHex(value)).toString();
  log('solve_slider: finalValue=', finalValue);

  // 4. GET 验证 API (fetch 会自动 extractCookies 存入 cookie jar)
  const verifyUrl = HOST + apiPath + '?type=' + type + '&key=' + key + '&value=' + finalValue;
  log('solve_slider: 验证 URL=', verifyUrl);
  const verifyRes = await fetch(verifyUrl, refUrl, 2);
  log('solve_slider: 验证响应长度=', verifyRes.length, '前 50 字符=', verifyRes.slice(0, 50));
  return true;
}


async function resolve(purl) {
  const u = String(purl || '').replace(/^http:\/\//, 'https://');
  if (!u) { logErr('resolve: 空地址'); return ['', '']; }
  const t = Math.floor(Date.now() / 1000);
  const pbase = 'https://' + PHOST + '/player/';
  log('resolve: 请求', pbase + 'api.php', 'url=', u);
  const body = await post(pbase + 'api.php', {
    url: u,
    key: enplay(u, md5hex(u + 'stray')),
    vkey: enplay(u, String(t) + md5hex(calc(u) + 'stray')),
    ckey: enplay(u, md5hex(PHOST + 'stray')),
  }, pbase + '?url=' + u);
  log('resolve: POST 返回长度', body.length, '前200字符:', body.slice(0, 200));
  let j;
  try { j = JSON.parse(body); } catch (e) { logErr('resolve: JSON 解析失败', e.message); return ['', '']; }
  if (String(j.code) !== '200' || !j.url) { logErr('resolve: code=', j.code, 'url为空=', !j.url); return ['', '']; }
  log('resolve: code=200, aes_key=', j.aes_key?.slice(0, 30), 'aes_iv=', j.aes_iv?.slice(0, 30), 'url=', j.url?.slice(0, 60));
  let k, iv;
  try {
    k = deplay(u, j.aes_key);
    iv = deplay(u, j.aes_iv);
  } catch (e) { logErr('resolve: deplay 失败', e.message); return ['', '']; }
  log('resolve: 解出 key=', k.slice(0, 20), 'iv=', iv.slice(0, 20));
  const real = aes_dec(j.url, k, iv);
  log('resolve: AES 解密结果长度', real.length, '前80字符:', real.slice(0, 80));
  return [real, String(j.type || '')];
}


function fix_url(u) {
  u = String(u || '').trim();
  if (!u) return '';
  if (u.startsWith('//')) return 'https:' + u;
  if (u.startsWith('/')) return HOST + u;
  return u;
}


function clean(t) {
  return String(t || '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
}


function pic(raw, title) {
  const u = String(raw || '').trim();
  if (!u || u === '/' || u === '#' || u === 'about:blank' || u.includes('load.gif') || u.includes('errorpic')) {
    return '';
  }
  return fix_url(u);
}


function show_url(tid, ext, pg) {
  const seg = new Array(SEGS).fill('');
  seg[0] = String(tid);
  for (const [k, i] of Object.entries(IDX)) {
    if (k === 'page') continue;
    const v = String((ext || {})[k] || '').trim();
    if (v) seg[i] = encodeURIComponent(v);
  }
  seg[IDX.page] = String(pg);
  return HOST + '/show/' + seg.join('-') + '.html';
}


function parse_cards(html) {
  const out = [];
  const seen = new Set();
  // 主匹配: 带 title 属性的详情链接
  const re1 = /<a[^>]+href="\/detail\/(\d+)\.html"[^>]*?title="([^"]*)"[\s\S]{0,900}?<\/a>/g;
  let m;
  while ((m = re1.exec(html)) !== null) {
    const vid = m[1];
    const title = m[2];
    if (seen.has(vid)) continue;
    seen.add(vid);
    out.push({ vod_id: vid, vod_name: title, vod_pic: '', vod_remarks: '' });
  }
  // 兜底: 榜单/热搜页无 title 属性, 标题在 infotitle 里
  const re2 = /<a[^>]+href="\/detail\/(\d+)\.html"[^>]*>([\s\S]{0,500}?)<\/a>/g;
  while ((m = re2.exec(html)) !== null) {
    const vid = m[1];
    const blk = m[2];
    if (seen.has(vid)) continue;
    const t = blk.match(/infotitle"?\s*>([^<]{1,60})</) || blk.match(/item-title"?\s*>([^<]{1,60})</);
    const nm = t ? clean(t[1]) : clean(blk).slice(0, 40);
    if (!nm) continue;
    seen.add(vid);
    const note = blk.match(/<p>([^<]{0,20})<\/p>/);
    out.push({ vod_id: vid, vod_name: nm, vod_pic: '', vod_remarks: note ? clean(note[1]) : '' });
  }
  // 补全图片和备注
  const pics = {};
  const notes = {};
  const re3 = /href="\/detail\/(\d+)\.html"[\s\S]{0,900}?<\/a>/g;
  while ((m = re3.exec(html)) !== null) {
    const blk = m[0];
    const vid = m[1];
    const p = blk.match(/data-original="([^"]+)"/) || blk.match(/<img[^>]+src="(https?[^"]+)"/);
    if (p && !(vid in pics)) pics[vid] = p[1];
    const n = blk.match(/class="module-item-note">([^<]{0,24})</) || blk.match(/class="module-item-text">([^<]{0,24})</);
    if (n && !(vid in notes)) notes[vid] = clean(n[1]);
  }
  for (const v of out) {
    if (!v.vod_pic) v.vod_pic = pics[v.vod_id] || '';
    v.vod_pic = pic(v.vod_pic, v.vod_name);
    if (!v.vod_remarks) v.vod_remarks = notes[v.vod_id] || '';
  }
  return out.filter(v => v.vod_name);
}


async function get_filters(tid) {
  if (tid in filtersCache) return filtersCache[tid];
  const html = await fetch(show_url(tid, {}, 1), HOST + '/type/' + tid + '.html');
  const groups = { area: [], class: [], lang: [], letter: [], year: [] };
  const re = /href="\/show\/([^"]+)\.html"[^>]*>([^<]{1,12})<\/a>/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    const raw = m[1];
    const name = clean(m[2]);
    if (!name || name === '全部') continue;
    const parts = decodeURIComponent(raw).split('-');
    if (parts.length < SEGS) continue;
    for (const [key, idx] of [['area', 1], ['class', 3], ['lang', 4], ['letter', 5], ['year', 11]]) {
      const v = idx < parts.length ? parts[idx] : '';
      if (v && v === name) {
        const otherKeys = [1, 3, 4, 5, 11].filter(j => j !== idx);
        const isAlone = otherKeys.every(j => j >= parts.length || parts[j] === '');
        if (isAlone && !groups[key].some(x => x.v === v)) {
          groups[key].push({ n: name, v: v });
        }
      }
    }
  }
  const label = { area: '地区', class: '剧情', lang: '语言', letter: '字母', year: '年份' };
  const flt = [];
  for (const key of ['class', 'area', 'year', 'lang', 'letter']) {
    if (!groups[key].length) continue;
    flt.push({ key, name: label[key], value: [{ n: '全部', v: '' }, ...groups[key]] });
  }
  filtersCache[tid] = flt;
  return flt;
}


function total_pages(html, pg) {
  const re = /\/show\/[^"]*?-{8}(\d+)-{3}\.html/g;
  const nums = [];
  let m;
  while ((m = re.exec(html)) !== null) nums.push(parseInt(m[1], 10));
  return nums.length ? Math.max(...nums) : pg + 1;
}


async function ocr_verify() {
  let Tesseract;
  try {
    const mod = await import('tesseract.js');
    Tesseract = mod.default || mod;
  } catch (e) {
    return false;  // 设备 bundle 无 tesseract.js, 走 fallback
  }
  let worker = null;
  try {
    worker = await Tesseract.createWorker('eng', 1, { logger: () => {} });
    await worker.setParameters({
      tessedit_char_whitelist: '0123456789',
      tessedit_lowercase: '1',
      tessedit_pageseg_mode: '7',
    });
  } catch (e) {
    return false;
  }
  for (let attempt = 0; attempt < 12; attempt++) {
    try {
      // 下载验证码图片
      const res = await req.get(HOST + '/index.php/verify/index.html', {
        headers: { 'User-Agent': UA, 'Referer': HOST + '/', 'Cookie': cookieHeader() },
        timeout: 20000,
        validateStatus: () => true,
        responseType: 'arraybuffer',
      });
      extractCookies(res.headers['set-cookie']);
      const buf = Buffer.from(res.data);
      // OCR 识别
      const { data } = await worker.recognize(buf);
      const code = String(data?.text || '').toLowerCase().replace(/[^0-9]/g, '').trim();
      if (code.length !== 4) {
        await sleep(1200);
        continue;
      }
      // 提交验证
      const r = await post(HOST + '/index.php/ajax/verify_check?type=search&verify=' + encodeURIComponent(code), '', HOST + '/');
      if (r.startsWith('{"code":1')) {
        if (worker) try { await worker.terminate(); } catch {}
        return true;
      }
    } catch (e) {
      // 异常静默
    }
    await sleep(1200);
  }
  if (worker) try { await worker.terminate(); } catch {}
  return false;
}

// ===== CatVod 接口 =====

async function home(reqIn) {
  const filter = reqIn?.body?.filter !== false;
  const cls = CATES.map(([t, n]) => ({ type_id: t, type_name: n }));
  const filters = {};
  if (filter) {
    for (const [t] of CATES) {
      const f = await get_filters(t);
      if (f.length) filters[t] = f;
    }
  }
  const html = await fetch(HOST + '/', undefined, 5, 'module-item');
  return { class: cls, filters, list: parse_cards(html) };
}


async function homeVod() {
  return { list: parse_cards(await fetch(HOST + '/', undefined, 5, 'module-item')) };
}


async function category(reqIn) {
  const body = reqIn?.body || {};
  const tid = String(body.id || '');
  const pg = Math.max(parseInt(body.page) || 1, 1);
  const extend = body.extend || body.filters || body.ext || body.filter || {};
  const url = show_url(tid, extend, pg);
  const html = await fetch(url, HOST + '/type/' + tid + '.html', 5, 'module-item');
  const vl = parse_cards(html);
  const pc = vl.length ? total_pages(html, pg) : pg;
  return { list: vl, page: pg, pagecount: pc, limit: 72, total: pc * 72 };
}

async function search(reqIn) {
  const body = reqIn?.body || {};
  const key = String(body.wd || '').trim();
  const pg = parseInt(body.page) || 1;
  log('search: wd=', key, 'page=', pg);
  const k = key;
  // 路径式搜索 URL(MACCMS 标准)
  const u = HOST + '/search/' + k + '-------------.html';
  let html = await fetch(u, HOST + '/', 2);
  log('search: 主URL返回长度', html.length, '含module-item=', html.includes('module-item'));
  // 滑块验证检测(站点风控升级, OCR 处理不了, 直接走 fallback)
  if (html.includes('drag_text') || html.includes('拖动滑块')) {
    logErr('search: 检测到滑块验证, 走 fallback');
    return search_fallback(key, pg);
  }
  if (html.includes('系统安全验证') || html.includes('需要输入验证码') || html.includes('访问此数据需要输入验证码')) {
    log('search: 检测到数字验证码, 尝试 OCR');
    if (await ocr_verify()) {
      log('search: OCR 通过, 重新请求');
      await sleep(4500);
      html = await fetch(u, HOST + '/', 2);
    } else {
      logErr('search: OCR 失败, 直接走 fallback, 不再重试搜索 URL');
      return search_fallback(key, pg);
    }
  }
  if (html.includes('请不要频繁操作')) {
    log('search: 频繁操作限流, 等待重试');
    await sleep(4500);
    html = await fetch(u, HOST + '/', 2);
  }
  let vl = parse_cards(html);
  log('search: parse_cards 结果', vl.length, '条');
  if (vl.length) {
    return { list: vl, page: pg, pagecount: vl.length >= 20 ? pg + 1 : pg, limit: vl.length, total: vl.length };
  }
  // 旧 URL 形式兜底
  for (const u2 of [
    HOST + '/search/-------------.html?wd=' + encodeURIComponent(k) + '&page=' + pg,
    HOST + '/index.php/vod/search/page/' + pg + '/wd/' + encodeURIComponent(k) + '.html',
  ]) {
    log('search: 尝试兜底URL', u2);
    html = await fetch(u2, HOST + '/', 2);
    if (html.includes('drag_text') || html.includes('拖动滑块')) {
      logErr('search: 兜底URL也遇到滑块, 走 fallback');
      return search_fallback(key, pg);
    }
    if (html.includes('验证码')) {
      if (await ocr_verify()) {
        await sleep(4500);
        html = await fetch(u2, HOST + '/', 2);
      } else {
        logErr('search: 兜底URL OCR 失败, 直接走 fallback');
        return search_fallback(key, pg);
      }
    }
    vl = parse_cards(html);
    log('search: 兜底URL parse_cards', vl.length, '条');
    if (vl.length) {
      return { list: vl, page: pg, pagecount: vl.length >= 20 ? pg + 1 : pg, limit: vl.length, total: vl.length };
    }
  }
  log('search: 所有 URL 均无结果, 走 fallback');
  return search_fallback(key, pg);
}


async function search_fallback(key, pg) {
  const k = String(key || '').trim();
  if (!k) return { list: [], page: pg, pagecount: pg, limit: 0, total: 0 };
  const hits = [];
  const seen = new Set();
  for (const [tid] of CATES) {
    const r = await category({ body: { id: tid, page: pg, filter: true, filters: {} } });
    for (const v of r.list) {
      if (v.vod_name.includes(k) && !seen.has(v.vod_id)) {
        seen.add(v.vod_id);
        hits.push(v);
      }
    }
    if (hits.length >= 20) break;
  }
  if (!hits.length) {
    const html = await fetch(HOST + '/index.php/label/hot.html', HOST + '/', 3, 'detail/');
    for (const v of parse_cards(html)) {
      if (v.vod_name.includes(k) && !seen.has(v.vod_id)) {
        seen.add(v.vod_id);
        hits.push(v);
      }
    }
  }
  return { list: hits, page: pg, pagecount: hits.length ? pg + 1 : pg, limit: hits.length, total: hits.length };
}


async function detail(reqIn) {
  const body = reqIn?.body || {};
  const ids = Array.isArray(body.id) ? body.id : [body.id];
  const vid = String(ids[0] || '');
  log('detail: id=', vid);
  const html = await fetch(HOST + '/detail/' + vid + '.html', HOST + '/', 5, 'module-info');
  log('detail: HTML长度=', html.length, '含module-info=', html.includes('module-info'));
  if (!html) { logErr('detail: HTML 为空'); return { list: [] }; }
  // 标题
  let name = '';
  const m1 = html.match(/<h1[^>]*>([^<]+)<\/h1>/);
  if (m1) name = clean(m1[1]);
  // 封面
  let pic_url = '';
  for (const pat of [
    /module-info-poster[\s\S]{0,300}?data-original="([^"]+)"/,
    /module-item-pic[\s\S]{0,240}?data-original="([^"]+)"/,
    /property="og:image"\s+content="([^"]+)"/,
    /data-original="([^"]+)"/,
  ]) {
    const mm = html.match(pat);
    if (mm && mm[1].trim() && mm[1].trim() !== '' && mm[1].trim() !== '/') {
      pic_url = mm[1];
      break;
    }
  }
  pic_url = pic(pic_url, name);
  // 年份/地区/类型
  const headStart = html.indexOf('module-info-heading');
  const head = headStart >= 0 ? html.slice(headStart, headStart + 1400) : '';
  let year = '';
  let area = '';
  const types = [];
  const reA = /<a[^>]+href="\/show\/([^"]+)\.html"[^>]*>([^<]{1,12})<\/a>/g;
  let ma;
  while ((ma = reA.exec(head)) !== null) {
    const raw = decodeURIComponent(ma[1]);
    const txt = clean(ma[2]);
    const parts = raw.split('-');
    if (parts.length > 11 && parts[11] === txt) year = txt;
    else if (parts.length > 1 && parts[1] === txt) area = txt;
    else if (parts.length > 3 && parts[3] === txt) types.push(txt);
  }
  // 导演/主演/备注
  let actor = '';
  let director = '';
  let remarks = '';
  const reI = /module-info-item[^>]*>([\s\S]{0,420}?)<\/div>\s*<\/div>/g;
  let mi;
  while ((mi = reI.exec(html)) !== null) {
    const t = clean(mi[1]);
    if (t.startsWith('导演')) director = t.replace('导演：', '').trim().replace(/^\/+|\/+$/g, '');
    else if (t.startsWith('主演') || t.startsWith('演员')) actor = t.replace(/^(主演|演员)：/, '').trim().replace(/^\/+|\/+$/g, '');
    if (t.includes('备注：')) remarks = t.split('备注：').pop().trim();
  }
  // 简介
  let desc = '';
  const md = html.match(/module-info-introduction[^>]*>([\s\S]{0,3000}?)<\/div>/);
  if (md) desc = clean(md[1]).slice(0, 900);
  // 线路和集数
  const names = html.match(/data-dropdown-value="([^"]+)"/g)?.map(x => x.match(/"([^"]+)"/)[1]) || [];
  const panels = [];
  const reP = /<div class="module-list[^"]*"[^>]*>([\s\S]{0,60000}?)(?=<div class="module-list|<script)/g;
  let mp;
  while ((mp = reP.exec(html)) !== null) panels.push(mp[1]);
  const froms = [];
  const urls = [];
  for (let i = 0; i < panels.length; i++) {
    const blk = panels[i];
    let eps = [];
    const reE = /href="(\/vplay\/[^"]+)"[^>]*>\s*<span>([^<]{0,40})<\/span>/g;
    let me;
    while ((me = reE.exec(blk)) !== null) eps.push([me[1], me[2]]);
    if (!eps.length) {
      const reE2 = /href="(\/vplay\/[^"]+)"[^>]*title="([^"]*)"/g;
      while ((me = reE2.exec(blk)) !== null) eps.push([me[1], me[2]]);
    }
    if (!eps.length) continue;
    froms.push(i < names.length ? names[i] : '线路' + (i + 1));
    const seenEps = new Set();
    const items = [];
    for (const [href, label] of eps) {
      if (seenEps.has(href)) continue;
      seenEps.add(href);
      const nm = clean(label) || ('第' + (items.length + 1) + '集');
      items.push(nm + '$' + href);
    }
    urls.push(items.join('#'));
  }
  const vod = {
    vod_id: vid, vod_name: name, vod_pic: pic_url,
    type_name: types.join('/'), vod_year: year, vod_area: area,
    vod_remarks: remarks, vod_actor: actor, vod_director: director,
    vod_content: desc,
    vod_play_from: froms.join('$$$') || '线路1',
    vod_play_url: urls.join('$$$'),
  };
  return { list: [vod] };
}


function isVideoFormat(url) {
  const u = String(url || '').toLowerCase();
  return ['.m3u8', '.mp4', '.flv', '.mkv', '.ts'].some(x => u.includes(x));
}


async function play(reqIn) {
  const body = reqIn?.body || {};
  const pid = String(body.id || '');
  log('play: id=', pid);
  const hdr = { 'User-Agent': UA, 'Referer': HOST + '/' };
  // 如果 pid 本身是视频地址, 直接返回
  if (isVideoFormat(pid) && pid.startsWith('http')) {
    log('play: pid 本身是视频地址, 直接返回');
    return { parse: 0, playUrl: '', url: pid, header: JSON.stringify(hdr) };
  }
  const page = pid.startsWith('http') ? pid : fix_url(pid);
  const ref = page.replace(/\/vplay\/(\d+)-.*/, '/detail/$1.html');
  log('play: vplay页=', page, 'ref=', ref);
  // 提取 player_aaaa(2 轮重试, 减少 vplay 页 403/429 雪崩)
  let pj = null;
  for (let rnd = 0; rnd < 2; rnd++) {
    const html = await fetch(page, ref, 3, 'player_aaaa');
    log('play: 第', rnd + 1, '轮, HTML长度=', html.length, '含player_aaaa=', html.includes('player_aaaa'));

    // 滑块验证检测: 403 + 滑块页 → 纯 HTTP 通过验证后重新请求
    if (html.includes('滑动验证') || html.includes('slideBox')) {
      log('play: 检测到滑块验证, 尝试纯 HTTP 通过');
      if (await solve_slider(html, page)) {
        log('play: 滑块验证通过, 等待 1 秒后重新请求 vplay 页');
        await sleep(1000);
        continue; // 重新循环请求 vplay 页(带验证后的 cookie)
      } else {
        logErr('play: 滑块验证失败');
      }
    }

    const m = html.match(/var player_aaaa\s*=\s*(\{.*?\})\s*<\/script>/s);
    if (m) {
      try { pj = JSON.parse(m[1]); log('play: player_aaaa 提取成功, encrypt=', pj.encrypt, 'url=', String(pj.url).slice(0, 60)); break; } catch (e) { pj = null; logErr('play: player_aaaa JSON 解析失败', e.message); }
    }
    await fetch(ref, HOST + '/', 2);
    await sleep(1000 + rnd * 1000);
  }
  if (!pj) {
    logErr('play: 2 轮重试后仍未提取到 player_aaaa, 返回原页让浏览器解析');
    return { parse: 1, playUrl: '', url: page, header: JSON.stringify(hdr) };
  }
  let raw = pj.url || '';
  const enc = String(pj.encrypt || '0');
  if (enc === '1') {
    raw = decodeURIComponent(raw);
  } else if (enc === '2') {
    try { raw = decodeURIComponent(b64d(raw).toString('utf8')); } catch (e) { logErr('play: b64d 失败', e.message); }
  }
  log('play: enc=', enc, '解出 raw=', raw.slice(0, 80));
  if (raw.startsWith('http') && isVideoFormat(raw)) {
    log('play: raw 是直接视频地址, 返回');
    return { parse: 0, playUrl: '', url: raw, header: JSON.stringify(hdr) };
  }
  // 调 resolve 解密真实地址
  log('play: 调 resolve 解密...');
  const [real] = await resolve(raw);
  if (real && real.startsWith('http')) {
    log('play: resolve 成功, 真实地址=', real.slice(0, 80));
    return { parse: 0, playUrl: '', url: real, header: JSON.stringify({ 'User-Agent': UA, 'Referer': 'https://' + PHOST + '/' }) };
  }
  logErr('play: resolve 未拿到有效地址, 返回原页让浏览器解析');
  return { parse: 1, playUrl: '', url: page, header: JSON.stringify(hdr) };
}


async function init() {
  log('init: 预热请求', HOST);
  filtersCache = {};
  lastReq = 0;
  const html = await fetch(HOST + '/');
  log('init: 预热返回长度=', html.length, '含module-item=', html.includes('module-item'));
  return {};
}

// ===== 工厂导出(对应 JS 站源规范) =====
export default function createSpider() {
  return {
    meta: {
      key: 'wbb',
      name: '歪比巴卜',
      type: 3,
    },
    api: async (fastify) => {
      fastify.post('/init', init);
      fastify.post('/home', home);
      fastify.post('/homeVod', homeVod);
      fastify.post('/category', category);
      fastify.post('/detail', detail);
      fastify.post('/play', play);
      fastify.post('/search', search);
    },
    check: async () => {
      try {
        const html = await fetch(HOST + '/', undefined, 1);
        return html.length > 1000;
      } catch (e) {
        return false;
      }
    },
  };
}
