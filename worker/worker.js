/**
 * content-toolbox R2 image host — Cloudflare Worker
 *
 * Routes:
 *   POST   /upload                 multipart/form-data: file, optional prefix
 *   GET    /view/<key>             stream an image from R2 (public)
 *   GET    /list                   list recent objects (requires API key if set)
 *   DELETE /delete?key=<key>       delete an object (requires API key if set)
 *
 * Auth (writes only): if env.API_KEY is set, Upload/List/Delete require an
 * `x-api-key` request header matching it. Views are always public.
 *
 * Deploy:
 *   cd worker && npx wrangler login && npx wrangler deploy
 *   # optional write-protection:
 *   npx wrangler secret put API_KEY
 */

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, x-api-key",
  "Access-Control-Max-Age": "3600",
};

function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...CORS, ...extra },
  });
}

function allowed(request, env) {
  if (!env.API_KEY) return true;
  return (request.headers.get("x-api-key") || "") === env.API_KEY;
}

function safeKey(name, prefix) {
  const ext = (name.split(".").pop() || "bin").toLowerCase().replace(/[^a-z0-9]/g, "");
  const base = (name.replace(/\.[^.]+$/, "") || "img").replace(/[^\w.-]/g, "_").slice(0, 50);
  const p = (prefix || "").replace(/^\/+|\/+$/g, "");
  return (p ? p + "/" : "") + Date.now() + "-" + base + "." + ext;
}

const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";
async function fj(url) {
  const r = await fetch(url, { headers: { "User-Agent": UA, "Accept": "application/json" } });
  return r.json();
}
async function hotToutiao() {
  const d = await fj("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc");
  return (d.data || []).map((x) => ({ title: x.Title || "", hot: x.HotValue || "", url: "https://www.toutiao.com/search/?keyword=" + encodeURIComponent(x.Title || "") }));
}
async function hotBili() {
  const d = await fj("https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all");
  return (d.data && d.data.list || []).slice(0, 20).map((x) => ({ title: x.title || "", url: "https://www.bilibili.com/video/" + x.bvid }));
}
async function hotBaidu() {
  const r = await fetch("https://top.baidu.com/board?tab=realtime", { headers: { "User-Agent": UA } });
  const html = await r.text();
  const m = html.match(/<!--s-data:([\s\S]*?)-->/);
  const d = JSON.parse(m ? m[1] : "{}");
  return (d.data && d.data.cards && d.data.cards[0].content || []).map((x) => ({ title: x.word || "", hot: x.hotScore, url: x.url || "https://top.baidu.com/board?tab=realtime" }));
}
async function hotGithub() {
  const since = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
  const d = await fj("https://api.github.com/search/repositories?q=created:>" + since + "&sort=stars&order=desc&per_page=15");
  return (d.items || []).map((x) => ({ title: x.full_name || "", hot: x.stargazers_count || "", url: x.html_url || "", desc: (x.description || "").slice(0, 120) }));
}
async function hotReddit() {
  const d = await fj("https://www.reddit.com/r/all/hot.json?limit=20");
  return (d.data && d.data.children || []).filter((c) => !c.data.stickied).map((c) => ({ title: c.data.title || "", hot: c.data.score || "", url: "https://www.reddit.com" + (c.data.permalink || "") }));
}
async function hotHackernews() {
  const ids = (await fj("https://hacker-news.firebaseio.com/v0/topstories.json") || []).slice(0, 15);
  const items = await Promise.all(ids.map((i) => fj("https://hacker-news.firebaseio.com/v0/item/" + i + ".json").catch(() => null)));
  return items.filter(Boolean).map((it) => ({ title: it.title || "", hot: it.score || "", url: it.url || ("https://news.ycombinator.com/item?id=" + it.id) }));
}
async function handleHot() {
  const tasks = { toutiao: hotToutiao(), bilibili: hotBili(), baidu: hotBaidu(), github: hotGithub(), hackernews: hotHackernews() };
  const platforms = {};
  for (const k of Object.keys(tasks)) {
    try { platforms[k] = { items: await tasks[k] }; }
    catch (e) { platforms[k] = { items: [], error: String((e && e.message) || e) }; }
  }
  return json({ updated: Date.now(), platforms });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const method = request.method;
    const { pathname } = url;

    if (method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });

    // Hot lists aggregation (works on custom domain; workers.dev may 1101)
    if (method === "GET" && pathname === "/hot") return handleHot();

    // Serve image
    if (method === "GET" && pathname.startsWith("/view/")) {
      const key = decodeURIComponent(pathname.slice("/view/".length));
      const obj = await env.BUCKET.get(key);
      if (!obj) return json({ error: "not found" }, 404);
      const headers = new Headers();
      obj.writeHttpMetadata(headers);
      headers.set("etag", obj.httpEtag);
      headers.set("Cache-Control", "public, max-age=31536000, immutable");
      headers.set("Access-Control-Allow-Origin", "*");
      return new Response(obj.body, { headers });
    }

    // Upload
    if (method === "POST" && pathname === "/upload") {
      if (!allowed(request, env)) return json({ error: "unauthorized" }, 401);
      const form = await request.formData();
      const file = form.get("file");
      if (!file || typeof file === "string") return json({ error: "no file" }, 400);
      const prefix = (form.get("prefix") || "").toString();
      const key = safeKey(file.name || "img.png", prefix);
      await env.BUCKET.put(key, file.stream(), {
        httpMetadata: { contentType: file.type || "application/octet-stream" },
      });
      return json({ url: `https://${url.host}/view/${encodeURIComponent(key)}`, key });
    }

    // Delete
    if (method === "DELETE" && pathname === "/delete") {
      if (!allowed(request, env)) return json({ error: "unauthorized" }, 401);
      const key = url.searchParams.get("key");
      if (!key) return json({ error: "no key" }, 400);
      await env.BUCKET.delete(key);
      return json({ ok: true });
    }

    // List
    if (method === "GET" && pathname === "/list") {
      if (!allowed(request, env)) return json({ error: "unauthorized" }, 401);
      const { objects } = await env.BUCKET.list({ limit: 50 });
      return json({
        items: objects.map((o) => ({
          key: o.key,
          url: `https://${url.host}/view/${encodeURIComponent(o.key)}`,
          size: o.size,
        })),
      });
    }

    return json(
      { error: "not found", usage: "POST /upload · GET /view/<key> · GET /list · DELETE /delete?key=" },
      404
    );
  },
};
