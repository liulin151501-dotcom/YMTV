/*!
 * @name 全豆要[聚合音源]
 * @description 迭代10.00稳定增强版，聚合星海/溯音/念心/长青/汽水，多链路智能回退，修复已知缺陷
 * @version 10.0
 * @author 全豆要 & Gemini & Toskysun & TZB679 & DeepSeek优化修复
 */

// --- 环境兼容 & 工具函数 ---
const DEBUG = false;
const log = DEBUG ? (...args) => console.log('[聚合音源]', ...args) : () => {};

// Promise.any polyfill
function promiseAny(promises) {
  return new Promise((resolve, reject) => {
    let pending = promises.length;
    const errors = [];
    if (pending === 0) return reject(new Error('No promises'));
    promises.forEach((p, idx) => {
      Promise.resolve(p).then(resolve).catch(err => {
        errors[idx] = err;
        if (--pending === 0) reject(new Error(errors.map(e => e?.message || String(e)).join('; ')));
      });
    });
  });
}

// --- 常量定义 ---
const CACHE_TTL_MS = 21600000; // 6小时
const CACHE_MAX_SIZE = 500;
const HTTP_URL_REGEX = /^https?:\/\//i;

// API 端点
const XINGHAI_MAIN_API = "https://music-api.gdstudio.xyz/api.php?use_xbridge3=true&loader_name=forest&need_sec_link=1&sec_link_scene=im&theme=light";
const XINGHAI_BACKUP_API = "https://music-dl.sayqz.com/api/";
const SUYIN_QQ_API = "https://oiapi.net/api/QQ_Music";
const SUYIN_QQ_KEY = "oiapi-ef6133b7-ac2f-dc7d-878c-d3e207a82575";
const SUYIN_163_API = "https://oiapi.net/api/Music_163";
const SUYIN_KUWO_API = "https://oiapi.net/api/Kuwo";
const SUYIN_MIGU_API = "https://api.xcvts.cn/api/music/migu";

// 需自行配置（留空则自动跳过）
const HUIBQ_API = "";
const HUIBQ_REQUEST_KEY = "";
const LINGCHUAN_API = "";

// 长青SVIP URL模板
const CHANGQING_URL_TEMPLATES = {
  tx: "http://175.27.166.236/kgqq/qq.php?type=mp3&id={id}&level={level}",
  wy: "http://175.27.166.236/wy/wy.php?type=mp3&id={id}&level={level}",
  kw: "https://musicapi.haitangw.net/music/kw.php?type=mp3&id={id}&level={level}",
  kg: "https://music.haitangw.cc/kgqq/kg.php?type=mp3&id={id}&level={level}",
  mg: "https://music.haitangw.cc/musicapi/mg.php?type=mp3&id={id}&level={level}"
};

// 念心SVIP URL模板
const NIANXIN_URL_TEMPLATES = {
  tx: "https://music.nxinxz.com/kgqq/tx.php?id={id}&level={level}&type=mp3",
  wy: "http://music.nxinxz.com/wy.php?id={id}&level={level}&type=mp3",
  kw: "http://music.nxinxz.com/kw.php?id={id}&level={level}&type=mp3",
  kg: "https://music.nxinxz.com/kgqq/kg.php?id={id}&level={level}&type=mp3",
  mg: "http://music.nxinxz.com/mg.php?id={id}&level={level}&type=mp3"
};

// 汽水VIP
const QISHUI_SOURCE_ID = "qsvip";
const QISHUI_SOURCE_NAME = "汽水VIP";
const QISHUI_API_HTTPS = "https://api.vsaa.cn/api/music.qishui.vip";
const QISHUI_API_HTTP = "http://api.vsaa.cn/api/music.qishui.vip";
const QISHUI_PROXY_API = "https://proxy.qishui.vsaa.cn/qishui/proxy";

// 各平台支持的音质列表
const PLATFORM_QUALITIES = {
  wy: ["24bit", "flac", "320k", "192k", "128k"],
  tx: ["24bit", "flac", "320k", "192k", "128k"],
  kw: ["24bit", "flac", "320k", "192k", "128k"],
  kg: ["24bit", "flac", "320k", "192k", "128k"],
  mg: ["24bit", "flac", "320k", "192k", "128k"]
};

