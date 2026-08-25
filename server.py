#!/usr/bin/env python3
"""content-toolbox local server.

Serves the dashboard over http://localhost (localhost = secure context, so
crypto.subtle signing + clipboard copy work for the R2 image host and
theme-copy features). Also exposes:

  /api/hot          aggregates a few hot lists server-side (residential-IP
                    sources that a datacenter IP can't reach). On a fresh
                    fetch it also writes a *daily snapshot* used by /api/trend.
  /api/trend        computes 增长 / 稳定 / 冷却 / 新上榜 labels from the last
                    N days of daily snapshots (default 7, up to 14).
  /api/ai_topics    POST - feeds current hot evidence to a local DeepSeek
                    endpoint and returns content-选题 ideas for a niche.

Zero dependencies - plain stdlib. The DeepSeek key lives in config.secret.json
(mode 600) next to this file - NEVER in index.html (it ships to the public
page). Run:

    python3 server.py            # http://localhost:8080
    PORT=9000 python3 server.py  # custom port
"""
import json
import os
import re
import shutil
import ssl
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

os.chdir(os.path.dirname(os.path.abspath(__file__)))

EXTRA = {
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".css": "text/css",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".wasm": "application/wasm",
}

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

# This box's network MITMs HTTPS (self-signed CA in the chain), so Python's
# default ssl verify fails under launchd's clean env. These are public data
# endpoints (hot lists / GitHub API) — safe to skip cert verification.
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

SECRET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.secret.json")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "trend")


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10, context=_SSL) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _get_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=10, context=_SSL) as r:
        return r.read().decode("utf-8", "ignore")


def _read_secret():
    try:
        with open(SECRET_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def hot_toutiao():
    d = _get_json("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc")
    return [{"title": x.get("Title", ""), "hot": x.get("HotValue", ""),
             "url": "https://www.toutiao.com/search/?keyword=" + urllib.parse.quote(x.get("Title", ""))}
            for x in d.get("data", [])]


def hot_bili():
    d = _get_json("https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all")
    return [{"title": x.get("title", ""), "hot": x.get("stat", {}).get("view", ""),
             "url": "https://www.bilibili.com/video/" + x.get("bvid", "")}
            for x in d.get("data", {}).get("list", [])[:20]]


def hot_baidu():
    html = _get_text("https://top.baidu.com/board?tab=realtime")
    m = re.search(r"<!--s-data:([\s\S]*?)-->", html)
    d = json.loads(m.group(1)) if m else {}
    content = (d.get("data", {}).get("cards") or [{}])[0].get("content", [])
    return [{"title": x.get("word", ""), "hot": x.get("hotScore"),
             "url": x.get("url", "https://top.baidu.com/board?tab=realtime")} for x in content]


def hot_github():
    since = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    d = _get_json("https://api.github.com/search/repositories?q=created:>%s&sort=stars&order=desc&per_page=15" % since)
    return [{"title": x.get("full_name", ""), "hot": x.get("stargazers_count", ""),
             "url": x.get("html_url", ""), "desc": (x.get("description") or "")[:120]}
            for x in d.get("items", [])]


def hot_redfox_douyin():
    """红狐 · 抖音每日热门作品榜 (需 REDFOX_API_KEY, 见 config.secret.json)."""
    sec = _read_secret()
    key = sec.get("redfox_api_key", "")
    if not key:
        return []
    body = json.dumps({}).encode("utf-8")
    req = urllib.request.Request("https://redfox.hk/story/api/dy/search/likesRank", data=body,
                                 headers={"REDFOX_API_KEY": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception:
        return []
    if d.get("code") != 2000:
        return []
    out = []
    for x in d.get("data", []):
        content = (x.get("content") or "").strip()
        if not content:
            continue
        heat = x.get("likeCount") or x.get("collectCount") or x.get("commentCount") or ""
        url = x.get("shareUrl") or x.get("itemUrl") or x.get("url") or ""
        if not url:
            url = "https://www.douyin.com/search/" + urllib.parse.quote(content[:20])
        desc = (x.get("category") or "")
        if x.get("accountName"):
            desc += " · @" + x.get("accountName", "")
        out.append({"title": content[:120], "hot": heat, "url": url, "desc": desc[:120]})
    return out[:20]


def api_hot():
    out = {}
    for name, fn in [("toutiao", hot_toutiao), ("bilibili", hot_bili), ("baidu", hot_baidu),
                     ("github", hot_github), ("redfox", hot_redfox_douyin)]:
        try:
            items = fn()
            out[name] = {"items": items}
            _snapshot(name, items)
        except Exception as e:  # noqa: BLE001 - report per-source error, don't kill the endpoint
            out[name] = {"items": [], "error": str(e)}
    return {"updated": int(time.time() * 1000), "platforms": out}


# ------------------------------ daily snapshots / trend ------------------------------
def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _snapshot(platform, items):
    """Write today's rank list for a platform (once per day, first fetch wins
    so position changes within a day don't jitter the trend)."""
    if not items:
        return
    try:
        d = os.path.join(DATA_DIR, platform)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, _today() + ".json")
        if os.path.exists(path):
            return
        rows = [{"title": it.get("title", ""), "rank": i + 1,
                 "heat": str(it.get("hot", "")), "url": it.get("url", ""),
                 "desc": it.get("desc", "")} for i, it in enumerate(items)]
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"date": _today(), "platform": platform, "rows": rows}, f, ensure_ascii=False)
    except Exception:
        pass


