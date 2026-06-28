# -*- coding: utf-8 -*-
import os, json, gc, re, base64, threading
from base.spider import Spider

class Spider(Spider):
    # ==========================================================================
    # 💎 【1. 核心导航配置区】 - 导航灵魂，全局过滤的“总闸门”
    # ==========================================================================
    # 🔑 [门阀1：关键字过滤闸]：填入关键字即可实现全场过滤；留空则全场扫描
    SEARCH_KEY = ""       #修改这个关键字，看你想看的
    
    # ⚙️ [门阀1.2：频道分页开关]：控制首页频道列表每页显示的条数
    CHANNEL_PAGE_SIZE = 1000  # 👈 修改这个数值，即可控制频道分页的大小 (默认1000条一页)
    
    # --------------------------------------------------------------------------
    # ⚙️ [门阀1.5：bh 专属配置阀]：支持自定义文件夹名
    bh_FOLDER_NAME = "bh"     # 📂 此处可修改文件夹名称

    # ==========================================================================
    # 🚀 【 bh 文件夹 物理开关 】：👇 下面这一行，删掉前面的 # 号即开启，加上 # 号即屏蔽
     #          self.scan_targets.append((self.bh_FOLDER_NAME, "根目录"))    #用#屏蔽这一行，小百合就不搜索bh文件夹。
    # ==========================================================================

    # ==========================================================================   
    INT_PATH_CONFIG = []        # 预留内置路径配置
    EXT_PATH_CONFIG = []        # 预留外置路径配置

    PROTO_M = b'://'            # 协议指纹识别
    GENRE_M = b',#genre#'       # TXT分类指纹识别
    COMMA = b','                # 分隔符识别

    def __init__(self):
        super().__init__()
        self.inited = False
        self.cache = {"categories": [], "search_data": {}}
        self.info_cache = {}        # ⚡ [高速缓存]：存储文件指纹(mtime/大小/条数)，实现秒开
        self.line_limit = 2000      # ⚙️ [默认阈值]：TXT分页的基础行数2000
        self.adaptive_tag = ""
        # 📂 初始化扫描列表，预设 bhh
        self.scan_targets = [("bhh", "根目录")]  #文件库

    def getName(self):
        return "深度分类_17K备注全量版_样式还原版"

    # ==========================================================================
    # ⚙️ 【2. 性能补偿系统】 - 自动根据设备内存调节“门阀”
    # ==========================================================================
    def _get_adaptive_config(self):
        """ [门阀2：自适应压力阀]：根据系统内存自动调整分页行数，防止低端机崩溃 """
        total_kb = 0
        try:
            with open('/proc/meminfo', 'r') as f:
                m = re.search(r'MemTotal:\s+(\d+)', f.read())
                if m: total_kb = int(m.group(1))
        except: total_kb = 2097152 # 默认2G
        
        # 🟢 动态调节逻辑：自适应内存越大，每页条数越多
        if total_kb <= 3145728: return {"limit": 2000, "tag": "Eco"}  #自适应2000条每页
        elif total_kb < 25165824: return {"limit": 8000, "tag": "Balance"}
        else: return {"limit": 30000, "tag": "Ultra"}

    def _get_file_base_stats(self, f_path):
        """ [门阀3：文件扫描加速阀]：二进制流式预扫，获取文件大小、分类数和总条数 """
        try:
            st = os.stat(f_path)
            if f_path in self.info_cache and self.info_cache[f_path]['mtime'] == st.st_mtime:
                return self.info_cache[f_path]
            
            g_count, l_count, has_genre = 0, 0, False
            with open(f_path, 'rb') as f:
                while True:
                    buf = f.read(512 * 1024)
                    if not buf: break
                    if self.GENRE_M in buf: 
                        g_count += buf.count(self.GENRE_M)
                        has_genre = True
                    l_count += (buf.count(self.PROTO_M) + buf.lower().count(b'.mkv') + buf.lower().count(b'.mp4'))
            
            f_size_str = f"{st.st_size/1048576:.1f}M" if st.st_size >= 1048576 else f"{int(st.st_size/1024)}K"
            data = {'mtime': st.st_mtime, 'rem': f"{f_size_str} {max(1, g_count)}类 {l_count}条", 
                    'count': l_count, 'size_raw': st.st_size, 'has_genre': has_genre, 'size_str': f_size_str}
            self.info_cache[f_path] = data
            return data
        except: return {'rem': "0B 0条", 'count': 0, 'size_raw': 0, 'has_genre': False, 'size_str': "0B"}

    # ==========================================================================
    # 🍲 【3. 四大解析类别】 - 完整缝合，不减代码逻辑
    # ==========================================================================

    def _extract_items(self, data):
        """ 🛡️【万能提取内核】确保不漏掉任何 JSON 异构数据 """
        if isinstance(data, list): return data
        if not isinstance(data, dict): return []
        for key in ["videos", "list", "vod", "data", "items"]:
            if key in data and isinstance(data[key], list): return data[key]
        for val in data.values():
            if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict): return val
        return []

    def _parse_txt_v34(self, fp, kw, is_int):
        """ [类一：TXT 核心解析修复版] """
        items = []
        try:
            f_name = os.path.basename(fp)
            with open(fp, 'rb') as f:
                for line_bytes in f:
                    line = line_bytes.decode('utf-8', errors='ignore').strip()
                    if not line or "#genre#" in line or "," not in line: continue
                    parts = line.split(',')
                    if len(parts) >= 2 and "://" in parts[1]:
                        name, url = parts[0].strip(), parts[1].strip()
                        if kw and (kw.lower() not in name.lower()) and (kw.lower() not in url.lower()):
                            continue
                        v_id = "RAW_TXT|" + base64.b64encode(f"{fp}|{url}|{name}".encode()).decode()
                        pic = "https://img.icons8.com/color/200/txt.png"
                        remark = "TXT"
                        if url.lower().endswith(('.mkv', '.mp4')):
                            pic = "https://img.icons8.com/color/200/video-file.png"
                            remark = "网络媒体"
                        items.append({"vod_id": v_id, "vod_name": name, "vod_pic": pic, "vod_remarks": remark, "vod_play_from": "本地TXT源", "vod_content": f"⚡{name} | 文件名:{f_name} | 路径:{fp}| 档位:{self.adaptive_tag}"})
        except: pass
        return items
  
    def _parse_m3u(self, fp, kw):
        """ [类二：M3U 频道提取] """
        items = []
        try:
            with open(fp, 'rb') as f:
                content = f.read().decode('utf-8', errors='ignore')
                temp_item = {}
                f_path = fp
                for line in content.split('\n'):
                    line = line.strip()
                    if line.startswith("#EXTINF:"):
                        name = line.split(',')[-1].strip()
                        logo = re.search(r'tvg-logo=["\'](.*?)["\']', line)
                        temp_item = {"n": name, "l": logo.group(1) if logo else ""}
                    elif "://" in line and not line.startswith("#"):
                        if not kw or (kw.lower() in temp_item.get("n", "").lower()) or (kw.lower() in line.lower()):
                            v_id = "M3U_URL|" + base64.b64encode(f"{temp_item.get('n','源')}|{temp_item.get('l','')}|{line}|{f_path}".encode()).decode()
                            items.append({"vod_id": v_id, "vod_name": temp_item.get("n", "直播源"), "vod_pic": temp_item.get("l", "") or "https://img.icons8.com/color/200/tv.png", "vod_remarks": "m3u", "vod_play_from": "本地M3U源", "file_type": "m3u"})
                        temp_item = {}
        except: pass
        return items
  
    def _parse_json(self, fp, kw):
        """ [类三：JSON 解析器] """
        items = []
        try:
            f_base = os.path.basename(fp).rsplit('.', 1)[0]
            with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read().strip()
                if not content: return []
                try:
                    data = json.loads(content)
                    source_list = self._extract_items(data)
                    if source_list:
                        for item in source_list:
                            v_name = item.get('vod_name', item.get('title', '未知'))
                            v_id_orig = str(item.get('vod_id', ''))
                            if not kw or kw.lower() in v_name.lower():
                                pic = item.get('vod_pic', item.get('cover', item.get('pic', item.get('img', ''))))
                                if not pic: pic = "https://img.icons8.com/color/200/json--v1.png"
                                v_id_data = f"JS_V2|{fp}|{v_id_orig if v_id_orig else v_name}"
                                item["vod_id"] = "V_JSON_V2|" + base64.b64encode(v_id_data.encode()).decode()
                                item["vod_name"] = f"[{f_base}] {v_name}"
                                item["vod_pic"] = pic
                                item["vod_remarks"] = "json"
                                item["file_type"] = "json"
                                items.append(item)
                        if items: return items
                except: pass

            sz = os.stat(fp).st_size
            if sz > 0:
                with open(fp, 'rb') as f_b:
                    sample = f_b.read(1024*1024)
                    c_sample = sample.count(b'"play_url"') + sample.count(b'"vod_play_url"')
                    count = int((c_sample / len(sample)) * sz) if len(sample) > 0 else 0
                parts = (count // self.line_limit) + 1 if count > 0 else 1
                for i in range(parts):
                    v_id_p = base64.b64encode(f"P|{i}|{fp}".encode()).decode()
                    items.append({
                        "vod_id": v_id_p, 
                        "vod_name": f"{f_base}({i+1}/{parts})" if parts > 1 else f_base, 
                        "vod_pic": "https://img.icons8.com/color/200/json--v1.png", 
                        "vod_remarks": "json_part"
                    })
        except: pass
        return items
  
    def _parse_media(self, fp, kw):
        """ [类四：本地媒体] """
        items = []
        name = os.path.basename(fp)
        if not kw or kw.lower() in name.lower():
            v_id = "MEDIA_URL|" + base64.b64encode(fp.encode()).decode()
            items.append({"vod_id": v_id, "vod_name": name, "vod_pic": "https://img.icons8.com/color/200/video-file.png", "vod_remarks": "直连", "vod_play_from": "本地TXT源", "file_type": "media"})
        return items

    def detailContent(self, array):
        v_id_raw = str(array[0])
        if v_id_raw.startswith("RAW_TXT|"):
            try:
                raw = base64.b64decode(v_id_raw.split("|")[1]).decode()
                f_path, url, name = raw.split('|', 2)
                content_str = f"⚡【片名】: {name} | 【路径】: {f_path} | 【链接】: {url} | 【文件名】: {os.path.basename(f_path)}| 档位:{self.adaptive_tag}"
                return {"list": [{"vod_name": name, "vod_play_from": "本地TXT源", "vod_play_url": f"全屏播放${url}", "vod_remarks": f"源自:{os.path.basename(f_path)}", "vod_content": content_str}]}
            except: pass
        elif v_id_raw.startswith("M3U_URL|"):
            try:
                raw_data = base64.b64decode(v_id_raw.split("|")[1]).decode()
                name, logo, url, f_path = raw_data.split('|', 3)
                content_m3u = f"⚡片名: {name} | 路径: {f_path} | 提示：M3U直连播放 | 档位:{self.adaptive_tag}"
                return {"list": [{"vod_name": name, "vod_pic": logo or "https://img.icons8.com/color/200/tv.png", "vod_play_from": "本地M3U源", "vod_play_url": f"全屏播放${url}", "vod_remarks": "m3u", "vod_content": content_m3u}]}
            except: pass
        elif v_id_raw.startswith("V_JSON_V2|"):
            try:
                raw = base64.b64decode(v_id_raw.split("|")[1]).decode()
                _, f_path, target_id = raw.split('|', 2)
                with open(f_path, 'r', encoding='utf-8', errors='ignore') as f:
                    data = json.loads(f.read())
                    source_list = self._extract_items(data)
                    for item in source_list:
                        v_name = item.get('vod_name', item.get('title', ''))
                        v_id_orig = str(item.get('vod_id', ''))
                        if v_id_orig == target_id or v_name == target_id:
                            item["vod_content"] = item.get("vod_content", "") + f" | 【路径】: {f_path} | 档位:{self.adaptive_tag}"
                            if "vod_play_from" not in item: item["vod_play_from"] = "本地解析"
                            if "vod_play_url" not in item: item["vod_play_url"] = item.get("play_url", "")
                            return {"list": [item]}
            except: pass
        try:
            raw = base64.b64decode(v_id_raw).decode()
            if raw.startswith("P|"):
                parts = raw.split('|', 2)
                p_idx, f_path = int(parts[1]), parts[2]
                with open(f_path, 'rb') as f:
                    pattern = re.compile(rb'\{[^{}]*"(?:vod_name|title)"\s*:\s*"([^"]+)"[^{}]*"(?:vod_play_url|play_url)"\s*:\s*"([^"]+)"[^{}]*\}')
                    play_urls, found, skip = [], 0, p_idx * self.line_limit
                    f.seek(0); overlap = b""
                    while True:
                        chunk = f.read(1024 * 1024 * 4) 
                        if not chunk and not overlap: break
                        current_data = overlap + chunk
                        matches = pattern.findall(current_data)
                        for m in matches:
                            found += 1
                            if found <= skip: continue
                            name = m[0].decode('utf-8', 'ignore').replace('$', '')
                            url = m[1].decode('utf-8', 'ignore')
                            play_urls.append(f"{name}${url}")
                            if len(play_urls) >= self.line_limit: break
                        if len(play_urls) >= self.line_limit or not chunk: break
                        overlap = current_data[-1024:]
                return {"list": [{"vod_name": os.path.basename(f_path), "vod_play_from": "分段提取", "vod_play_url": "#".join(play_urls), "vod_content": f"⚡分段模式读取中 | 路径:{f_path}"}]}
        except: pass
        if v_id_raw.startswith("MEDIA_URL|"):
            path = base64.b64decode(v_id_raw.split("|")[1]).decode()
            return {"list": [{"vod_name": os.path.basename(path), "vod_play_from": "本地媒体", "vod_play_url": f"全屏播放${path}"}]}
        return {"list": []}

    # ==========================================================================
    # 📂 【5. 初始化与扫描引擎】 - 🎯 【核心修改点：还原分类样式】
    # ==========================================================================
    def init(self, extend):
        if self.inited: return
        gc.disable()
        conf = self._get_adaptive_config()
        self.line_limit, self.adaptive_tag = conf["limit"], conf["tag"]
        kw, kw_b = self.SEARCH_KEY.strip(), self.SEARCH_KEY.strip().lower().encode('utf-8')
        
        raw_roots = ["/storage/emulated/0", "/sdcard"]
        try:
            if os.path.exists("/storage"):
                for d in os.listdir("/storage"):
                    p = os.path.join("/storage", d)
                    if os.path.isdir(p) and d not in ["self", "emulated", "knox", "sdcard", "runtime", "container"]:
                        raw_roots.append(p)
        except: pass

        all_results_list, scanned_paths = [], set()
        for r in raw_roots:
            if not os.path.exists(r): continue
            real_root = os.path.realpath(r); scanned_paths.add(real_root)
            is_int = "emulated" in real_root or "sdcard" in real_root
            for folder_key, display_label in self.scan_targets:
                target_root_path = os.path.join(r, folder_key)
                if os.path.isdir(target_root_path):
                    r_items = self._scan_folder_simple(target_root_path, kw, kw_b, is_int)
                    if r_items: all_results_list.append({"name": display_label, "items": r_items, "weight": 100, "path": target_root_path, "is_int": is_int})
                    try:
                        with os.scandir(target_root_path) as it:
                            for entry in it:
                                if entry.is_dir():
                                    s_items = self._scan_folder_simple(entry.path, kw, kw_b, is_int)
                                    if s_items: all_results_list.append({"name": entry.name, "items": s_items, "weight": 2, "path": entry.path, "is_int": is_int})
                                    try:
                                        with os.scandir(entry.path) as sub_it:
                                            for se in sub_it:
                                                if se.is_dir():
                                                    n_items = self._scan_folder_simple(se.path, kw, kw_b, is_int)
                                                    if n_items: all_results_list.append({"name": f"{entry.name}/{se.name}*", "items": n_items, "weight": 5, "path": se.path, "is_int": is_int})
                                    except: pass
                    except: pass

        all_results_list.sort(key=lambda x: (x['weight'], x['path']))
        final_cats, final_data = [], {}
        
        # 🟢 获取频道分页门阀数值
        p_size = self.CHANNEL_PAGE_SIZE if self.CHANNEL_PAGE_SIZE > 0 else 1000

        for res_obj in all_results_list:
            items = res_obj["items"]
            
            # 🎯 【关键动作】：去掉 [💾内/外] 图标前缀，还原为原始分类样式
            total = len(items)
            total_pages = (total + p_size - 1) // p_size    
            
            for i in range(total_pages):
                tid = base64.b64encode(f"{res_obj['path']}|{i+1}".encode()).decode()
                # ✍️ 修改处：直接构建分类名，不再添加 storage_valve 变量
                cat_name = f"{res_obj['name']}({total})[{i+1}/{total_pages}]"
                final_cats.append({"type_id": tid, "type_name": cat_name})
                # ✍️ 根据分页开关数值进行切片
                final_data[tid] = items[i*p_size : (i+1)*p_size]

        self.cache["categories"] = final_cats if final_cats else [{"type_id": "NONE", "type_name": "❌未找到任何文件"}]
        self.cache["search_data"] = final_data
        self.inited = True
        gc.collect()

    def _scan_folder_simple(self, folder_path, kw, kw_b, is_int):
        res = []
        try:
            with os.scandir(folder_path) as it:
                for entry in it:
                    if entry.is_file():
                        ext = entry.name.lower()
                        if ext.endswith('.txt'): res.extend(self._parse_txt_v34(entry.path, kw, is_int))
                        elif ext.endswith(('.m3u', '.m3u8')): res.extend(self._parse_m3u(entry.path, kw))
                        elif ext.endswith('.json'): res.extend(self._parse_json(entry.path, kw))
                        elif ext.endswith(('.mp4', '.mkv')): res.extend(self._parse_media(entry.path, kw))
        except: pass
        return res

    def homeContent(self, filter): return {"class": self.cache["categories"]}
    def categoryContent(self, tid, pg, filter, ext):
        res = self.cache["search_data"].get(tid, [])
        return {"page": 1, "pagecount": 1, "limit": len(res), "total": len(res), "list": res}
    def playerContent(self, flag, id, vipFlags):
        url = id.split('$')[-1] if '$' in id else id
        return {"url": url.strip(), "header": {"User-Agent": "okhttp/3.12.0"}, "parse": 0}
    def destroy(self): gc.collect(); return "destroy"