# 内容工作台 · Content Toolbox

一个**单文件 + 本机服务器**的内容创作工作台，把写内容高频用到的 **16 个工具**打包进一个浏览器标签。**全本地、零后端、零成本**；也附一份 Hermes/Agent 技能（`SKILL.md`）沉淀完整搭建与踩坑经验。

> ⚠️ 本仓库**不含任何密钥**。DeepSeek / 红狐(RedFox) key 只写进你本机的 `config.secret.json`（mode 600），**不要提交**（见 `.gitignore`）。

## 16 个工具

**工具**：R2 图床 · Markdown→PNG · 图文卡片 · 去 Emoji · 公众号排版 · 封面生成 · 字数统计 · 二维码生成
**图片**：九宫格切图 · 图片压缩/转换 · 图片加水印
**选题·发布**：热榜选题 · 一键分发 · AI 周报 · 违禁词检测
**知识库**：本地 Markdown 知识库（可导出 Obsidian）

## 运行

```bash
cd content-toolbox
python3 server.py            # → http://localhost:8080
```

`server.py` 是 **Python 标准库、零依赖**。用 `localhost`（而非 file://）打开才是浏览器「安全上下文」——R2 签名、剪贴板复制、知识库写入这些才正常。

## 本地 API（仅 localhost）

| 接口 | 作用 |
|------|------|
| `/api/hot` | 聚合 头条/百度/B站/GitHub 趋势/**红狐·抖音爆款** 热榜，每次刷新写当日快照 |
| `/api/trend?days=7\|14` | 每日快照算出 📈增长/🆕新上榜/➖稳定/📉冷却 及在榜天数 |
| `/api/ai_topics` (POST) | 用本地 DeepSeek 结合热榜证据 + 账号定位生成选题 |
| `/api/kb` (GET/POST/DELETE + search + export) | 本地知识库（`data/kb/*.md`，Obsidian frontmatter） |

更完整的 API 与热榜源取舍见 `SKILL.md` 与 `references/redfox-douyin.md`。

## 部署（可选）

`index.html` + `vendor/` 是纯静态，可直接推到 **Cloudflare Pages**（零成本）做公开版；`worker/` 是 R2 图床的 Cloudflare Worker（写端口用 `API_KEY` 保护）。

## 结构

```
content-toolbox/
├── index.html          # 工作台（16 工具，单文件）
├── server.py           # 本地服务器（stdlib；含每日快照线程）
├── config.secret.json  # ⚠️ 本地密钥（不提交）
├── data/trend/         # 热榜每日快照
├── data/kb/            # 知识库 markdown
├── vendor/             # markdown-it / html2canvas / jszip / qrcode（本地 vendored）
└── worker/             # Cloudflare Worker（R2 图床 + /hot 兜底）
```

## 技能

`SKILL.md` 可作为 **Hermes/Agent 技能**安装，覆盖：单文件 dashboard 构建、R2 直传→Worker 演进、Cloudflare Pages 部署、热榜源可达性取舍、趋势/AI选题/知识库/违禁词/红狐抖音接入、以及 launchd 托管与网络 MITM 的 SSL 坑。