// 平台映射到星海主API名称
const PLATFORM_TO_XINGHAI = {
  wy: "netease", tx: "tencent", kw: "kuwo", kg: "kugou", mg: "migu"
};

// 音质到星海主API码率参数（修复flac24bit映射）
const QUALITY_TO_BR = {
  "128k": "128", "192k": "192", "320k": "320", 
  "flac": "740", "flac24bit": "999", "24bit": "999"
};

// 平台映射到星海备API名称
const PLATFORM_TO_XINGHAI_BACKUP = {
  wy: "netease", tx: "qq", kw: "kuwo"
};

// 溯音QQ 码率映射
const QUALITY_TO_SUYIN_QQ_BR = {
  "128k": 7, "192k": 6, "320k": 5, "flac": 4, "hires": 3, "atmos": 2, "master": 1, "24bit": 1
};

// 溯音酷我 码率映射
const QUALITY_TO_KUWO_BR = {
  flac: 1, "320k": 5, "128k": 7, "24bit": 1
};

// 高品质音质集合
const HIRES_QUALITY_SET = new Set(["24bit", "flac", "flac24bit", "hires", "master", "atmos"]);

// --- 缓存实现 (修复LRU更新逻辑) ---
const urlCache = new Map();
const cacheKeys = [];

function getCachedUrl(cacheKey) {
  const entry = urlCache.get(cacheKey);
  if (!entry) return null;
  if (Date.now() - entry.timestamp >= CACHE_TTL_MS) {
    urlCache.delete(cacheKey);
    const idx = cacheKeys.indexOf(cacheKey);
    if (idx > -1) cacheKeys.splice(idx, 1);
    return null;
  }
  // 更新LRU顺序：移除后重新加入尾部
  const idx = cacheKeys.indexOf(cacheKey);
  if (idx > -1) cacheKeys.splice(idx, 1);
  cacheKeys.push(cacheKey);
  return entry.url;
}

function setCachedUrl(cacheKey, url) {
  // 如果已存在，先删除旧记录，再添加新记录（保证timestamp更新且顺序正确）
  if (urlCache.has(cacheKey)) {
    const idx = cacheKeys.indexOf(cacheKey);
    if (idx > -1) cacheKeys.splice(idx, 1);
    urlCache.delete(cacheKey);
  }
  urlCache.set(cacheKey, { url, timestamp: Date.now() });
  cacheKeys.push(cacheKey);
  if (cacheKeys.length > CACHE_MAX_SIZE) {
    const oldestKey = cacheKeys.shift();
    urlCache.delete(oldestKey);
  }
}

const { EVENT_NAMES, request, on, send } = globalThis.lx;

// --- 请求封装（增强错误信息）---
function httpRequest(url, options = { method: "GET" }) {
  return new Promise((resolve, reject) => {
    request(url, { timeout: 20000, ...options }, (err, res) => {
      if (err) return reject(new Error(`请求错误: ${err.message}`));
      let body = res?.body;
      if (typeof body === "string") {
        const trimmed = body.trim();
        if (trimmed.startsWith("{") || trimmed.startsWith("[") || trimmed.startsWith("\"")) {
          try { body = JSON.parse(trimmed); } catch {}
        }
      }
      resolve({ statusCode: res?.statusCode ?? 0, headers: res?.headers || {}, body });
    });
  });
}

async function httpGet(url, params = {}) {
  const queryStr = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");
  const sep = url.includes("?") ? "&" : "?";
  const fullUrl = url + (queryStr ? sep + queryStr : "");
  const res = await httpRequest(fullUrl, { method: "GET", timeout: 10000 });
  if (res.statusCode >= 400) throw new Error(`HTTP错误: ${res.statusCode}`);
  return res.body;
}

async function httpGetWithFallback(url, params = {}, timeout = 15000) {
  const urls = url === QISHUI_API_HTTPS ? [QISHUI_API_HTTPS, QISHUI_API_HTTP] : [url];
  let lastError = null;
  for (const u of urls) {
    try {
      const queryStr = Object.entries(params)
        .filter(([, v]) => v != null)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
        .join("&");
      const fullUrl = u + (queryStr ? (u.includes("?") ? "&" : "?") + queryStr : "");
      const res = await httpRequest(fullUrl, { method: "GET", timeout });
      if (res.statusCode >= 400) throw new Error(`HTTP ${res.statusCode}`);
      return res.body;
    } catch (e) { lastError = e; }
  }
  throw lastError || new Error("请求失败");
}

