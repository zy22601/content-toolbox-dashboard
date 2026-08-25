# 轻作 · 内容工作站（QingZuo）

把写内容高频用到的 **16 个工具**打包成本地 dashboard，一个浏览器标签全搞定。**全本地、零后端、离线可用**（R2 图床、热榜选题、AI 选题需联网）。

## 运行

```bash
cd ~/workspace/content-toolbox
python3 server.py            # → http://localhost:8080
PORT=9000 python3 server.py  # 自定义端口
```

> 用 `localhost` 打开（而不是双击 file://）。localhost 是浏览器「安全上下文」，R2 上传签名、公众号富文本复制、复制图片这些才正常可用。
> `server.py` 是 Python 标准库，零依赖。

## 16 个工具

| # | 工具 | 干什么 | 关键语法 |
|---|------|--------|---------|
| 1 | **R2 图床** | 图片直传 Cloudflare R2，返回直链 / Markdown / HTML | 拖拽/粘贴/选图 |
| 2 | **Markdown → PNG** | Markdown 渲染成高清长图 | 左右分栏实时预览 |
| 3 | **图文卡片** | 3:4 竖版文字卡片，批量多张，适配小红书 | `==高亮==` 行内高亮；独立一行 `---` 分页 |
| 4 | **去除 Emoji** | 一键清掉表情/符号，保留纯文本 | 粘贴→清洗→复制 |
| 5 | **公众号排版** | 写 Markdown 出公众号样式，复制富文本进公众号保持排版 | 主题/主色可调 |
| 6 | **封面生成** | 输入标题/副标题/角标/落款，套现成配色生成封面 | 16:9 · 3:4 · 1:1，导出高清 PNG |
| 7 | **字数统计** | 实时统计汉字/标点/英文单词/数字/行数/段落 + 估算阅读时长 | 输入即统计 |
| 8 | **二维码生成** | 链接/文本 → 二维码，导流公众号/社群/商品 | 容错/配色/尺寸可调 |
| 9 | **九宫格切图** | 一图切多格发多图平台，可裁正方形、打包 ZIP | 2×3 / 3×3 / 3×4 等 |
| 10 | **图片压缩/转换** | WebP/JPEG 压到平台上限，省 R2 流量 | 格式/质量/最大宽高 |
| 11 | **图片加水印** | 文字水印防盗图、品牌露出 | 单角标 / 平铺斜纹 |
| 12 | **热榜选题** | 聚合头条/百度/B站/**GitHub 趋势**/Hacker News 热榜，**🤖 AI 相关**一键筛 AI，勾选进选题清单导出 | 热榜需联网（本机不含 HN，公开页含）；选题清单本地存 |
| 13 | **一键分发** | 一份 Markdown → 各平台可粘贴文案（公众号/知乎/小红书/X） | 平台勾选 + 标签 + 链接，复制即贴 |
| 14 | **AI 周报** | 每周累计 AI 热点池（GitHub/HN/国内），☆想写标记，一键导出周报 Markdown | 跨天抓取去重，本地存 |
| 15 | **违禁词检测** | 公众号/小红书/知乎发前自查：广告法极限词、敏感违禁、医疗夸大、引流词、平台违规 | 命中标红 + 类别，一键复制「清洗版」（替换为 *） |
| 16 | **知识库** | 本地 Markdown 知识库：收选题/成稿/拆书/素材，全局搜索、按类型筛、导出 Obsidian | `data/kb/*.md`（frontmatter），仅 localhost |

## R2 图床：配置（Worker 模式，默认/推荐）

工作台 R2 图床现在**只用 Cloudflare Worker**（免 CORS、免本机密钥、链接走你的域名），已移除「浏览器直传」模式（避免产生公开 `r2.dev` 链接）。

1. 部署 Worker（`~/workspace/content-toolbox/worker/`）：`npx wrangler deploy`（首次自动建桶 `content-toolbox-images`）。
2. ⚠️ **必须设写保护密钥**（否则任何人可上传/删除你的桶、白嫖存储）：
   ```bash
   printf '%s' "$(openssl rand -hex 24)" | npx wrangler secret put API_KEY
   ```
3. 工作台 → R2 图床 → 填 **Worker 地址**（如 `https://cdn.toolscomb.com`）+ **API Key**（上一步生成的值），保存。
4. 图片直链形如 `<worker>/view/<key>`；写操作（上传/删除/列表）需 API Key，读（view）公开。

**安全**：Worker `/upload` `/list` `/delete` 需 `x-api-key`（无 key → 401）；`/view`（图床链接）与 `/hot`（热榜）保持公开。密钥只存 Cloudflare 云端 + 你浏览器 localStorage。若不想图走通用 `r2.dev`，在 Cloudflare 控制台 R2 桶 → Settings → **Public access** 关掉即可（此开关无 API，只能控制台手动）。

## 结构

```
content-toolbox/
├── index.html          # 工作台（16 工具，单文件）
├── server.py           # 本地服务器（stdlib，localhost:8080；含每日快照线程）
├── config.secret.json  # 本地 DeepSeek key（mode 600，勿提交/勿进 index.html）
├── data/trend/         # 每日热榜快照（/api/trend 据此算趋势）
├── data/kb/            # 知识库 markdown（/api/kb，Obsidian frontmatter）
├── vendor/
│   ├── markdown-it.umd.min.js   # Markdown → HTML
│   └── html2canvas.min.js       # HTML → PNG
└── README.md
```

## 本地 API & 趋势 / AI 选题（参考 insprira，2026-08）

server.py 除了托管静态页，还提供 3 个本地接口（**仅 localhost**，公开页不可用）：

