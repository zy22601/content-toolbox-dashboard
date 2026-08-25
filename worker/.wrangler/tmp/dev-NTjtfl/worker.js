var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });

// worker.js
var CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, x-api-key",
  "Access-Control-Max-Age": "3600"
};
function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...CORS, ...extra }
  });
}
__name(json, "json");
function allowed(request, env) {
  if (!env.API_KEY) return true;
  return (request.headers.get("x-api-key") || "") === env.API_KEY;
}
__name(allowed, "allowed");
function safeKey(name, prefix) {
  const ext = (name.split(".").pop() || "bin").toLowerCase().replace(/[^a-z0-9]/g, "");
  const base = (name.replace(/\.[^.]+$/, "") || "img").replace(/[^\w.-]/g, "_").slice(0, 50);
  const p = (prefix || "").replace(/^\/+|\/+$/g, "");
  return (p ? p + "/" : "") + Date.now() + "-" + base + "." + ext;
}
__name(safeKey, "safeKey");
var UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";
async function fj(url) {
  const r = await fetch(url, { headers: { "User-Agent": UA, "Accept": "application/json" } });
  return r.json();
}
__name(fj, "fj");
async function hotToutiao() {
  const d = await fj("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc");
  return (d.data || []).map((x) => ({ title: x.Title || "", hot: x.HotValue || "", url: "https://www.toutiao.com/search/?keyword=" + encodeURIComponent(x.Title || "") }));
}
__name(hotToutiao, "hotToutiao");
async function hotBili() {
  const d = await fj("https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all");
  return (d.data && d.data.list || []).slice(0, 20).map((x) => ({ title: x.title || "", url: "https://www.bilibili.com/video/" + x.bvid }));
}
__name(hotBili, "hotBili");
async function hotBaidu() {
  const r = await fetch("https://top.baidu.com/board?tab=realtime", { headers: { "User-Agent": UA } });
  const html = await r.text();
  const m = html.match(/<!--s-data:([\s\S]*?)-->/);
  const d = JSON.parse(m ? m[1] : "{}");
  return (d.data && d.data.cards && d.data.cards[0].content || []).map((x) => ({ title: x.word || "", hot: x.hotScore, url: x.url || "https://top.baidu.com/board?tab=realtime" }));
}
__name(hotBaidu, "hotBaidu");
async function hotGithub() {
  const since = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
  const d = await fj("https://api.github.com/search/repositories?q=created:>" + since + "&sort=stars&order=desc&per_page=15");
  return (d.items || []).map((x) => ({ title: x.full_name || "", hot: x.stargazers_count || "", url: x.html_url || "", desc: (x.description || "").slice(0, 120) }));
}
__name(hotGithub, "hotGithub");
async function hotHackernews() {
  const ids = (await fj("https://hacker-news.firebaseio.com/v0/topstories.json") || []).slice(0, 15);
  const items = await Promise.all(ids.map((i) => fj("https://hacker-news.firebaseio.com/v0/item/" + i + ".json").catch(() => null)));
  return items.filter(Boolean).map((it) => ({ title: it.title || "", hot: it.score || "", url: it.url || "https://news.ycombinator.com/item?id=" + it.id }));
}
__name(hotHackernews, "hotHackernews");
async function handleHot() {
  const tasks = { toutiao: hotToutiao(), bilibili: hotBili(), baidu: hotBaidu(), github: hotGithub(), hackernews: hotHackernews() };
  const platforms = {};
  for (const k of Object.keys(tasks)) {
    try {
      platforms[k] = { items: await tasks[k] };
    } catch (e) {
      platforms[k] = { items: [], error: String(e && e.message || e) };
    }
  }
  return json({ updated: Date.now(), platforms });
}
__name(handleHot, "handleHot");
var worker_default = {
  async fetch(request, env) {
    const url = new URL(request.url);
    const method = request.method;
    const { pathname } = url;
    if (method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    if (method === "GET" && pathname === "/hot") return handleHot();
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
    if (method === "POST" && pathname === "/upload") {
      if (!allowed(request, env)) return json({ error: "unauthorized" }, 401);
      const form = await request.formData();
      const file = form.get("file");
      if (!file || typeof file === "string") return json({ error: "no file" }, 400);
      const prefix = (form.get("prefix") || "").toString();
      const key = safeKey(file.name || "img.png", prefix);
      await env.BUCKET.put(key, file.stream(), {
        httpMetadata: { contentType: file.type || "application/octet-stream" }
      });
      return json({ url: `https://${url.host}/view/${encodeURIComponent(key)}`, key });
    }
    if (method === "DELETE" && pathname === "/delete") {
      if (!allowed(request, env)) return json({ error: "unauthorized" }, 401);
      const key = url.searchParams.get("key");
      if (!key) return json({ error: "no key" }, 400);
      await env.BUCKET.delete(key);
      return json({ ok: true });
    }
    if (method === "GET" && pathname === "/list") {
      if (!allowed(request, env)) return json({ error: "unauthorized" }, 401);
      const { objects } = await env.BUCKET.list({ limit: 50 });
      return json({
        items: objects.map((o) => ({
          key: o.key,
          url: `https://${url.host}/view/${encodeURIComponent(o.key)}`,
          size: o.size
        }))
      });
    }
    return json(
      { error: "not found", usage: "POST /upload \xB7 GET /view/<key> \xB7 GET /list \xB7 DELETE /delete?key=" },
      404
    );
  }
};

// ../../../.npm/_npx/d77349f55c2be1c0/node_modules/wrangler/templates/middleware/middleware-ensure-req-body-drained.ts
var drainBody = /* @__PURE__ */ __name(async (request, env, _ctx, middlewareCtx) => {
  try {
    return await middlewareCtx.next(request, env);
  } finally {
    try {
      if (request.body !== null && !request.bodyUsed) {
        const reader = request.body.getReader();
        while (!(await reader.read()).done) {
        }
      }
    } catch (e) {
      console.error("Failed to drain the unused request body.", e);
    }
  }
}, "drainBody");
var middleware_ensure_req_body_drained_default = drainBody;

// ../../../.npm/_npx/d77349f55c2be1c0/node_modules/wrangler/templates/middleware/middleware-miniflare3-json-error.ts
function reduceError(e) {
  return {
    name: e?.name,
    message: e?.message ?? String(e),
    stack: e?.stack,
    cause: e?.cause === void 0 ? void 0 : reduceError(e.cause)
  };
}
__name(reduceError, "reduceError");
var jsonError = /* @__PURE__ */ __name(async (request, env, _ctx, middlewareCtx) => {
  try {
    return await middlewareCtx.next(request, env);
  } catch (e) {
    const error = reduceError(e);
    const body = JSON.stringify(error);
    const headers = {
      "Content-Type": "application/json",
      "MF-Experimental-Error-Stack": "true"
    };
    const encoded = encodeURIComponent(body);
    if (encoded.length <= 8192) {
      headers["MF-Experimental-Error-Stack-Payload"] = encoded;
    }
    return new Response(body, { status: 500, headers });
  }
}, "jsonError");
var middleware_miniflare3_json_error_default = jsonError;

// .wrangler/tmp/bundle-wApmag/middleware-insertion-facade.js
var __INTERNAL_WRANGLER_MIDDLEWARE__ = [
  middleware_ensure_req_body_drained_default,
  middleware_miniflare3_json_error_default
];
var middleware_insertion_facade_default = worker_default;

// ../../../.npm/_npx/d77349f55c2be1c0/node_modules/wrangler/templates/middleware/common.ts
var __facade_middleware__ = [];
function __facade_register__(...args) {
  __facade_middleware__.push(...args.flat());
}
__name(__facade_register__, "__facade_register__");
function __facade_invokeChain__(request, env, ctx, dispatch, middlewareChain) {
  const [head, ...tail] = middlewareChain;
  const middlewareCtx = {
    dispatch,
    next(newRequest, newEnv) {
      return __facade_invokeChain__(newRequest, newEnv, ctx, dispatch, tail);
    }
  };
  return head(request, env, ctx, middlewareCtx);
}
__name(__facade_invokeChain__, "__facade_invokeChain__");
function __facade_invoke__(request, env, ctx, dispatch, finalMiddleware) {
  return __facade_invokeChain__(request, env, ctx, dispatch, [
    ...__facade_middleware__,
    finalMiddleware
  ]);
}
__name(__facade_invoke__, "__facade_invoke__");

// .wrangler/tmp/bundle-wApmag/middleware-loader.entry.ts
var __Facade_ScheduledController__ = class ___Facade_ScheduledController__ {
  constructor(scheduledTime, cron, noRetry) {
    this.scheduledTime = scheduledTime;
    this.cron = cron;
    this.#noRetry = noRetry;
  }
  scheduledTime;
  cron;
  static {
    __name(this, "__Facade_ScheduledController__");
  }
  #noRetry;
  noRetry() {
    if (!(this instanceof ___Facade_ScheduledController__)) {
      throw new TypeError("Illegal invocation");
    }
    this.#noRetry();
  }
};
function wrapExportedHandler(worker) {
  if (__INTERNAL_WRANGLER_MIDDLEWARE__ === void 0 || __INTERNAL_WRANGLER_MIDDLEWARE__.length === 0) {
    return worker;
  }
  for (const middleware of __INTERNAL_WRANGLER_MIDDLEWARE__) {
    __facade_register__(middleware);
  }
  const fetchDispatcher = /* @__PURE__ */ __name(function(request, env, ctx) {
    if (worker.fetch === void 0) {
      throw new Error("Handler does not export a fetch() function.");
    }
    return worker.fetch(request, env, ctx);
  }, "fetchDispatcher");
  return {
    ...worker,
    fetch(request, env, ctx) {
      const dispatcher = /* @__PURE__ */ __name(function(type, init) {
        if (type === "scheduled" && worker.scheduled !== void 0) {
          const controller = new __Facade_ScheduledController__(
            Date.now(),
            init.cron ?? "",
            () => {
            }
          );
          return worker.scheduled(controller, env, ctx);
        }
      }, "dispatcher");
      return __facade_invoke__(request, env, ctx, dispatcher, fetchDispatcher);
    }
  };
}
__name(wrapExportedHandler, "wrapExportedHandler");
function wrapWorkerEntrypoint(klass) {
  if (__INTERNAL_WRANGLER_MIDDLEWARE__ === void 0 || __INTERNAL_WRANGLER_MIDDLEWARE__.length === 0) {
    return klass;
  }
  for (const middleware of __INTERNAL_WRANGLER_MIDDLEWARE__) {
    __facade_register__(middleware);
  }
  return class extends klass {
    #fetchDispatcher = /* @__PURE__ */ __name((request, env, ctx) => {
      this.env = env;
      this.ctx = ctx;
      if (super.fetch === void 0) {
        throw new Error("Entrypoint class does not define a fetch() function.");
      }
      return super.fetch(request);
    }, "#fetchDispatcher");
    #dispatcher = /* @__PURE__ */ __name((type, init) => {
      if (type === "scheduled" && super.scheduled !== void 0) {
        const controller = new __Facade_ScheduledController__(
          Date.now(),
          init.cron ?? "",
          () => {
          }
        );
        return super.scheduled(controller);
      }
    }, "#dispatcher");
    fetch(request) {
      return __facade_invoke__(
        request,
        this.env,
        this.ctx,
        this.#dispatcher,
        this.#fetchDispatcher
      );
    }
  };
}
__name(wrapWorkerEntrypoint, "wrapWorkerEntrypoint");
var WRAPPED_ENTRY;
if (typeof middleware_insertion_facade_default === "object") {
  WRAPPED_ENTRY = wrapExportedHandler(middleware_insertion_facade_default);
} else if (typeof middleware_insertion_facade_default === "function") {
  WRAPPED_ENTRY = wrapWorkerEntrypoint(middleware_insertion_facade_default);
}
var middleware_loader_entry_default = WRAPPED_ENTRY;
export {
  __INTERNAL_WRANGLER_MIDDLEWARE__,
  middleware_loader_entry_default as default
};
//# sourceMappingURL=worker.js.map