def _load_days(platform, days):
    """Return [{date, rows:[...]}] for the last `days` snapshots (oldest->newest)."""
    d = os.path.join(DATA_DIR, platform)
    out = []
    if not os.path.isdir(d):
        return out
    files = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    for f in files[-days:]:
        try:
            with open(os.path.join(d, f), encoding="utf-8") as fh:
                out.append(json.load(fh))
        except Exception:
            continue
    return out


def _classify(hist, days):
    """hist = rows from newest->oldest for a single title across the window."""
    if not hist:
        return "stable", 0
    now, prev = hist[0]["rank"], (hist[1]["rank"] if len(hist) > 1 else None)
    total = len([h for h in hist if h.get("rank")])
    sep = max(1, days // 2)
    older = [h for h in hist if h.get("older")]  # flagged below
    # newest day present => part of today's board
    is_new = total <= 2 and hist[0].get("rank") is not None and total <= 2
    if prev is None:
        # only in today's / latest snapshot -> brand new or one-day
        return ("new" if total <= 2 else "stable"), 0
    delta = prev - now  # positive => rank number dropped => moved UP
    if is_new:
        return "new", 0
    if delta >= 1:
        return "rising", delta
    if delta <= -1:
        return "cooling", delta
    return "stable", delta


def api_trend(days=7):
    days = max(2, min(int(days), 14))
    platform_order = ["redfox", "toutiao", "baidu", "bilibili", "github"]
    result = {"days": days, "platforms": {}}
    for plat in platform_order:
        hist = _load_days(plat, days)
        if not hist:
            continue
        # index by title, per date
        by_title = {}
        for day in hist:
            date = day.get("date", "")
            for r in day.get("rows", []):
                t = r.get("title", "").strip()
                if not t:
                    continue
                by_title.setdefault(t, []).append({**r, "date": date})
        items = []
        for t, recs in by_title.items():
            # order newest first
            recs.sort(key=lambda r: r.get("date", ""), reverse=True)
            latest = recs[0]
            present = len(recs)
            older_days = len({r["date"] for r in recs if r.get("date", "") < hist[-1].get("date", "9999")})
            trend, delta = _classify(recs, days)
            # reframe: new only if it just appeared (present days still small AND in recent half)
            if present <= 2 and max(r.get("rank") or 99 for r in recs) <= 15:
                trend = "new"
            elif present >= days - 1 and delta == 0:
                trend = "stable"
            items.append({
                "title": t, "rank": latest.get("rank"), "heat": latest.get("heat", ""),
                "url": latest.get("url", ""), "desc": latest.get("desc", ""),
                "days": present, "delta": delta, "trend": trend,
            })
        items.sort(key=lambda x: (0 if x["trend"] == "rising" else
                                  1 if x["trend"] == "new" else
                                  2 if x["trend"] == "stable" else 3,
                                  - (x["rank"] or 99)))
        result["platforms"][plat] = items
    return result


# ------------------------------ AI 选题 (DeepSeek) ------------------------------
def ai_topics(niche, platform, count=6):
    sec = _read_secret()
    key = sec.get("deepseek_api_key", "")
    base = sec.get("deepseek_base_url", "https://api.deepseek.com/v1")
    model = sec.get("deepseek_model", "deepseek-chat")
    if not key:
        return {"ok": False, "error": "未配置 DeepSeek key（config.secret.json 为空）"}
    hot = api_hot()
    platforms = hot.get("platforms", {})
    evidence_lines = []
    for name in ("toutiao", "baidu", "github"):
        items = platforms.get(name, {}).get("items", [])[:10]
        label = {"toutiao": "头条", "baidu": "百度", "github": "GitHub"}.get(name, name)
        for it in items:
            evidence_lines.append(f"- [{label}] {it.get('title','')} (热度 {it.get('hot','')})")
    evidence = "\n".join(evidence_lines) or "（今日热榜暂无可获取数据）"
    prompt = (
        "你是资深内容选题策划。账号定位：%s；目标平台：%s。\n"
        "下面是一份今日全网热榜证据，请从中挖掘%s适合写的内容选题。\n"
        "要求：标题抓眼球但不标题党、角度可实操、贴合账号定位；给出每个选题的切入点(angle)、\n"
        "为什么值不值得写(why)、与账号的匹配度(fit=高/中/低)。\n"
        "严格只输出 JSON，不要其它文字，格式："
        '{"topics":[{"title":"...","angle":"...","why":"...","fit":"高"}]}，共%d条。\n\n'
        "今日热榜证据：\n%s" % (niche, platform, niche, count, evidence)
    )
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0.7, "max_tokens": 2200}).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45, context=_SSL) as r:
            data = json.loads(r.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        content = re.sub(r"^```(json)?\s*", "", content.strip())
        content = re.sub(r"\s*```$", "", content.strip())
        topics = json.loads(content)
        if isinstance(topics, dict) and "topics" in topics:
            topics = topics["topics"]
        return {"ok": True, "topics": topics}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


# ------------------------------ local knowledge base (markdown files) ------------------------------
KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kb")


def _kb_dirs():
    os.makedirs(KB_DIR, exist_ok=True)


def _kb_parse_md(path):
    txt = open(path, encoding="utf-8").read()
    meta, body = {}, txt
    if txt.startswith("---"):
        parts = txt.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip("\"'")
            body = parts[2].strip()
    return meta, body


def _kb_item(mid, meta, body):
    return {"id": mid, "title": meta.get("title", ""), "type": meta.get("type", ""),
            "tags": [t for t in re.split(r"[,\s，]+", meta.get("tags", "")) if t],
            "source": meta.get("source", ""), "date": meta.get("date", ""),
            "updated": meta.get("updated", ""),
            "excerpt": re.sub(r"[\n\r\t]+", " ", body)[:120]}


def _kb_list():
    _kb_dirs()
    out = []
    for fn in os.listdir(KB_DIR):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(KB_DIR, fn)
        meta, body = _kb_parse_md(path)
        out.append(_kb_item(meta.get("id") or fn[:-3], meta, body))
    out.sort(key=lambda x: x.get("updated", ""), reverse=True)
    return out


def _kb_get(mid):
    if not mid or re.search(r"[^\w\-]", mid):
        return None
    path = os.path.join(KB_DIR, mid + ".md")
    if not os.path.isfile(path):
        return None
    meta, body = _kb_parse_md(path)
    return {"id": meta.get("id") or mid, "meta": meta, "content": body}


def _kb_save(payload):
    _kb_dirs()
    mid = (payload.get("id") or "").strip()
    if not mid:
        mid = str(int(time.time() * 1000)) + "-" + os.urandom(3).hex()
    title = (payload.get("title") or "").strip() or "未命名"
    typ = (payload.get("type") or "素材").strip()
    tags = payload.get("tags") or []
    if isinstance(tags, list):
        tags = "，".join(str(t) for t in tags)
    source = (payload.get("source") or "").strip()
    date = payload.get("date") or datetime.now().strftime("%Y-%m-%d")
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = payload.get("content") or ""
    fm = ("---\n"
          f'title: "{title}"\n'
          f'type: "{typ}"\n'
          f"tags: [{tags}]\n"
          f'source: "{source}"\n'
          f"date: {date}\n"
          f"updated: {updated}\n"
          f"id: {mid}\n"
          "---\n\n")
    open(os.path.join(KB_DIR, mid + ".md"), "w", encoding="utf-8").write(fm + body)
    return {"ok": True, "id": mid}


def _kb_delete(mid):
    if not mid or re.search(r"[^\w\-]", mid):
        return False
    path = os.path.join(KB_DIR, mid + ".md")
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def _kb_search(q):
    q = (q or "").lower().strip()
    _kb_dirs()
    out = []
    for fn in os.listdir(KB_DIR):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(KB_DIR, fn)
        meta, body = _kb_parse_md(path)
        hay = (meta.get("title", "") + " " + meta.get("tags", "") + " " + body).lower()
        if not q or q in hay:
            out.append(_kb_item(meta.get("id") or fn[:-3], meta, body))
    out.sort(key=lambda x: x.get("updated", ""), reverse=True)
    return out


def _kb_export(target):
    target = (target or "").strip()
    if not target:
        return {"ok": False, "error": "未指定导出目录"}
    os.makedirs(target, exist_ok=True)
    n = 0
    for it in _kb_list():
        fp = os.path.join(KB_DIR, it["id"] + ".md")
        if not os.path.isfile(fp):
            continue
        safe = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", it["title"] or "untitled")
        shutil.copy(fp, os.path.join(target, safe + ".md"))
        n += 1
    return {"ok": True, "count": n, "target": target}


# simple server-side cache so repeated loads are instant (hot lists change slowly)
_hot_cache = {"ts": 0, "body": None}
HOT_TTL = 300  # seconds


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, **EXTRA}

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/hot":
            hot = api_hot()
            if _hot_cache["body"] and time.time() - _hot_cache["ts"] < HOT_TTL:
                hot = json.loads(_hot_cache["body"])
            else:
                _hot_cache["ts"] = time.time()
                _hot_cache["body"] = json.dumps(hot, ensure_ascii=False).encode("utf-8")
            return self._json(hot)
        if path == "/api/trend":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            days = int(q.get("days", ["7"])[0])
            return self._json(api_trend(days))
        if path == "/api/kb":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            mid = q.get("id", [""])[0] if q else ""
            if mid:
                g = _kb_get(mid)
                return self._json(g or {"ok": False, "error": "not found"}, 404 if not g else 200)
            return self._json({"items": _kb_list()})
        if path == "/api/kb/search":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("q", [""])[0]
            return self._json({"items": _kb_search(q)})
        super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/ai_topics":
            try:
                ln = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(ln).decode("utf-8")) if ln else {}
                niche = (req.get("niche") or "职场/效率工具").strip()[:120]
                platform = (req.get("platform") or "公众号").strip()[:30]
                count = int(req.get("count") or 6)
            except Exception:
                return self._json({"ok": False, "error": "bad request"}, 400)
            return self._json(ai_topics(niche, platform, count))
        if path == "/api/kb":
            try:
                ln = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(ln).decode("utf-8")) if ln else {}
            except Exception:
                return self._json({"ok": False, "error": "bad request"}, 400)
            return self._json(_kb_save(req))
        if path == "/api/kb/export":
            try:
                ln = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(ln).decode("utf-8")) if ln else {}
            except Exception:
                return self._json({"ok": False, "error": "bad request"}, 400)
            return self._json(_kb_export(req.get("target", "")))
        super().do_POST()

    def do_DELETE(self):
        path = self.path.split("?")[0]
        if path == "/api/kb":
            mid = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("id", [""])[0]
            return self._json({"ok": _kb_delete(mid)})
        self.send_response(405)
        self.end_headers()

    def log_message(self, fmt, *args):  # quiet by default
        print("%s %s" % (self.address_string(), fmt % args))


def main():
    port = int(os.environ.get("PORT", 8080))
    # daily background snapshot so /api/trend accumulates 7/14-day history
    threading.Thread(target=snapshot_loop, daemon=True).start()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"* content-toolbox  running →  http://localhost:{port}/")
    print(f"* 热榜每日快照 → {DATA_DIR}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


def snapshot_loop():
    try:
        api_hot()  # initial snapshot so trend has today immediately
    except Exception:
        pass
    while True:
        now = datetime.now()
        nxt = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        time.sleep(max(1, (nxt - now).total_seconds()))
        try:
            api_hot()
        except Exception:
            pass


if __name__ == "__main__":
    main()
