/*
@header({
  searchable: 0,
  filterable: 1,
  quickSearch: 0,
  title: '88看球[体]',
  author: 'OpenClaw',
  lang: 'cat'
})
*/

let host = 'https://www.88kanqiu.la';
const headers = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
  'Referer': host + '/',
};

const B64_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

function base64ToUtf8(str) {
  str = String(str || '').replace(/[^A-Za-z0-9+/=]/g, '');
  const bytes = [];
  for (let i = 0; i < str.length; i += 4) {
    const c1 = B64_CHARS.indexOf(str.charAt(i));
    const c2 = B64_CHARS.indexOf(str.charAt(i + 1));
    const c3 = B64_CHARS.indexOf(str.charAt(i + 2));
    const c4 = B64_CHARS.indexOf(str.charAt(i + 3));
    if (c1 < 0 || c2 < 0) continue;
    const n = (c1 << 18) | (c2 << 12) | ((c3 < 0 ? 0 : c3) << 6) | (c4 < 0 ? 0 : c4);
    bytes.push((n >> 16) & 255);
    if (str.charAt(i + 2) !== '=') bytes.push((n >> 8) & 255);
    if (str.charAt(i + 3) !== '=') bytes.push(n & 255);
  }

  let out = '';
  for (let i = 0; i < bytes.length;) {
    const b1 = bytes[i++];
    if (b1 < 0x80) {
      out += String.fromCharCode(b1);
    } else if (b1 >= 0xc0 && b1 < 0xe0) {
      const b2 = bytes[i++] || 0;
      out += String.fromCharCode(((b1 & 0x1f) << 6) | (b2 & 0x3f));
    } else if (b1 >= 0xe0 && b1 < 0xf0) {
      const b2 = bytes[i++] || 0;
      const b3 = bytes[i++] || 0;
      out += String.fromCharCode(((b1 & 0x0f) << 12) | ((b2 & 0x3f) << 6) | (b3 & 0x3f));
    } else {
      const b2 = bytes[i++] || 0;
      const b3 = bytes[i++] || 0;
      const b4 = bytes[i++] || 0;
      const cp = ((b1 & 0x07) << 18) | ((b2 & 0x3f) << 12) | ((b3 & 0x3f) << 6) | (b4 & 0x3f);
      const u = cp - 0x10000;
      out += String.fromCharCode(0xd800 + (u >> 10), 0xdc00 + (u & 0x3ff));
    }
  }
  return out;
}

function decodePlaySource(raw) {
  if (!raw || typeof raw !== 'string') return null;
  const trimmed = raw.trim();

  for (let prefix = 0; prefix <= 8; prefix++) {
    for (let suffix = 0; suffix <= 4; suffix++) {
      if (trimmed.length <= prefix + suffix) continue;
      const candidate = trimmed.slice(prefix, trimmed.length - suffix || undefined);
      try {
        const decoded = base64ToUtf8(candidate);
        const jsonStart = decoded.indexOf('{');
        if (jsonStart >= 0) return JSON.parse(decoded.slice(jsonStart));
      } catch (e) {}
    }
  }

  try {
    const decoded = base64ToUtf8(trimmed);
    const jsonStart = decoded.indexOf('{');
    if (jsonStart >= 0) return JSON.parse(decoded.slice(jsonStart));
  } catch (e) {}
  return null;
}

function toDirectPlayUrl(url) {
  if (!url) return '';
  const m = String(url).match(/[?&]url=([^&]+)/);
  if (m && m[1]) {
    try { return decodeURIComponent(m[1]); } catch (e) { return m[1]; }
  }
  return url;
}

async function init(cfg) {
  if (cfg.ext && cfg.ext.startsWith('http')) host = cfg.ext.trim().replace(/\/$/, '');
}

