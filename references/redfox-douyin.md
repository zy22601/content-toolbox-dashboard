# 红狐·抖音爆款接入（Content Toolbox 热榜源）

把 RedFox(红狐hub) 的「抖音每日热门作品榜」接成本地热榜一个平台源。**真实 `redfox_api_key` 只存 `~/workspace/content-toolbox/config.secret.json`（mode 600），绝不放 index.html、不提交 git。**

## 1. 后端 server.py（stdlib）

```python
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
```

- 加到 `api_hot()` 的平台列表：`[("toutiao",...), ("baidu",...), ("bilibili",...), ("github",...), ("redfox", hot_redfox_douyin)]`
- 加入趋势：`api_trend()` 的 `platform_order` 也要加 `"redfox"`（否则不进趋势）。
- **鉴权**：请求头 `REDFOX_API_KEY`（或 `X-API-KEY`），值为 `config.secret.json` 的 `redfox_api_key`。
- **返回**：`{code:2000, data:[{content, accountName, category, likeCount, collectCount, commentCount, ...}]}`。`content`=作品正文（当 title），`likeCount`/`collectCount` 当热度。
- **网络坑**：本机网络对 HTTPS 做 MITM（自签名证书），`urlopen` 必须带 `context=_SSL`（见 SKILL.md「launchd 干净环境 SSL」坑），否则 `CERTIFICATE_VERIFY_FAILED`。

## 2. 前端 index.html

- `HL_NAMES` 加 `redfox:'红狐·抖音爆款'`。
- **AI 周报**：`aiwGrab()` 里对 redfox **跳过 AIRE 过滤**（抖音爆款基本非 AI，硬筛全空）——
  `if(k!=='redfox' && !AIRE.test(it.title||'')) return;`；
  `aiwRender()` 的 groups 加 `['redfox','🔥 爆款·抖音（红狐）']`，cnn 组过滤改成 `!(github||hackernews||redfox)`，redfox 组按热度排序并 `slice(0,12)`；`aiwExport` 加 `sec('🔥 爆款·抖音（红狐）', ...)`；`AIW_SRC` 加 `redfox:'抖音爆款'`。
- **违禁词扫描**：违禁词检测加按钮「🔥 抖音爆款扫描」→ `bwRedfoxScan()` 拉 `/api/hot` 的 `redfox` 源，逐条扫 `bwWords(strict)`，标出含引流/违规词的爆款钩子；词库补了 `橱窗/小黄车/直播间/扣1/关注+/站外/telegram/whatsapp/软广/诱导关注`。

## 3. 配置与范围

- `config.secret.json`（mode 600）：`{"deepseek_api_key": "...", "redfox_api_key": "ak_...", "redfox_base": "https://redfox.hk", ...}`。
- **仅 localhost**：红狐源靠本机 key，公开页（Cloudflare Pages）无此源（`/api/hot` 公开页走 Worker，无 redfox）。

## 4. 坑/实测

- **小红书「七日爆款」**：`GET /story/api/cozeSkill/getXhsCozeSkillDataSeven?category=<分类>`，认证 2000 但**当前返回空**（`data:[]`，实测"综合全部/职业发展"均空）——可能要传 `rankDate` 或需在红狐控制台激活对应 coze skill。**别接以免空转扣费**；要用先实测有数据。
- 抖音热门作品榜 `POST /story/api/dy/search/likesRank`（body `{}`）**实测 50→20 条**（content/分类/@作者/点赞数齐全，如"好久不见～"@邓家佳 307万赞）。
- 单价 ¥0.06/次（星级按累计调用量阶梯）。