async function httpPost(url, body = {}, timeout = 20000) {
  const res = await httpRequest(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    timeout
  });
  if (res.statusCode >= 400) throw new Error(`HTTP错误: ${res.statusCode}`);
  return res.body;
}

// --- 工具函数 ---
function getSongId(songInfo) {
  return String(songInfo?.id || songInfo?.songmid || songInfo?.songId || songInfo?.hash || songInfo?.rid || songInfo?.mid || songInfo?.strMediaMid || songInfo?.mediaId || "");
}

function normalizeQuality(quality) {
  const q = String(quality || "128k").toLowerCase();
  if (q === "128k") return "low";
  if (q === "320k") return "standard";
  if (q === "flac") return "lossless";
  if (q === "flac24bit" || q === "24bit") return "flac24bit";
  return "128k";
}

function normalizeSongInfo(raw) {
  const id = raw?.id || raw?.vid ? String(raw.id || raw.vid) : "";
  return {
    id,
    songmid: id,
    hash: id,
    name: raw?.name ? String(raw.name) : "未知歌曲",
    singer: raw?.artists ? String(raw.artists) : "未知歌手",
    albumName: raw?.album ? String(raw.album) : "",
    duration: raw?.duration ? Math.floor(Number(raw.duration) / 1000) : 0,
    pic: raw?.cover || raw?.pic ? String(raw.cover || raw.pic) : "",
    _raw: raw || {}
  };
}

function getFirstData(response) {
  const data = response?.data;
  if (Array.isArray(data)) return data[0] || null;
  if (data && typeof data === "object" && data[0]) return data[0];
  return null;
}

// 标准化关键词
function normalizeKeyword(keyword) {
  return String(keyword || "")
    .replace(/\(\s*Live\s*\)/gi, "")
    .replace(/\([^)]*\)/g, "")
    .replace(/\s+/g, "")
    .replace(/[^\w\u4e00-\u9fa5]/g, "")
    .trim()
    .toLowerCase();
}

function titleMatch(a, b) {
  const na = normalizeKeyword(a);
  const nb = normalizeKeyword(b);
  return na && nb ? na.includes(nb) || nb.includes(na) : true;
}

function songInfoMatch(item, target) {
  const song = item?.song || item?.data?.song || item?.title || "";
  const singer = item?.singer || item?.data?.singer || item?.artist || "";
  const album = item?.album || item?.data?.album || "";
  if (!titleMatch(song, target?.name || "")) return false;
  if (target?.singer && singer && !titleMatch(singer, target.singer)) return false;
  if ((target?.albumName || target?.album) && album && !titleMatch(album, target.albumName || target.album)) return false;
  return true;
}

// 新增：通用的歌曲标题匹配（用于溯音咪咕等）
function songTitleMatch(res, songInfo) {
  const title = res?.title || res?.name || "";
  const artist = res?.artist || res?.singer || "";
  if (!titleMatch(title, songInfo?.name || "")) return false;
  if (songInfo?.singer && artist && !titleMatch(artist, songInfo.singer)) return false;
  return true;
}

function buildSearchKeywords(songInfo) {
  const name = songInfo?.name || "";
  const album = songInfo?.albumName || songInfo?.album || "";
  const singer = songInfo?.singer || "";
  const keywords = [];
  if (name && album) {
    const kw = normalizeKeyword(name + album);
    if (kw) keywords.push({ keyword: kw, strict: true });
  }
  if (name && singer) {
    const kw = normalizeKeyword(name + singer);
    if (kw) keywords.push({ keyword: kw, strict: true });
  }
  if (name) {
    const kw = normalizeKeyword(name);
    if (kw) keywords.push({ keyword: kw, strict: false });
  }
  return keywords;
}