async function home(filter) {
  return JSON.stringify({
    class: [
      { type_id: '', type_name: '全部直播' },
      //{ type_id: '1', type_name: '篮球直播' },
      //{ type_id: '8', type_name: '足球直播' },
      { type_id: '21', type_name: '其他直播' }
    ],
    filters: {
      '1': [{ key: 'cateId', name: '类型', value: [
        { n: 'NBA', v: '1' },
        { n: 'CBA', v: '2' },
        { n: '篮球综合', v: '4' },
        { n: '纬来体育', v: '21' }
      ] }],
      '8': [{ key: 'cateId', name: '类型', value: [
        { n: '英超', v: '8' },
        { n: '西甲', v: '9' },
        { n: '意甲', v: '10' },
        { n: '欧冠', v: '12' },
        { n: '欧联', v: '13' },
        { n: '德甲', v: '14' },
        { n: '法甲', v: '15' },
        { n: '欧国联', v: '16' },
        { n: '足总杯', v: '27' },
        { n: '国王杯', v: '33' },
        { n: '中超', v: '7' },
        { n: '亚冠', v: '11' },
        { n: '足球综合', v: '23' },
        { n: '欧协联', v: '28' },
        { n: '美职联', v: '26' }
      ] }]
    }
  });
}

async function homeVod() {
  return await category('', 1, null, {});
}

async function category(tid, pg, filter, extend = {}) {
  const cateId = (extend && extend.cateId) || tid || '';
  const path = cateId ? `/match/${cateId}/live` : '/';
  const html = (await req(host + path, { headers })).content;

  const list = [];
  const items = pdfa(html, '.list-group-item');
  items.forEach(it => {
    const btn = pdfa(it, '.btn.btn-primary,.btn.btn-default')[0];
    const time = pdfh(it, '.category-game-time&&Text').trim();
    const gameType = pdfh(it, '.game-type&&Text').trim();
    const team1 = pdfh(it, '.team-name:eq(0)&&Text').trim();
    const team2 = pdfh(it, '.team-name:eq(1)&&Text').trim();
    const title = `${time} ${gameType} ${team1} vs ${team2}`.trim();
    if (!title || title === 'vs') return;
    const href = btn ? pdfh(btn, 'a&&href') : '';
    const remark = btn ? pdfh(btn, 'a&&Text').trim() : '暂无';
    const pic = pdfh(it, 'img:eq(0)&&src') || '/static/img/default.png';
    list.push({
      vod_id: `${host}${href}###${encodeURIComponent(title)}`,
      vod_name: title,
      vod_pic: pic.startsWith('http') ? pic : host + pic,
      vod_remarks: remark
    });
  });

  return JSON.stringify({ page: 1, pagecount: 1, list });
}

async function detail(id) {
  let realId = id;
  let displayName = '赛事直播';
  if (id.includes('###')) {
    const parts = id.split('###', 2);
    realId = parts[0];
    displayName = decodeURIComponent(parts[1] || '赛事直播');
  }

  const match = realId.match(/\/live\/(\d+)\/play/);
  const gameId = match ? match[1] : '';
  if (!gameId) return JSON.stringify({ list: [] });

  const r = await req(`${host}/live/${gameId}/source`, {
    headers: { ...headers, Referer: realId }
  });
  const json = JSON.parse(r.content);
  const data = decodePlaySource(json.data || '');
  const links = (data && data.links) || [];
  const playUrls = links.map(i => `${i.name || '线路'}$${toDirectPlayUrl(i.url || '')}`).filter(Boolean).join('#');

  return JSON.stringify({
    list: [{
      vod_id: realId,
      vod_name: displayName,
      vod_pic: host + '/static/img/default.png',
      vod_remarks: '直播中',
      vod_play_from: '88看球',
      vod_play_url: playUrls,
      vod_content: '实时体育直播'
    }]
  });
}

async function search(wd, quick, pg = 1) {
  return JSON.stringify({ page: pg, list: [] });
}

async function play(flag, id, flags) {
  return JSON.stringify({ parse: 0, url: id });
}

export function __jsEvalReturn() {
  return { init, home, homeVod, category, search, detail, play };
}