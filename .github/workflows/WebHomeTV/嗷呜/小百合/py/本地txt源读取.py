# -*- coding: utf-8 -*-
import os, base64, gc, re
from base.spider import Spider

class Spider(Spider):
    # ==========================================================================
    # 💎 【1. 核心导航配置区】
    # ==========================================================================
    # ⚙️ [门阀1.2：频道分页开关]：控制首页频道列表每页显示的条数
    CHANNEL_PAGE_SIZE = 2000  # 👈 修改这个数值，即可控制频道分页的大小 (默认2000条一页)
    
    # --------------------------------------------------------------------------

    # 🔍 [指纹定义]：用于二进制流扫描时快速定位协议、分类和分隔符
    PROTO_M = b'://'
    GENRE_M = b',#genre#'
    COMMA = b','

    def __init__(self):
        super().__init__()
        self.inited = False
        # cache["categories"]: 存储首页展示的频道对象列表
        # cache["file_index"]: 映射频道 ID 到对应的文件路径列表
        self.cache = {"categories": [], "file_index": {}}
        self.info_cache = {} # 文件指纹缓存，记录 mtime 以避免重复扫描硬盘
        self.all_files_for_search = [] # 扁平化的文件路径列表，供搜索引擎使用
        self.line_limit = 2000 # 单页显示的条数上限，由自适应系统动态修改
        self.adaptive_tag = "" # 性能标签，用于 getName 辨识当前压感状态

    def getName(self):
        # 动态返回插件名称，方便在 UI 界面查看当前处于哪种内存压力档位
        return f"LocalTXT_DeepScan_v41_FolderMix_{self.adaptive_tag}"

    # ==========================================================================
    # ⚙️ 【门阀1：自适应压感闸门】 - 根据手机实际物理内存，动态调整解析强度
    # ==========================================================================
    def _get_adaptive_config(self):
        """ 性能自适应：根据系统 MemTotal 自动决定分段解析的颗粒度，防止低端机 OOM """
        total_kb = 0
        try:
            with open('/proc/meminfo', 'r') as f:
                content = f.read()
                m = re.search(r'MemTotal:\s+(\d+)', content)
                if m: total_kb = int(m.group(1))
        except: total_kb = 2097152 
        
        if total_kb <= 3145728: 
            return {"limit": 2000, "tag": "Eco"}
        elif total_kb < 25165824: 
            return {"limit": 8000, "tag": "Balance"}
        else: 
            return {"limit": 30000, "tag": "Ultra"}

    def _format_size(self, size_bytes):
        """ 辅助工具：将字节数值转化为人类可读的 K/M 字符串 """
        if size_bytes < 1024: return f"{int(size_bytes)}B"
        if size_bytes < 1048576: return f"{int(size_bytes/1024)}K"  
        return f"{size_bytes/1048576:.1f}M"

    # ==========================================================================
    # 🚀 【门阀2：二进制高速预扫引擎】 - 秒开万行文件的核心
    # ==========================================================================
    def _get_file_base_stats(self, f_path):
        """ 指纹扫描器：通过探测协议头频次预估内容总量 """
        try:
            st = os.stat(f_path)
            if f_path in self.info_cache and self.info_cache[f_path]['mtime'] == st.st_mtime:
                return self.info_cache[f_path]
            
            g_count, l_count = 0, 0
            has_genre = False
            with open(f_path, 'rb') as f:
                while True:
                    buf = f.read(1024 * 1024)
                    if not buf: break
                    if self.GENRE_M in buf:
                        has_genre = True
                        g_count += buf.count(self.GENRE_M)
                    l_count += buf.count(self.PROTO_M)
            
            f_size_str = self._format_size(st.st_size)
            data = {
                'mtime': st.st_mtime, 
                'rem': f"{f_size_str} {max(1, g_count)}类 {l_count}条", 
                'count': l_count, 
                'size_str': f_size_str,
                'size_raw': st.st_size, 
                'has_genre': has_genre 
            }
            self.info_cache[f_path] = data
            return data
        except: return {'rem': "0B 0类 0条", 'count': 0, 'size_str': "0B", 'size_raw': 0, 'has_genre': False}

    # ==========================================================================
    # 📂 【关键部位：全量路径扫描引擎】 - 注入外存储标识逻辑
    # ==========================================================================
    def init(self, extend):
        """ 首页初始化：遍历全盘路径，补全外存星号标识 """
        if self.inited: return
        config = self._get_adaptive_config()
        self.line_limit = config["limit"]
        self.adaptive_tag = config["tag"]

        all_txt_files = []
        # 🎯 [新增] 存储类型索引，用于标记文件是否属于外置挂载点
        file_storage_info = {} 
        
        # 扫描列表预设 (root: 路径, is_ext: 是否外置)
        scan_tasks = [{"root": "/storage/emulated/0/bh", "is_ext": False}]
        
        try:
            if os.path.exists("/storage"):
                for s in os.listdir("/storage"):
                    if s not in ["self", "emulated", "knox", "sdcard0"]:
                        p = os.path.join("/storage", s, "bh")
                        if os.path.isdir(p): scan_tasks.append({"root": p, "is_ext": True})
        except: pass

        if extend and os.path.isdir(extend):
            scan_tasks.insert(0, {"root": extend, "is_ext": True})

        # 全深度扫描
        for task in scan_tasks:
            b_path = task["root"]
            if not os.path.exists(b_path): continue
            for root, _, files in os.walk(b_path):
                for name in files:
                    if name.lower().endswith('.txt'):
                        f_path = os.path.join(root, name)
                        if f_path not in all_txt_files: 
                            all_txt_files.append(f_path)
                            file_storage_info[f_path] = task["is_ext"]
        
        self.all_files_for_search = all_txt_files
        all_raw_cats, final_index = [], {}
        folder_groups = {} 
        sorted_files = sorted(all_txt_files) 

        for f_path in sorted_files:
            try:
                sz_raw = os.path.getsize(f_path)
                f_size_mb = sz_raw / 1048576 
                
                # 🎯 [关键部位]：根据存储类型决定是否添加星号 ☆
                is_ext = file_storage_info.get(f_path, False)
                star_tag = " ☆" if is_ext else ""
                
                info = self._get_file_base_stats(f_path)
                f_info = f"({info['rem']})"
                
                if f_size_mb >= 5:
                    f_base = os.path.basename(f_path).rsplit('.', 1)[0]
                    t_name = f"{f_base} {f_info}{star_tag}"
                    tid = base64.b64encode(f"SINGLE|{f_path}".encode()).decode()
                    all_raw_cats.append({"type_id": tid, "type_name": t_name})
                    final_index[tid] = [f_path]
                else:
                    folder_name = os.path.basename(os.path.dirname(f_path))
                    if folder_name == "bh" or not folder_name: folder_name = "根目录"
                    # 🎯 小文件文件夹模式同样应用外存标识
                    group_key = f"📁{folder_name}{star_tag}"
                    if group_key not in folder_groups: folder_groups[group_key] = []
                    folder_groups[group_key].append(f_path)
            except: continue

        # ✨ [聚合处理]：应用 CHANNEL_PAGE_SIZE 门阀控制分页
        p_limit = self.CHANNEL_PAGE_SIZE if self.CHANNEL_PAGE_SIZE > 0 else 30
        for g_name, g_files in folder_groups.items():
            for i in range(0, len(g_files), p_limit):
                chunk = g_files[i : i + p_limit]
                page_idx = (i // p_limit) + 1
                suffix = f"-P{page_idx}" if len(g_files) > p_limit else ""
                final_t_name = f"{g_name}{suffix}"
                tid = base64.b64encode(final_t_name.encode()).decode()
                all_raw_cats.append({"type_id": tid, "type_name": final_t_name})
                final_index[tid] = chunk

        self.cache["categories"] = all_raw_cats 
        self.cache["file_index"] = final_index 
        self.inited = True
        gc.collect() 

    def homeContent(self, filter): 
        return {"class": self.cache["categories"]}

    # ==========================================================================
    # 🍲 【列表填充逻辑】 - 保持原有 500K 稳压阀不动
    # ==========================================================================
    def categoryContent(self, tid, pg, filter, ext):
        if str(pg) != "1": return {"list": []}
        target_files = self.cache["file_index"].get(tid, [])
        v_list = []
        for f_path in target_files:
            if not os.path.exists(f_path): continue
            f_base = os.path.basename(f_path)[:-4] 
            info = self._get_file_base_stats(f_path)
            
            # 🛡️ 原有稳压阀逻辑
            parts = 1 if (info['size_raw'] < 500 * 1024 and info['has_genre']) else ((info['count'] // self.line_limit) + 1 if info['count'] > 0 else 1)
            
            for i in range(parts):
                v_id = base64.b64encode(f"P|{i}|{f_path}".encode()).decode()
                v_list.append({
                    "vod_id": v_id, 
                    "vod_name": f"{f_base}({i+1}/{parts})" if parts > 1 else f_base,
                    "vod_pic": "https://img.icons8.com/color/200/txt.png", 
                    "vod_remarks": info['rem'] 
                })
        return {"list": v_list}

    # ==========================================================================
    # 📺 【详情页解析系统】 - 保持原有解析强度与编码识别逻辑
    # ==========================================================================
    def detailContent(self, array):
        try:
            raw = base64.b64decode(array[0]).decode()
            parts_raw = raw.split('|', 2)
            if len(parts_raw) < 3: return {"list": []}
            p_idx, f_path = int(parts_raw[1]), parts_raw[2]
            info = self._get_file_base_stats(f_path)
            
            enc = 'utf-8'
            with open(f_path, 'rb') as f:
                head = f.read(2048)
                for e in ['utf-8', 'gb18030', 'cp936']:
                    try: head.decode(e); enc = e; break
                    except: pass

            froms, urls, curr_g = [], [], "未分类" 
            genre_dict = {curr_g: []}; genre_order = [curr_g]
            
            parts = 1 if (info['size_raw'] < 500 * 1024 and info['has_genre']) else ((info['count'] // self.line_limit) + 1 if info['count'] > 0 else 1)
            skip, found, this_part_count = p_idx * self.line_limit, 0, 0
            
            with open(f_path, 'rb') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith(b'#'): continue 
                    
                    if self.GENRE_M in line:
                        curr_g = line.split(b',')[0].decode(enc, 'ignore').strip()
                        if curr_g not in genre_dict: genre_dict[curr_g] = []; genre_order.append(curr_g)
                    elif self.PROTO_M in line and self.COMMA in line:
                        found += 1
                        if parts > 1 and found <= skip: continue
                        
                        this_part_count += 1
                        if curr_g not in genre_dict: genre_dict[curr_g] = []; genre_order.append(curr_g)
                        name, _, url = line.decode(enc, 'ignore').partition(',')
                        genre_dict[curr_g].append(f"{name.strip()}${url.strip()}")
                        
                        if parts > 1 and found >= (skip + self.line_limit): break

            for g in genre_order:
                if genre_dict[g]:
                    froms.append(g); urls.append("#".join(genre_dict[g]))

            content = f"⚡总量:{info['size_str']} {info['count']}条 | 本段:{p_idx+1}/{parts}集 {this_part_count}条 | 路径:{f_path} | 档位:{self.adaptive_tag}"
            return {"list": [{
                "vod_name": os.path.basename(f_path)[:-4], 
                "vod_play_from": "$$$".join(froms), 
                "vod_play_url": "$$$".join(urls), 
                "vod_content": content
            }]}
        except: return {"list": []}

    def searchContent(self, key, quick):
        res = []
        for f in self.all_files_for_search:
            if key in os.path.basename(f):
                info = self._get_file_base_stats(f)
                res.append({
                    "vod_id": base64.b64encode(f"P|0|{f}".encode()).decode(),
                    "vod_name": os.path.basename(f)[:-4],
                    "vod_pic": "https://img.icons8.com/color/200/search--v1.png",
                    "vod_remarks": info['rem']
                })
        return {"list": res}

    def playerContent(self, flag, id, vipFlags): 
        return {"url": id, "parse": 0}