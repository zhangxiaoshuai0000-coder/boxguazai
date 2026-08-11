#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
══════════════════════════════════════════════════════════════════
《遮天法 2.0》— 如意影视 (ryys.cc) 专用爬虫源
境界：洞天境 · 现代 SPA 异步站点
══════════════════════════════════════════════════════════════════

【站点特征】
  - 纯前端 SPA，首页为骨架屏，数据靠 /backend/api/public/*.php 异步加载
  - 片源（source）与分类（type）分离，需先调 site 接口获取元数据
  - 列表接口支持 source + type + page 组合筛选
  - 搜索走独立接口

【核心设计】
  - homeContent 先返回片源列表（作为 "vod" 数据展示），再返回分类
  - 符合 TVBox 标准六接口
══════════════════════════════════════════════════════════════════
"""

import sys
import re
import json
import time
import base64
import random
from urllib import parse
from typing import Dict, List, Optional, Any

import requests


# ══════════════════════════════════════════════════════════════
# 站点配置
# ══════════════════════════════════════════════════════════════
SITE_URL = "https://ryys.cc"
API_BASE = f"{SITE_URL}/backend/api/public"


# ══════════════════════════════════════════════════════════════
# 日志与统计（简化版遮天法）
# ══════════════════════════════════════════════════════════════
class ZheTianLogger:
    REALM_EMOJI = {
        "轮海": "~", "道宫": "#", "四极": "=",
        "化龙": "@", "仙台": "^", "红尘仙": "*",
        "路由": ">", "统计": "$", "洞天": "⊙"
    }

    def info(self, realm: str, msg: str):
        emoji = self.REALM_EMOJI.get(realm, ".")
        print(f"[{emoji}{realm}] {msg}", flush=True)

    def debug(self, realm: str, msg: str):
        pass

    def warning(self, realm: str, msg: str):
        emoji = self.REALM_EMOJI.get(realm, "!")
        print(f"[{emoji}{realm}] WARN: {msg}", flush=True)

    def error(self, realm: str, msg: str):
        emoji = self.REALM_EMOJI.get(realm, "x")
        print(f"[{emoji}{realm}] ERR: {msg}", flush=True)


log = ZheTianLogger()


# ══════════════════════════════════════════════════════════════
# 源天书 · 基础请求层
# ══════════════════════════════════════════════════════════════
class YuanTianShu:
    realm_name = "源天书"

    def __init__(self):
        self.siteUrl = SITE_URL
        self._session = requests.Session()
        self._ua_pool = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.2 Safari/605.1.15",
        ]

    def _random_ua(self) -> str:
        return random.choice(self._ua_pool)

    def _headers(self, extra: Dict = None) -> Dict:
        h = {
            "User-Agent": self._random_ua(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": f"{self.siteUrl}/",
            "Origin": self.siteUrl,
        }
        if extra:
            h.update(extra)
        return h

    def _fetch_json(self, url: str, params: Dict = None, headers: Dict = None) -> Optional[Dict]:
        """GET 请求并解析 JSON"""
        t0 = time.time()
        try:
            resp = self._session.get(
                url, params=params, headers=self._headers(headers), timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            elapsed = (time.time() - t0) * 1000
            log.debug("洞天", f"GET {url.split('/')[-1]} ({resp.status_code}, {elapsed:.0f}ms)")
            if isinstance(data, dict) and data.get("success") and "data" in data:
                return data["data"]
            return data
        except Exception as e:
            log.error("洞天", f"请求失败 {url}: {e}")
            return None

    def _post_json(self, url: str, json_data: Dict = None, headers: Dict = None) -> Optional[Dict]:
        """POST 请求并解析 JSON"""
        try:
            resp = self._session.post(
                url, json=json_data, headers=self._headers(headers), timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data.get("success") and "data" in data:
                return data["data"]
            return data
        except Exception as e:
            log.error("洞天", f"POST 失败 {url}: {e}")
            return None

    @staticmethod
    def fix_url(url: str, host: str = SITE_URL) -> str:
        if not url:
            return ""
        if url.startswith("http"):
            return url
        if url.startswith("//"):
            return f"https:{url}"
        return f"{host.rstrip('/')}{url}" if url.startswith("/") else f"{host.rstrip('/')}/{url}"


# ══════════════════════════════════════════════════════════════
# 洞天境 · 如意影视专用
# ══════════════════════════════════════════════════════════════
class DongTian_RuYi(YuanTianShu):
    """
    洞天境·如意 —— 专为 ryys.cc 现代 SPA 架构设计
    
    技术要点：
      1. 首页无数据，所有元数据来自 /backend/api/public/site.php
      2. 列表来自 /backend/api/public/videos.php?source=&type=&page=
      3. 搜索来自 /backend/api/public/search.php?q=&page=
      4. 详情页直接构造 /detail.html?id={vod_id}&source={source_id}
    """

    realm_name = "洞天·如意"
    realm_level = 7
    defense_level = 4

    def __init__(self):
        super().__init__()
        self._site_meta: Optional[Dict] = None
        self._sources: List[Dict] = []
        self._categories: List[Dict] = []
        self._page_size = 20

    # ───── 缓存元数据 ─────
    def _ensure_meta(self):
        """拉取 site 元数据（片源 + 分类 + 站点配置）"""
        if self._site_meta is not None:
            return

        data = self._fetch_json(f"{API_BASE}/site.php")
        if not data:
            log.warning("洞天", "site.php 返回空，使用硬编码兜底")
            self._site_meta = {}
            self._sources = []
            self._categories = []
            return

        self._site_meta = data
        self._sources = data.get("sources", [])
        # 分类需要等第一次 videos 请求带 include_categories=1 时才完整
        # 这里先尝试取 site 里可能有的默认分类
        self._categories = []
        self._page_size = max(1, int(data.get("homepage_page_size", 20)))

        log.info("洞天", f"元数据加载完成: {len(self._sources)} 个片源, 分页 {self._page_size}")

    # ───── TVBox 六接口 ─────

    def homeContent(self, filter: bool = False) -> Dict:
        """
        【核心】先显示片源，再显示分类
        
        如意影视的"片源"（sources）本质上是不同的采集站，
        这里把片源作为首页列表返回（让用户先看到内容），
        同时返回分类供切换。
        """
        self._ensure_meta()

        # 1. 先返回片源列表（作为视频卡片展示，点击即进入该片源的分类页）
        #    为了有真实视频，我们取默认片源的第一页数据作为"片源推荐"
        videos = []
        if self._sources:
            default_source = self._sources[0].get("id", "")
            # 尝试拉取默认片源首页数据
            list_data = self._fetch_json(
                f"{API_BASE}/videos.php",
                params={"source": default_source, "page": 1, "type": "", "include_categories": 1}
            )
            if list_data:
                videos = self._parse_videos(list_data.get("videos", []), default_source)
                # 顺便缓存分类
                cats = list_data.get("categories", [])
                if cats:
                    self._categories = cats

        # 2. 构造分类（如果 videos 接口没返回分类，用硬编码兜底）
        classes = self._build_classes()

        # 3. 构造片源作为"筛选标签"（TVBox 的 filters 机制）
        #    由于 TVBox 的 class 是分类，我们把片源也塞进 filters 里
        filters = {}
        if self._sources:
            source_filter = {
                "name": "片源",
                "key": "source",
                "value": [{"n": s.get("name", s.get("id", "")), "v": s.get("id", "")} for s in self._sources]
            }
            # 给每个分类都加上片源筛选
            for c in classes:
                filters[c["type_id"]] = [source_filter]

        result = {
            "list": videos,       # ← 先显示片源推荐内容
            "class": classes,     # ← 再显示分类
        }
        if filters:
            result["filters"] = filters

        log.info("洞天", f"homeContent 返回 {len(videos)} 条片源推荐, {len(classes)} 个分类")
        return result

    def categoryContent(self, tid: str, pg: str, filter: bool, extend: Dict) -> Dict:
        """
        分类列表：tid 是分类 type_id，extend 里可能有 source（片源ID）
        """
        self._ensure_meta()
        source_id = extend.get("source", "") if extend else ""
        
        # 如果没有指定片源，取第一个
        if not source_id and self._sources:
            source_id = self._sources[0].get("id", "")

        params = {
            "source": source_id,
            "type": tid,
            "page": pg,
            "include_categories": 0,
        }

        data = self._fetch_json(f"{API_BASE}/videos.php", params=params)
        videos = self._parse_videos(data.get("videos", []), source_id) if data else []

        # 分页信息（接口没返回总页数时，按有下一页处理）
        page = int(pg)
        # 如果返回数量不足 page_size，认为是最后一页
        pagecount = page + 1 if len(videos) >= self._page_size else page
        if not videos:
            pagecount = page

        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": self._page_size,
            "total": pagecount * self._page_size,
        }

    def detailContent(self, ids: List[str]) -> Dict:
        """
        详情页：ids[0] 格式为 "source_id|vod_id" 或纯 vod_id
        """
        raw_id = ids[0]
        if "|" in raw_id:
            source_id, vod_id = raw_id.split("|", 1)
        else:
            vod_id = raw_id
            source_id = self._sources[0].get("id", "") if self._sources else ""

        # 尝试从 videos 接口获取详情（很多 SPA 站列表即详情）
        # 或者构造播放页 URL
        play_url = f"{self.siteUrl}/detail.html?id={vod_id}&source={source_id}"
        
        # 尝试获取该视频详情（部分站点支持 /videos.php?id=）
        detail_data = self._fetch_json(
            f"{API_BASE}/videos.php",
            params={"source": source_id, "id": vod_id}
        )
        
        if detail_data and "videos" in detail_data:
            videos = detail_data["videos"]
            if videos and len(videos) > 0:
                v = videos[0]
                return {
                    "list": [self._format_detail(v, source_id)]
                }

        # 兜底：构造一个只有播放链接的详情
        return {
            "list": [{
                "vod_id": f"{source_id}|{vod_id}",
                "vod_name": "如意影视",
                "vod_pic": "",
                "vod_play_from": "如意源",
                "vod_play_url": f"正片${play_url}",
            }]
        }

    def playerContent(self, flag: str, id: str, vipFlags: str) -> Dict:
        """
        播放解析：id 可能是 detail.html 链接，需要进一步提取真实 m3u8
        """
        if id.startswith("http"):
            # 如果是 detail.html 页面，需要抓取真实播放地址
            if "/detail.html" in id:
                # 提取参数
                parsed = parse.urlparse(id)
                qs = parse.parse_qs(parsed.query)
                vod_id = qs.get("id", [""])[0]
                source_id = qs.get("source", [""])[0]
                
                # 尝试从 videos 接口拿播放地址
                data = self._fetch_json(
                    f"{API_BASE}/videos.php",
                    params={"source": source_id, "id": vod_id} if source_id else {"id": vod_id}
                )
                if data and data.get("videos"):
                    v = data["videos"][0]
                    m3u8 = v.get("url", v.get("play_url", v.get("video_url", "")))
                    if m3u8:
                        return {"parse": 0, "url": m3u8, "header": f"Referer={self.siteUrl}/"}

            # 直接是 m3u8/mp4
            if ".m3u8" in id or ".mp4" in id:
                return {"parse": 0, "url": id, "header": f"Referer={self.siteUrl}/"}

        return {"parse": 1, "url": id, "header": f"Referer={self.siteUrl}/"}

    def searchContent(self, key: str, quick: str, pg: str = "1") -> Dict:
        """
        搜索：/backend/api/public/search.php?q=&page=
        """
        params = {"q": key, "page": pg}
        data = self._fetch_json(f"{API_BASE}/search.php", params=params)
        videos = self._parse_videos(data.get("videos", [])) if data else []
        return {"list": videos, "page": int(pg)}

    def localProxy(self, param: Dict) -> List:
        return [404, "text/plain", "Not Supported"]

    # ───── 内部工具 ─────

    def _parse_videos(self, raw_list: List[Dict], source_id: str = "") -> List[Dict]:
        """统一解析视频列表"""
        result = []
        for v in raw_list:
            vid = v.get("id", v.get("vod_id", ""))
            sid = v.get("source_id", source_id)
            # ID 拼接 source_id|vod_id，确保 detail 能拆分
            vod_id = f"{sid}|{vid}" if sid else vid
            
            pic = v.get("pic", v.get("thumb", v.get("cover", v.get("image", ""))))
            name = v.get("name", v.get("title", v.get("vod_name", "未知"))
            remarks = v.get("remarks", v.get("note", v.get("status", "")))
            
            result.append({
                "vod_id": vod_id,
                "vod_name": name,
                "vod_pic": self.fix_url(pic) if pic else "",
                "vod_remarks": remarks,
            })
        return result

    def _format_detail(self, v: Dict, source_id: str) -> Dict:
        """格式化详情对象"""
        vid = v.get("id", v.get("vod_id", ""))
        vod_id = f"{source_id}|{vid}" if source_id else vid
        pic = v.get("pic", v.get("thumb", v.get("cover", "")))
        
        # 播放地址：优先 url，其次 episodes
        episodes = []
        if "episodes" in v and isinstance(v["episodes"], list):
            for ep in v["episodes"]:
                ep_name = ep.get("name", ep.get("title", "正片"))
                ep_url = ep.get("url", "")
                if ep_url:
                    episodes.append(f"{ep_name}${ep_url}")
        elif "url" in v and v["url"]:
            episodes.append(f"正片${v['url']}")
        
        return {
            "vod_id": vod_id,
            "vod_name": v.get("name", v.get("title", "未知")),
            "vod_pic": self.fix_url(pic) if pic else "",
            "vod_remarks": v.get("remarks", ""),
            "vod_content": v.get("content", v.get("desc", v.get("description", ""))),
            "vod_play_from": "如意源",
            "vod_play_url": "#".join(episodes) if episodes else "",
        }

    def _build_classes(self) -> List[Dict]:
        """构造分类列表"""
        if self._categories:
            return [{"type_name": c.get("name", c.get("title", "未知")), "type_id": str(c.get("id", c.get("type_id", "")))} 
                      for c in self._categories if c.get("id") or c.get("type_id")]
        
        # 兜底：如意影视常见分类
        return [
            {"type_name": "电影", "type_id": "1"},
            {"type_name": "电视剧", "type_id": "2"},
            {"type_name": "动漫", "type_id": "3"},
            {"type_name": "综艺", "type_id": "4"},
        ]


# ══════════════════════════════════════════════════════════════
# TVBox 标准入口
# ══════════════════════════════════════════════════════════════
class Spider(DongTian_RuYi):
    """TVBox / 影视仓 标准入口"""
    pass


# ══════════════════════════════════════════════════════════════
# 一键入口
# ══════════════════════════════════════════════════════════════
def create_spider_for(url: str = SITE_URL) -> Spider:
    sp = Spider()
    sp.siteUrl = url.rstrip("/")
    return sp


# ══════════════════════════════════════════════════════════════
# 自检 & 测试
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    sp = Spider()
    print("=" * 50)
    print("【homeContent】先片源，后分类")
    home = sp.homeContent()
    print(json.dumps(home, ensure_ascii=False, indent=2))
    
    if home.get("class"):
        tid = home["class"][0]["type_id"]
        print(f"\n【categoryContent】tid={tid}")
        cat = sp.categoryContent(tid=tid, pg="1", filter=False, extend={})
        print(json.dumps(cat, ensure_ascii=False, indent=2)[:1500])
    
    print("\n【searchContent】key=斗罗大陆")
    search = sp.searchContent(key="斗罗大陆", quick="1", pg="1")
    print(json.dumps(search, ensure_ascii=False, indent=2)[:1500])