| 接口 | 作用 |
|------|------|
| `/api/hot` | 聚合头条 / 百度 / B站 / GitHub 热榜；**每次刷新写入当日快照** |
| `/api/trend?days=7\|14` | 由每日快照算出每个词 **📈增长 / 🆕新上榜 / ➖稳定 / 📉冷却** 及在榜天数 |
| `/api/ai_topics` (POST) | 用**本地 DeepSeek**（config.secret.json）结合今日热榜证据 + 账号定位，生成 4–6 条选题 |
| `/api/kb` (GET/POST/DELETE) + `/api/kb/search` + `/api/kb/export` | 本地知识库：列表/读取/保存/删除/全文搜索/导出到 Obsidian（`data/kb/*.md`） |

- **红狐·抖音爆款（工具12·新增源）**：`/api/hot` 还会带一个 `redfox` 平台——POST `redfox.hk/story/api/dy/search/likesRank`（每日热门作品榜，¥0.06/次），**需 `config.secret.json` 里的 `redfox_api_key`**（HEADER 鉴权）。**仅 localhost**（key 在本机，公开页无此源）。抖音每日热门作品榜实测 20 条（content/分类/@作者/点赞数）。**小红书「七日爆款」coze 接口当前认证通过但返回空**（可能需激活 skill 或用 rankDate），暂未接入以免空转扣费。

- **趋势**：server.py 启动即快照一次，并每天 **09:00 自动再快照**（`snapshot_loop` 线程），连续几天就攒出 7/14 天趋势。热榜条目的趋势徽标 + 顶部「🔥 趋势」筛选栏由 `/api/trend` 驱动。
- **AI 选题**：在「设置 → AI 选题定位」填账号领域（存 localStorage），热榜下方点「🤖 AI 选题」生成；DeepSeek key 只存本机 `config.secret.json`（mode 600），**不进 index.html**（公开页拿不到）。公开页点 AI 选题会提示需 localhost。
- 公开页（tools.1616666.xyz）仍可正常用 **违禁词检测**、以及其它 13 个工具；趋势栏会自动隐藏、AI 选题提示需本机。

## 说明

- **Markdown→PNG / 图文卡片 / 公众号排版** 全部本地渲染，内容不上传。
- 图文卡片导出为 3:4（1242×1656，1.5x 缩放 = 1863×2484）；Markdown→PNG 按 2x 缩放导出。
- 其余 4 个工具是纯静态页，可整个 `index.html` + `vendor/` 直接托管到 Netlify/Cloudflare Pages。

## R2 托管方式二：Cloudflare Worker（推荐，免本机 / 免 CORS）

工作台 R2 页顶部有「托管方式」切换。选 **Cloudflare Worker** 后，密钥只存云端，浏览器直传不经本地签名，也无需在桶上配 CORS。源码在 `worker/`：

```
worker/
├── worker.js      # /upload · /view/<key> · /delete · /list
└── wrangler.toml  # name / main / R2 binding BUCKET
```

### 部署（命令行）

```bash
cd worker
npx wrangler login                    # 浏览器弹出，登录你的 Cloudflare 账号
npx wrangler deploy                    # 首次自动创建 R2 桶 content-toolbox-images
# 可选：给写入加保护（上传/删除需 x-api-key 头）
npx wrangler secret put API_KEY
```

部署完把打印的 `https://content-toolbox-r2.<subdomain>.workers.dev` 填进工作台 R2 页的 **Worker 地址**；若设了 `API_KEY`，把同一个值填进 **API Key**。之后拖图即直传，返回 `<worker>/view/<key>` 直链（`/view` 对所有人开放，可当公开图床）。

> 不想用命令行？也可以在 Cloudflare 控制台 → **Workers & Pages → 创建** → 粘贴 `worker.js`，在「设置 → 绑定」加 R2 桶绑定（变量名 `BUCKET`），再在「设置 → 变量和机密」加 `API_KEY`（可选）。

> ## 当前状态（2026-08）
>
> **R2 图床 2 种托管方式均可用**，工作台顶部可随时切换：
> - **Worker 模式**：`https://cdn.toolscomb.com`（已上线的 Worker + R2，免本机、免 CORS、密钥只存云端）。上传/取回均实测 200。
> - **浏览器直传模式**：S3 SigV4 直传 `content-toolbox-images` 桶 + 公开地址 `https://pub-3863b6653cf04cd1af042ceaf2991aa8.r2.dev`。localhost / pages.dev 双端实测可用（已配 CORS）。
>
> ⚠️ 本账号的 **`*.workers.dev` 域名对任何 worker 都返回 1101**（hello world 也一样）——是 workers.dev hostname 的问题，**不是 runtime 坏**。解决办法：把 worker 挂到**自定义域名**（`cdn.toolscomb.com`）即可绕过，正常执行。首次挂自定义域名踩了两个坑：(1) 路由名被拼成 `cdn.toolscomb.com.toolscomb.com`（要删掉、用 Custom Domain 精确填 `cdn.toolscomb.com`）；(2) 之前手动加的 `CNAME cdn.toolscomb.com→workers.dev` 会和 Custom Domain 冲突导致 1016，删掉那条 CNAME 即可。
>
> 其余 4 个工具为纯静态，已托管到 **`https://content-toolbox.pages.dev`**，并绑定品牌域名 **`https://tools.1616666.xyz`**（两者同源，均实测通过）。
>
> 提示：品牌域名 `tools.1616666.xyz` 上使用 **R2 图床请切 Worker 模式**（cdn.toolscomb.com，无 CORS 限制，任意域名可用）；「浏览器直传」模式的 CORS 只放行 localhost 和 content-toolbox.pages.dev。
