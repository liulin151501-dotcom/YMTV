import { _ } from 'assets://js/lib/cat.js';
import 'assets://js/lib/crypto-js.js';

let baseUrl = '';
const DEFAULT_BASE = 'https://app.365ting.com/listen/Apitzg2025/';
const HEADERS = {
    'User-Agent': 'TingShiJie/1.8.8 (m.i275.com)'
};

function md5(str) {
    return CryptoJS.MD5(str).toString();
}

async function requestJson(url) {
    let res = await req(url, { headers: HEADERS, timeout: 10000 });
    let content = typeof res === 'string' ? res : (res.content || '');
    try {
        return JSON.parse(content);
    } catch (e) {
        return null;
    }
}

async function ensureInit() {
    if (baseUrl) return;
    try {
        let configUrl = 'http://101.43.48.231:8090/config/tingchina2025.txt';
        let res = await req(configUrl, { headers: HEADERS, timeout: 5000 });
        let content = typeof res === 'string' ? res : (res.content || '');
        baseUrl = (content && content.trim()) ? content.trim() : DEFAULT_BASE;
    } catch (e) {
        baseUrl = DEFAULT_BASE;
    }
    if (!baseUrl.endsWith('/')) baseUrl += '/';
}

async function init() {
    await ensureInit();
}

async function home(filter) {
    await ensureInit();
    let classes = [];
    try {
        let catJson = await requestJson(baseUrl + 'category/list');
        if (catJson?.status === 0 && Array.isArray(catJson.data)) {
            for (let cat of catJson.data) {
                if (cat.id && cat.name) {
                    classes.push({ type_id: cat.id.toString(), type_name: cat.name });
                }
            }
        }
    } catch (e) {}
    return JSON.stringify({ class: classes, list: [] });
}

async function category(tid, pg, filter, extend) {
    await ensureInit();
    let page = parseInt(pg) || 1;
    let url = `${baseUrl}appHomeByCategory?categoryId=${tid}&page=${page}&size=120`;
    let videos = [];
    try {
        let json = await requestJson(url);
        if (json?.status === 0 && Array.isArray(json.data)) {
            for (let item of json.data) {
                videos.push({
                    vod_id: item.id ? item.id.toString() : '',
                    vod_name: item.bookTitle || '',
                    vod_pic: item.bookImage || '',
                    vod_remarks: item.bookAnchor || ''
                });
            }
        }
    } catch (e) {}
    let pagecount = videos.length < 120 ? page : page + 1;
    return JSON.stringify({
        page: page,
        pagecount: pagecount,
        limit: 20,
        total: 2000,
        list: videos
    });
}

async function detail(id) {
    await ensureInit();
    let bookId = (Array.isArray(id) ? id[0] : id).toString();
    try {
        let url = `${baseUrl}book?bookId=${bookId}`;
        let json = await requestJson(url);
        if (!json || json.status !== 0) throw new Error();
        let bookData = json.data?.bookData;
        if (!bookData) throw new Error();
        let title = bookData.bookTitle || '';
        let desc = bookData.bookDesc || '';
        let cover = bookData.bookImage || '';
        let totalChapters = bookData.count || 0;
        let pageCount = Math.ceil(totalChapters / 1000);
        let playUrlParts = [];
        for (let p = 1; p <= pageCount; p++) {
            let chapUrl = `${baseUrl}chapter?size=1000&page=${p}&sort=asc&bookId=${bookId}`;
            let chapJson = await requestJson(chapUrl);
            if (chapJson?.status === 0 && chapJson.data?.list) {
                for (let chap of chapJson.data.list) {
                    let position = chap.position;
                    let chapterId = chap.chapterId;
                    if (position && chapterId) {
                        playUrlParts.push(`${position}$${bookId}|${chapterId}`);
                    }
                }
            }
        }
        let vod = {
            vod_id: bookId,
            vod_name: title,
            vod_pic: cover,
            vod_play_from: '世界听书',
            vod_play_url: playUrlParts.join('#'),
            vod_content: desc
        };
        return JSON.stringify({ list: [vod] });
    } catch (e) {
        return JSON.stringify({ list: [] });
    }
}

async function play(flag, id, flags) {
    await ensureInit();
    try {
        let parts = id.split('|');
        if (parts.length < 2) throw new Error();
        let bookId = parts[0];
        let chapterId = parts[1];
        let timestamp = Date.now().toString();
        let key = 'J9gSpfUlzYxE8Hn5IXiGaD2jVMrwAm0K';
        let sign1 = md5(timestamp + key);
        let sign2 = md5(sign1 + key);
        let url = `${baseUrl}AppGetChapterUrl2023?timeStamp=${timestamp}&uid=&chapterId=${chapterId}&addItParapet=${sign2}&bookId=${bookId}`;
        let json = await requestJson(url);
        if (json?.status === 0 && json.src) {
            return JSON.stringify({ parse: 0, url: json.src, header: {} });
        }
    } catch (e) {}
    return JSON.stringify({ parse: 0, url: '', header: {} });
}

async function search(wd, quick, pg) {
    await ensureInit();
    try {
        let url = `${baseUrl}appSearch?client=babala-android&search=${encodeURIComponent(wd)}&app_token=abcSEARCH-2025`;
        let json = await requestJson(url);
        if (!json || json.status !== 0) throw new Error();
        let bookData = json.data?.bookData;
        let videos = [];
        if (Array.isArray(bookData)) {
            for (let item of bookData) {
                videos.push({
                    vod_id: item.id ? item.id.toString() : '',
                    vod_name: item.bookTitle || '',
                    vod_pic: item.bookImage || '',
                    vod_remarks: item.bookAnchor || ''
                });
            }
        }
        return JSON.stringify({
            page: 1,
            pagecount: 100,
            limit: 20,
            total: 2000,
            list: videos
        });
    } catch (e) {
        return JSON.stringify({ list: [] });
    }
}

export function __jsEvalReturn() {
    return { init, home, category, detail, play, search };
}