function getPlatformSongId(platform, songInfo) {
  if (platform === "kg") return songInfo?.hash || songInfo?.songmid || songInfo?.id || songInfo?.rid || songInfo?.mid;
  if (platform === "tx") {
    const mid = songInfo?.meta?.qq?.mid || songInfo?.meta?.mid || songInfo?.songmid ||
      (typeof songInfo?.id === "string" && !/^\d+$/.test(songInfo.id) ? songInfo.id : null);
    if (mid) return mid;
    const songid = songInfo?.meta?.qq?.songid || songInfo?.meta?.songid ||
      (typeof songInfo?.id === "number" ? songInfo.id : (typeof songInfo?.id === "string" && /^\d+$/.test(songInfo.id) ? Number(songInfo.id) : null));
    return songid;
  }
  return songInfo?.songmid || songInfo?.id || songInfo?.songId || songInfo?.rid || songInfo?.hash;
}

function buildCacheKey(prefix, songInfo, quality = "") {
  const id = getPlatformSongId(prefix, songInfo) || getSongId(songInfo);
  return `${prefix}_${id}_${quality}`;
}

function validateUrl(url, sourceName) {
  if (!url || typeof url !== "string") throw new Error(`${sourceName}返回空URL`);
  if (!HTTP_URL_REGEX.test(url.trim())) throw new Error(`${sourceName}非法URL格式`);
  return url.trim();
}

function selectQuality(requested, supported) {
  const order = ["24bit", "flac", "flac24bit", "320k", "192k", "128k"];
  const req = String(requested || "128k").toLowerCase();
  if (supported.includes(req)) return req;
  const startIdx = order.indexOf(req);
  if (startIdx > -1) {
    for (let i = startIdx; i < order.length; i++) if (supported.includes(order[i])) return order[i];
  }
  for (let i = order.length - 1; i >= 0; i--) if (supported.includes(order[i])) return order[i];
  return supported[0] || "128k";
}

// --- 汽水VIP实现（增加重试和超时保护）---
async function qishuiSearch(keyword, page = 1, pageSize = 30) {
  if (!keyword) return { isEnd: true, list: [] };
  const res = await httpGetWithFallback(QISHUI_API_HTTPS, {
    act: "search", keywords: keyword, page, pagesize: pageSize, type: "music"
  }, 15000);
  const list = Array.isArray(res?.data?.lists) ? res.data.lists : [];
  return {
    isEnd: list.length < pageSize,
    list: list.map(normalizeSongInfo),
    total: res?.data?.total ? Number(res.data.total) : list.length
  };
}

async function qishuiGetUrl(songInfo, quality) {
  const songId = getSongId(songInfo);
  if (!songId) throw new Error("汽水VIP缺少歌曲ID");
  const res = await httpGetWithFallback(QISHUI_API_HTTPS, {
    act: "song", id: songId, quality: normalizeQuality(quality)
  }, 20000);
  const data = getFirstData(res);
  if (!data?.url) throw new Error("汽水VIP未返回可用URL");
  if (data.ekey) {
    const proxyRes = await httpPost(QISHUI_PROXY_API, {
      url: data.url, key: data.ekey, filename: data.filename || "KMusic", ext: data.fileExtension || "aac"
    }, 60000);
    if (Number(proxyRes?.code) === 200 && proxyRes?.url) return String(proxyRes.url);
    throw new Error("汽水VIP代理解密失败");
  }
  return String(data.url);
}

async function qishuiGetLyric(songInfo) {
  const songId = getSongId(songInfo);
  if (!songId) return { lyric: "" };
  const res = await httpGetWithFallback(QISHUI_API_HTTPS, { act: "song", id: songId }, 15000);
  const data = getFirstData(res);
  return { lyric: data?.lyric ? String(data.lyric) : "" };
}

async function qishuiHandler(action, params = {}) {
  if (action === "musicSearch" || action === "search") {
    return qishuiSearch(params?.keyword || "", params?.page || 1, params?.pagesize || 30);
  }
  if (action === "musicUrl") {
    if (!params?.musicInfo) throw new Error("请求参数不完整");
    return validateUrl(await qishuiGetUrl(params.musicInfo, params.type), "汽水VIP");
  }
  if (action === "lyric") return qishuiGetLyric(params?.musicInfo || {});
  throw new Error("action not support");
}

