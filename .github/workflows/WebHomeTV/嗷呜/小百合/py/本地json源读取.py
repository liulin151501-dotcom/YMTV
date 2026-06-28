# -*- coding: utf-8 -*-
import os, base64, gc, re, json, time
from base.spider import Spider

class Spider(Spider):
    # ==========================================================================
    # 💎 【1. 核心导航配置区】
    # ==========================================================================
    # ⚙️ [门阀1.2：频道分页开关]：控制首页频道列表每页显示的条数
    CHANNEL_PAGE_SIZE = 2000  # 👈 修改这个数值，即可控制频道分页的大小 (默认2000条一页)
    
    # --------------------------------------------------------------------------

    def __init__(self):
        super().__init__()
        self.inited = False
        self.cache = {"categories": [], "file_index": {}} # 存储分类信息与文件索引映射
        self.info_cache = {} # 预留信息缓存容器
        self.line_limit = 2000    # ⚙️ [默认阈值]：JSON分页的基础条数，影响二级菜单分段
        self.adaptive_tag = "" # 性能档位标签

    def getName(self):
        # 返回插件名称，包含版本号与性能档位，方便在软件内追踪状态
        return f"LocalJSON_Turbo_v44_Direct_{self.adaptive_tag}"

    # ==========================================================================
    # ⚙️ 【性能补偿系统】 - 自动检测设备硬件环境，动态调整解析压力
    # ==========================================================================
    def _get_adaptive_config(self):
        """ 性能自适应逻辑：通过读取系统内存信息，决定分页的大小，防止低端设备OOM崩溃 """
        total_kb = 0
        try:
            if os.path.exists('/proc/meminfo'):
                with open('/proc/meminfo', 'r') as f:
                    content = f.read()
                    # 正则提取系统总物理内存大小
                    m = re.search(r'MemTotal:\s+(\d+)', content)
                    if m: total_kb = int(m.group(1))
        except: pass
        
        # 默认兜底内存设定为2G
        if total_kb == 0: total_kb = 2097152 
        
        # 档位划分：3G以下为Eco(节能)，12G以下为Balance(均衡)，以上为Ultra(极致)
        if total_kb <= 3145728: return {"limit": 2000, "tag": "Eco"}
        elif total_kb < 12582912: return {"limit": 5000, "tag": "Balance"}
        else: return {"limit": 10000, "tag": "Ultra"}

    def _format_size(self, size_bytes):
        """ 格式化文件大小显示：将字节单位转换为更直观的K或M """
        if size_bytes < 1024: return f"{int(size_bytes)}B"
        if size_bytes < 1048576: return f"{int(size_bytes/1024)}K"  
        return f"{size_bytes/1048576:.1f}M"

    # ==========================================================================
    # 📂 【核心初始化引擎】 - 处理全路径深度扫描、自动归类与分段处理
    # ==========================================================================
    def init(self, extend):
        """ 插件启动入口：负责扫描指定目录下的所有JSON文件并生成首页频道 """
        if self.inited: return
        config = self._get_adaptive_config()
        self.line_limit = config["limit"]
        self.adaptive_tag = config["tag"]

        all_json_files = []
        # 🎯 修改点：记录每个文件的存储类型
        file_storage_info = {} 

        # 1. 设置扫描任务列表，包含是否为外置存储的标记
        scan_tasks = [{"root": "/storage/emulated/0/bh", "is_ext": False}]
        
        # 尝试扫描外部存储设备（如SD卡、U盘）中的 bh 目录
        try:
            if os.path.exists("/storage"):
                for s in os.listdir("/storage"):
                    if s not in ["self", "emulated", "knox", "sdcard0", "runtime"]:
                        ext_path = os.path.join("/storage", s, "bh")
                        if os.path.isdir(ext_path): 
                            scan_tasks.append({"root": ext_path, "is_ext": True})
        except: pass
        
        # 优先级：如果提供了 extend 路径，则将其作为扫描的第一优先级 (暂定为外置显示)
        if extend and os.path.isdir(extend): 
            scan_tasks.insert(0, {"root": extend, "is_ext": True})

        # 深度递归扫描
        for task in scan_tasks:
            path = task["root"]
            if not os.path.isdir(path): continue
            for root, _, files in os.walk(path):
                for name in files:
                    if name.lower().endswith('.json'):
                        f_path = os.path.join(root, name)
                        if f_path not in all_json_files: 
                            all_json_files.append(f_path)
                            file_storage_info[f_path] = task["is_ext"]

        all_raw_cats, final_index = [], {}
        folder_groups = {} # 用于将小文件按文件夹名称进行归类
        sorted_files = sorted(all_json_files)
        
        for f_path in sorted_files:
            try:
                sz_raw = os.path.getsize(f_path)
                f_size_mb = sz_raw / 1048576
                is_ext = file_storage_info.get(f_path, False)
                star = " ☆" if is_ext else "" # 🎯 [关键动作]：补全外存星号标识
                
                # 读取文件头部样本进行条数预估
                with open(f_path, 'rb') as f_cnt:
                    sample = f_cnt.read(1024*512)
                    c_sample = sample.count(b'"play_url"') if b'"play_url"' in sample else sample.count(b'"vod_play_url"')
                    count = int((c_sample / len(sample)) * sz_raw) if len(sample) > 0 else 0
                    if count == 0 and sz_raw > 0: count = 1
                
                f_info = f"({self._format_size(sz_raw)}|{count}条)"
                
                # 逻辑分支：5M以上大文件单独作为一个频道展示
                if f_size_mb >= 5:
                    f_base = os.path.basename(f_path).rsplit('.', 1)[0]
                    t_name = f"{f_base} {f_info}{star}"
                    tid = base64.b64encode(f"SINGLE|{f_path}".encode()).decode()
                    all_raw_cats.append({"type_id": tid, "type_name": t_name})
                    final_index[tid] = [f_path]
                else:
                    folder_name = os.path.basename(os.path.dirname(f_path))
                    if folder_name == "bh" or not folder_name: folder_name = "根目录"
                    group_key = f"📁{folder_name}{star}"
                    if group_key not in folder_groups: folder_groups[group_key] = []
                    folder_groups[group_key].append(f_path)
            except: continue

        # 🎯 [核心修改]：应用 CHANNEL_PAGE_SIZE 门阀处理文件夹分组
        p_size = self.CHANNEL_PAGE_SIZE if self.CHANNEL_PAGE_SIZE > 0 else 30
        for g_name, g_files in folder_groups.items():
            for i in range(0, len(g_files), p_size):
                chunk = g_files[i : i + p_size]
                page_num = (i // p_size) + 1
                suffix = f"-P{page_num}" if len(g_files) > p_size else ""
                final_t_name = f"{g_name}{suffix}"
                tid = base64.b64encode(final_t_name.encode()).decode()
                all_raw_cats.append({"type_id": tid, "type_name": final_t_name})
                final_index[tid] = chunk

        self.cache["categories"] = all_raw_cats
        self.cache["file_index"] = final_index
        self.cache["all_files"] = sorted_files
        self.inited = True
        gc.collect() 

    def homeContent(self, filter):
        """ 返回首页频道列表 """
        return {"class": self.cache["categories"]}

    # ==========================================================================
    # 🎯 [二级菜单展示] - 根据文件内容，自动选择“直接列出视频”或“文件分段”模式
    # ==========================================================================
    def categoryContent(self, tid, pg, filter, ext):
        """ 处理点击分类后的内容展示：核心兼容逻辑所在 """
        if str(pg) != "1": return {"list": []}
        target_files = self.cache["file_index"].get(tid, [])
        v_list = []
        for f_path in target_files:
            if not os.path.exists(f_path): continue
            f_base = os.path.basename(f_path).rsplit('.', 1)[0]
            try:
                # 🚀 [新格式解析动作]：针对标准 JSON 对象（Simplified）
                with open(f_path, 'r', encoding='utf-8', errors='ignore') as f_read:
                    content = f_read.read()
                    if '"videos"' in content: 
                        data = json.loads(content)
                        for item in data.get('videos', []):
                            v_name = item.get('title', '未知')
                            v_id = base64.b64encode(f"NEW|{f_path}|{v_name}".encode()).decode()
                            v_list.append({
                                "vod_id": v_id, 
                                "vod_name": f"[{f_base}] {v_name}", 
                                "vod_pic": item.get('cover', 'https://img.icons8.com/color/200/json--v1.png'),
                                "vod_remarks": item.get('type', '新格式')
                            })
                        continue 

                # 🚀 [旧格式处理逻辑]：保留原有的基于文件分段的虚拟列表显示
                sz = os.stat(f_path).st_size
                with open(f_path, 'rb') as f:
                    sample = f.read(1024*1024) 
                    c_sample = sample.count(b'"play_url"') if b'"play_url"' in sample else sample.count(b'"vod_play_url"')
                    count = int((c_sample / len(sample)) * sz) if len(sample) > 0 else 0
                parts = (count // self.line_limit) + 1 if count > 0 else 1
                for i in range(parts):
                    v_id = base64.b64encode(f"P|{i}|{f_path}".encode()).decode()
                    v_list.append({
                        "vod_id": v_id, 
                        "vod_name": f"{f_base}({i+1}/{parts})" if parts > 1 else f_base,
                        "vod_pic": "https://img.icons8.com/color/200/json--v1.png",
                        "vod_remarks": f"{self._format_size(sz)} 约{count}条"
                    })
            except: continue
        return {"list": v_list}

    # ==========================================================================
    # 🎯 [详情页解析] - 对新旧两种 ID 模式进行全自动识别与数据提取
    # ==========================================================================
    def detailContent(self, array):
        """ 处理详情页请求：负责提取播放地址、线路名、简介等核心数据 """
        try:
            raw = base64.b64decode(array[0]).decode()
            
            if raw.startswith("NEW|"):
                _, f_path, target_title = raw.split('|', 2)
                with open(f_path, 'r', encoding='utf-8', errors='ignore') as f:
                    data = json.loads(f.read())
                    for item in data.get('videos', []):
                        if item.get('title') == target_title:
                            return {"list": [{
                                "vod_name": target_title,
                                "vod_pic": item.get('cover', ''),
                                "vod_play_from": item.get('source', '本地源'),
                                "vod_play_url": item.get('play_url', ''),
                                "vod_content": item.get('description', f"路径: {f_path}")
                            }]}
                return {"list": []}

            parts = raw.split('|', 2)
            p_idx, f_path = int(parts[1]), parts[2]
            with open(f_path, 'rb') as f:
                pattern = re.compile(rb'\{[^{}]*"(?:vod_name|title)"\s*:\s*"([^"]+)"[^{}]*"(?:vod_play_url|play_url)"\s*:\s*"([^"]+)"[^{}]*\}')
                play_urls, found, skip = [], 0, p_idx * self.line_limit
                head = f.read(512*1024)
                enc = 'utf-8'
                for e in ['utf-8', 'gb18030']:
                    try: head.decode(e); enc = e; break
                    except: pass
                
                play_from = "本地线路"
                m_f = re.search(rb'"vod_play_from"\s*:\s*"([^"]+)"', head)
                if m_f: play_from = m_f.group(1).decode(enc, 'ignore')
                
                f.seek(0)
                overlap = b""
                while True:
                    chunk = f.read(1024 * 1024 * 4) 
                    if not chunk and not overlap: break
                    current_data = overlap + chunk
                    matches = pattern.findall(current_data)
                    for m in matches:
                        found += 1
                        if found <= skip: continue
                        name = m[0].decode(enc, 'ignore').replace('$', '')
                        url = m[1].decode(enc, 'ignore')
                        play_urls.append(f"{name}${url}")
                        if len(play_urls) >= self.line_limit: break
                    if len(play_urls) >= self.line_limit or not chunk: break
                    overlap = current_data[-1024:] 
            
            f_size = self._format_size(os.path.getsize(f_path))
            return {"list": [{
                "vod_name": os.path.basename(f_path).rsplit('.', 1)[0], 
                "vod_play_from": play_from, 
                "vod_play_url": "#".join(play_urls), 
                "vod_content": f"⚡总量:{f_size} | 本段:{len(play_urls)}集 | 路径:{f_path}"
            }]}
        except: return {"list": []}

    def searchContent(self, key, quick):
        """ 本地搜索功能：基于文件名的关键字匹配 """
        res = []
        for f in self.cache.get("all_files", []):
            if key in os.path.basename(f):
                res.append({
                    "vod_id": base64.b64encode(f"P|0|{f}".encode()).decode(), 
                    "vod_name": os.path.basename(f).rsplit('.', 1)[0], 
                    "vod_pic": "https://img.icons8.com/color/200/search--v1.png", 
                    "vod_remarks": "搜索结果"
                })
        return {"list": res}

    def playerContent(self, flag, id, vipFlags):
        """ 最终播放解析 """
        url = id.split('$')[-1] if '$' in id else id
        return {"url": url.strip(), "parse": 0}

    def destroy(self):
        """ 销毁方法：清理缓存并释放内存 """
        gc.collect(); gc.enable(); return "destroy"