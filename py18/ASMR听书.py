# -*- coding: utf-8 -*-
# ASMR MOON (asmrmoon.com) 免费音声站 Python Spider


import json
import re

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        pass

try:
    import requests
except ImportError:
    requests = None

HOST = "https://asmrmoon.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg")
VIDEO_EXTS = (".m3u8", ".mp4", ".ts")


class Spider(BaseSpider):
    def init(self, extend=""):
        self.host = (extend or HOST).strip().rstrip("/")
        self.session = requests.Session() if requests else None
        if self.session:
            self.session.headers = {
                "User-Agent": UA,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.init()

    def getName(self):
        return "ASMR MOON"

    def _post(self, api, body):
        if not self.session:
            return {}
        try:
            r = self.session.post(self.host + api, json=body, timeout=25)
            if r.status_code != 200:
                return {}
            return r.json()
        except Exception:
            return {}

    def _list(self, path, page=1, per_page=1000):
        d = self._post("/api/fs/list", {
            "path": path, "password": "",
            "page": page, "per_page": per_page,
            "refresh": False, "force_global_name_sort": False,
        })
        return (d.get("data") or {}).get("content") or []

    def _is_media(name):
        n = name.lower()
        return n.endswith(AUDIO_EXTS) or n.endswith(VIDEO_EXTS)

    def _collect_files(self, path, depth=0):
        out = []
        try:
            items = self._list(path)
        except Exception:
            return out
        for it in items:
            name = it.get("name") or ""
            full = (path.rstrip("/") + "/" + name).replace("//", "/")
            if it.get("is_dir"):
                if depth < 3:
                    out.extend(self._collect_files(full, depth + 1))
            elif self._is_media(name):
                out.append({"name": name, "path": full, "size": it.get("size", 0)})
        return out

    def homeContent(self, filter=False):
        items = self._list("/")
        classes = []
        for it in items:
            if not it.get("is_dir"):
                continue
            name = it.get("name") or ""
            if name in ("使用说明", ".git", "@eaDir"):
                continue
            classes.append({"type_id": "/" + name, "type_name": name})
        lst = []
        if classes:
            creators = self._list(classes[0]["type_id"])
            for c in creators:
                if c.get("is_dir"):
                    nm = c.get("name") or ""
                    lst.append({
                        "vod_id": classes[0]["type_id"] + "/" + nm,
                        "vod_name": nm,
                        "vod_pic": "",
                        "vod_remarks": "创作者",
                    })
        return {"class": classes, "list": lst}

    def homeVideoContent(self):
        h = self.homeContent()
        return {"list": h.get("list", [])}

    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        items = self._list(tid, page=int(pg), per_page=100)
        lst = []
        for it in items:
            if not it.get("is_dir"):
                continue
            nm = it.get("name") or ""
            lst.append({
                "vod_id": (tid.rstrip("/") + "/" + nm).replace("//", "/"),
                "vod_name": nm,
                "vod_pic": "",
                "vod_remarks": "创作者",
            })
        return {"list": lst, "page": int(pg), "pagecount": 9999}

    def searchContent(self, key, quick=False, pg="1"):
        d = self._post("/api/fs/search", {
            "parent": "/", "keywords": key, "scope": 0,
            "page": int(pg), "per_page": 50, "password": "",
        })
        content = (d.get("data") or {}).get("content") or []
        lst = []
        for it in content:
            name = it.get("name") or ""
            parent = it.get("parent") or ""
            if it.get("is_dir") or not self._is_media(name):
                continue
            full = (parent.rstrip("/") + "/" + name).replace("//", "/")
            lst.append({
                "vod_id": full,
                "vod_name": name,
                "vod_pic": "",
                "vod_remarks": parent,
            })
        return {"list": lst}

    def detailContent(self, ids):
        vid = str(ids[0] if isinstance(ids, list) else ids)
        if self._is_media(vid.split("/")[-1]):
            name = vid.split("/")[-1]
            vod = {
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": "",
                "vod_play_from": "ASMR",
                "vod_play_url": "1 %s$%s" % (name, vid),
            }
            return {"list": [vod]}
        files = self._collect_files(vid)
        if not files:
            return {"list": []}
        parts = []
        for i, f in enumerate(files, 1):
            title = re.sub(r"\.[^.]+$", "", f["name"]) or ("音轨%d" % i)
            parts.append("%d %s$%s" % (i, title, f["path"]))
        vod = {
            "vod_id": vid,
            "vod_name": vid.split("/")[-1],
            "vod_pic": "",
            "vod_play_from": "ASMR",
            "vod_play_url": "#".join(parts),
        }
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags=None):
        path = str(id)
        if not path.startswith("/"):
            return {"parse": 0, "playUrl": ""}
        d = self._post("/api/fs/get", {"path": path, "password": ""})
        raw = ((d.get("data") or {}).get("raw_url")) or ""
        if not raw:
            return {"parse": 0, "playUrl": ""}
        return {"parse": 0, "playUrl": raw, "header": {"User-Agent": UA}}