// --- 星海主/备 ---
async function xinghaiMainGetUrl(platform, songId, quality, songInfo) {
  const source = PLATFORM_TO_XINGHAI[platform];
  if (!source) throw new Error("星海主不支持该平台");
  const id = songId ?? getPlatformSongId(platform, songInfo);
  if (!id) throw new Error("缺少songId");
  const br = QUALITY_TO_BR[selectQuality(quality, ["128k","192k","320k","flac","flac24bit"])] || "128";
  const url = `${XINGHAI_MAIN_API}&types=url&source=${source}&id=${encodeURIComponent(id)}&br=${br}`;
  const res = await httpRequest(url, { headers: { "User-Agent": "LX-Music-Mobile" } });
  const body = res.body;
  if (!body?.url) throw new Error(body?.message || "星海主未返回URL");
  return body.url;
}

async function xinghaiBackupGetUrl(platform, songId, quality, songInfo) {
  const source = PLATFORM_TO_XINGHAI_BACKUP[platform];
  if (!source) throw new Error("星海备不支持该平台");
  const id = songId ?? getPlatformSongId(platform, songInfo);
  if (!id) throw new Error("缺少songId");
  const br = selectQuality(quality, ["128k","192k","320k","flac","flac24bit"]);
  const res = await httpGet(XINGHAI_BACKUP_API, { source, id, type: "url", br });
  if (!res?.url) throw new Error("星海备未返回url");
  return res.url;
}

// --- Huibq/聆川 (若配置) ---
async function huibqGetUrl(platform, songId, quality, songInfo) {
  if (!HUIBQ_API || !HUIBQ_REQUEST_KEY) throw new Error("Huibq未配置");
  const hash = songInfo?.hash ?? songInfo?.songmid;
  if (!hash) throw new Error("缺少hash");
  const q = selectQuality(quality, ["320k","128k"]);
  const url = `${HUIBQ_API}/url/${platform}/${encodeURIComponent(hash)}/${q}`;
  const res = await httpRequest(url, {
    headers: { "X-Request-Key": HUIBQ_REQUEST_KEY, "User-Agent": "Mozilla/5.0" }
  });
  const body = res.body;
  if (body?.code !== 0) throw new Error(body?.message || "Huibq错误");
  if (!body.url) throw new Error("Huibq空URL");
  return body.url;
}

async function lingchuanGetUrl(platform, songId, quality, songInfo) {
  if (!LINGCHUAN_API) throw new Error("聆川未配置");
  const hash = songInfo?.hash ?? songInfo?.songmid;
  if (!hash) throw new Error("缺少hash");
  const q = selectQuality(quality, ["320k","128k"]);
  const res = await httpGet(`${LINGCHUAN_API}/url`, { source: platform, songId: hash, quality: q });
  if (res?.code !== 200) throw new Error(res?.message || "聆川错误");
  if (!res.url) throw new Error("聆川空URL");
  return res.url;
}

// --- 溯音系列 ---
async function suyinQQGetUrl(songInfo, quality) {
  const mid = songInfo?.meta?.qq?.mid || songInfo?.meta?.mid || songInfo?.songmid ||
    (typeof songInfo?.id === "string" && !/^\d+$/.test(songInfo.id) ? songInfo.id : null);
  const songid = songInfo?.meta?.qq?.songid || songInfo?.meta?.songid ||
    (typeof songInfo?.id === "number" ? songInfo.id : (typeof songInfo?.id === "string" && /^\d+$/.test(songInfo.id) ? Number(songInfo.id) : null));
  if (!mid && !songid) throw new Error("缺少QQ音乐ID");

  const tryBrs = [5,4,3,2,1,7,6].filter(v => v >= (QUALITY_TO_SUYIN_QQ_BR[quality] || 7));
  let lastErr;
  for (const br of tryBrs) {
    try {
      const params = { key: SUYIN_QQ_KEY, type: "json", br, n: 1 };
      if (mid) params.mid = mid; else params.songid = songid;
      const res = await httpGet(SUYIN_QQ_API, params);
      const url = res?.music || res?.url || res?.message?.match(/音频链接[：:](.+?)(?:\n|$)/)?.[1];
      if (url) return url.trim();
    } catch (e) { lastErr = e; }
  }
  throw lastErr || new Error("溯音QQ失败");
}

async function suyin163GetUrl(songInfo) {
  const id = songInfo?.songmid || songInfo?.id;
  if (!id) throw new Error("缺少网易云ID");
  const res = await httpGet(SUYIN_163_API, { id });
  if (res?.code === 0 && res?.data) {
    const item = Array.isArray(res.data) ? res.data[0] : res.data;
    if (item?.url) return item.url;
  }
  throw new Error("溯音163获取失败");
}

async function suyinKuwoGetUrl(songInfo, quality) {
  if (!songInfo?.name) throw new Error("需要歌曲名");
  const cacheKey = buildCacheKey("kw", songInfo, quality);
  const cached = getCachedUrl(cacheKey);
  if (cached) return cached;

  const br = QUALITY_TO_KUWO_BR[selectQuality(quality, ["flac","320k","128k"])] || 1;
  const keywords = buildSearchKeywords(songInfo);
  let lastErr;
  for (const { keyword, strict } of keywords) {
    try {
      const res = await httpGet(SUYIN_KUWO_API, { msg: keyword, n: 1, br });
      let url = res?.data?.url;
      if (!url) {
        const match = String(res?.message || "").match(/音乐链接[：:](\S+)/);
        url = match?.[1];
      }
      if (url) {
        if (strict && !songInfoMatch(res, songInfo)) continue;
        setCachedUrl(cacheKey, url);
        return url;
      }
    } catch (e) { lastErr = e; }
  }
  throw lastErr || new Error("溯音酷我失败");
}

async function suyinMiguGetUrl(songInfo) {
  if (!songInfo?.name) throw new Error("需要歌曲名");
  const cacheKey = buildCacheKey("mg", songInfo);
  const cached = getCachedUrl(cacheKey);
  if (cached) return cached;

  const keywords = buildSearchKeywords(songInfo);
  let lastErr;
  for (const { keyword, strict } of keywords) {
    try {
      const res = await httpGet(SUYIN_MIGU_API, { gm: keyword, n: 1, num: 1, type: "json" });
      let url = res?.musicInfo || res?.url || res?.data?.url;
      if (!url && res?.message) {
        const match = String(res.message).match(/链接[：:](\S+)/);
        url = match?.[1];
      }
      if (url && HTTP_URL_REGEX.test(url)) {
        // 修复：使用 songTitleMatch 代替未定义的 songTitleMatch
        if (strict && !songTitleMatch(res, songInfo)) continue;
        setCachedUrl(cacheKey, url);
        return url;
      }
    } catch (e) { lastErr = e; }
  }
  throw lastErr || new Error("溯音咪咕失败");
}

// --- 长青/念心 ---
function buildTemplateUrl(platform, quality, songInfo, templates, sourceName) {
  const template = templates[platform];
  if (!template) throw new Error(`${sourceName}不支持该平台`);
  const songId = getPlatformSongId(platform, songInfo);
  if (!songId) throw new Error("缺少songId");
  let level = "128k";
  if (quality.includes("flac") || quality.includes("24bit")) level = "flac";
  else if (quality.includes("320k")) level = "320k";
  return template.replace("{id}", encodeURIComponent(songId)).replace("{level}", level);
}

async function changqingGetUrl(platform, songId, quality, songInfo) {
  return buildTemplateUrl(platform, quality, songInfo, CHANGQING_URL_TEMPLATES, "长青SVIP");
}
async function nianxinGetUrl(platform, songId, quality, songInfo) {
  return buildTemplateUrl(platform, quality, songInfo, NIANXIN_URL_TEMPLATES, "念心SVIP");
}

// --- 构建回退链 ---
const SOURCE_HANDLERS = {};
function initHandlers() {
  const base = {
    xinghai: { name: "星海主", fn: xinghaiMainGetUrl },
    suyinQQ: { name: "溯音QQ", fn: (p, sid, q, si) => suyinQQGetUrl(si, q) },
    suyin163: { name: "溯音163", fn: (p, sid, q, si) => suyin163GetUrl(si) },
    suyinKw: { name: "溯音酷我", fn: (p, sid, q, si) => suyinKuwoGetUrl(si, q) },
    suyinMg: { name: "溯音咪咕", fn: (p, sid, q, si) => suyinMiguGetUrl(si) },
    changqing: { name: "长青SVIP", fn: changqingGetUrl },
    nianxin: { name: "念心SVIP", fn: nianxinGetUrl },
    xinghaiBackup: { name: "星海备", fn: xinghaiBackupGetUrl },
  };
  if (HUIBQ_API && HUIBQ_REQUEST_KEY) base.huibq = { name: "Huibq", fn: huibqGetUrl };
  if (LINGCHUAN_API) base.lingchuan = { name: "聆川", fn: lingchuanGetUrl };
  Object.assign(SOURCE_HANDLERS, base);
}
initHandlers();

function buildChain(platform) {
  const order = ["xinghai", "huibq", "suyin163", "suyinQQ", "suyinKw", "suyinMg", "lingchuan", "changqing", "nianxin", "xinghaiBackup"];
  return order
    .filter(k => SOURCE_HANDLERS[k])
    .filter(k => {
      if (k === "suyin163" && platform !== "wy") return false;
      if (k === "suyinQQ" && platform !== "tx") return false;
      if (k === "suyinKw" && platform !== "kw") return false;
      if (k === "suyinMg" && platform !== "mg") return false;
      return true;
    })
    .map(k => SOURCE_HANDLERS[k]);
}

// --- 聚合获取URL（增强并发控制）---
async function getUrlWithFallback(platform, songInfo, quality) {
  if (!PLATFORM_QUALITIES[platform]) throw new Error("无效平台");
  const selectedQuality = selectQuality(quality || "128k", PLATFORM_QUALITIES[platform]);
  const songId = getPlatformSongId(platform, songInfo);
  const chain = buildChain(platform);
  if (!chain.length) throw new Error("无可用的音源");

  const errors = [];
  const concurrentCount = Math.min(3, chain.length);
  const firstBatch = chain.slice(0, concurrentCount).map(h =>
    h.fn(platform, songId, selectedQuality, songInfo).then(url => validateUrl(url, h.name))
  );

  try {
    return await promiseAny(firstBatch);
  } catch (e) {
    errors.push(...(e.message?.split('; ') || [e.message]));
  }

  for (let i = concurrentCount; i < chain.length; i++) {
    const h = chain[i];
    try {
      const url = await h.fn(platform, songId, selectedQuality, songInfo);
      return validateUrl(url, h.name);
    } catch (e) {
      errors.push(`${h.name}: ${e.message}`);
    }
  }
  throw new Error(`所有源失败: ${errors.join('; ')}`);
}

// --- 搜索聚合（保持汽水搜索，可扩展）---
async function aggregateSearch(keyword, page = 1, pageSize = 30) {
  return qishuiSearch(keyword, page, pageSize);
}

// --- 音源注册 ---
const sourceConfig = {};
Object.keys(PLATFORM_QUALITIES).forEach(p => {
  sourceConfig[p] = {
    name: { wy:"网易云", tx:"QQ", kw:"酷我", kg:"酷狗", mg:"咪咕" }[p],
    type: "music",
    actions: ["musicUrl"],
    qualitys: PLATFORM_QUALITIES[p]
  };
});
sourceConfig[QISHUI_SOURCE_ID] = {
  name: QISHUI_SOURCE_NAME,
  type: "music",
  actions: ["musicSearch", "musicUrl", "lyric"],
  qualitys: ["128k", "320k", "flac", "flac24bit"]
};

// 主事件监听
on(EVENT_NAMES.request, ({ action, source, info }) => {
  if (source === QISHUI_SOURCE_ID) return qishuiHandler(action, info);
  if (action === "musicSearch") {
    return aggregateSearch(info?.keyword, info?.page, info?.pagesize);
  }
  if (action === "musicUrl") {
    if (!info?.musicInfo) return Promise.reject(new Error("缺少歌曲信息"));
    return getUrlWithFallback(source, info.musicInfo, info.type || "128k");
  }
  return Promise.reject(new Error("不支持的操作"));
});

send(EVENT_NAMES.inited, { openDevTools: false, sources: sourceConfig });
log("聚合音源 v10.00 已就绪 (修复LRU缓存、songTitleMatch缺失、音质映射等)");