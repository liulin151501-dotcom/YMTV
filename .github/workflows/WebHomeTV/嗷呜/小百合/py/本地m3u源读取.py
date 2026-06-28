# -*- coding: utf-8 -*-
import os, base64, gc, re, json
from base.spider import Spider

class Spider(Spider):
    # ==========================================================================
    # 💎 【1. 核心导航配置区】
    # ==========================================================================
    # ⚙️ [门阀1.2：频道分页开关]：控制首页频道列表每页显示的条数
    CHANNEL_PAGE_SIZE = 2000  # 👈 修改这个数值，即可控制频道分页的大小 (默认2000条一页)
    
    # --------------------------------------------------------------------------

    # 定义 M3U 特征常量：协议头、分组标识、逗号分隔符（二进制模式使用）
    PROTO_M = b'://'
    GENRE_M = b',#genre#'
    COMMA = b','

    def __init__(self):
        super().__init__()
        self.inited = False
        # 缓存容器：categories 存放频道列表，file_index 存放频道ID与文件的映射
        self.cache = {"categories": [], "file_index": {}}
        self.info_cache = {} # 文件状态缓存，用于存储文件修改时间、条数等
        # 初始预设，会在 init 中根据 _get_adaptive_config 自动覆盖
        self.line_limit = 2000    
        self.adaptive_tag = "" # 性能标签（Eco/Balance/Ultra）

    def getName(self):
        # 动态返回插件名，包含当前设备的性能档位
        return f"LocalM3U_Turbo_v45_Fixed_{self.adaptive_tag}"

    # --- ⚙️ 核心1：内存自适应补偿系统 - 动态调节分页阈值防止 OOM 闪退 ---
    def _get_adaptive_config(self):
        """ 性能自适应：根据系统 MemTotal 自动决定单页展示的数据条数 """
        total_kb = 0
        try:
            if os.path.exists('/proc/meminfo'):
                with open('/proc/meminfo', 'r') as f:
                    content = f.read()
                    # 正则匹配物理内存总量
                    m = re.search(r'MemTotal:\s+(\d+)', content)
                    if m: total_kb = int(m.group(1))
        except: 
            total_kb = 2097152 # 默认兜底按 2G 内存处理

        # 档位判定逻辑
        if total_kb <= 3145728: 
            return {"limit": 2000, "tag": "Eco"}    # 3G以下低端设备
        elif total_kb < 25165824: 
            return {"limit": 10000, "tag": "Balance"} # 24G以下主流设备
        else: 
            return {"limit": 50000, "tag": "Ultra"}   # 高端旗舰设备

    def _format_size(self, size_bytes):
        """ 格式化文件大小：自动转换字节为 K 或 M 单位 """
        if size_bytes < 1024: return f"{int(size_bytes)}B"
        if size_bytes < 1048576: return f"{int(size_bytes/1024)}K"  
        return f"{size_bytes/1048576:.1f}M"

    # --- ⚙️ 核心2：二进制预扫引擎 - 极速统计 M3U 条数，确保主页不卡顿 ---
    def _get_file_base_stats(self, f_path):
        """ 获取文件统计：利用 mtime 缓存机制，避免重复读取硬盘 """
        try:
            st = os.stat(f_path)
            # 如果缓存命中的文件且未被修改，则直接返回缓存结果
            if f_path in self.info_cache and self.info_cache[f_path]['mtime'] == st.st_mtime:
                return self.info_cache[f_path]
            
            count = 0
            with open(f_path, 'rb') as f:
                while True:
                    buf = f.read(1024 * 1024) # 1MB 缓冲区流式读取
                    if not buf: break
                    # 使用正则匹配 URL 特征（含换行及非注释判断）
                    count += len(re.findall(rb'\n\s*(?!#)\w+://', b'\n' + buf))
            
            f_size_str = self._format_size(st.st_size)
            data = {
                'mtime': st.st_mtime, 
                'rem': f"{f_size_str} {count}条", 
                'count': count, 
                'size_bytes': st.st_size,
                'size_str': f_size_str
            }
            self.info_cache[f_path] = data # 更新缓存
            return data
        except: 
            return {'rem': "0B 0条", 'count': 0, 'size_bytes': 0, 'size_str': "0B"}

    # ==========================================================================
    # 📂 【核心初始化引擎】 - 重构逻辑：大文件独立频道 + 小文件文件夹自动聚合
    # ==========================================================================
    def init(self, extend):
        """ 扫描全路径，建立文件索引并生成首页频道 """
        if self.inited: return
        config = self._get_adaptive_config()
        self.line_limit = config["limit"]
        self.adaptive_tag = config["tag"]

        all_m3u_files = []
        # 🎯 存储路径与挂载属性的映射
        file_storage_map = {} 

        # 1. 设置扫描任务列表，包含是否为外置存储的标记
        scan_tasks = [{"root": "/storage/emulated/0/bh", "is_ext": False}]
        
        # 扫描外部存储（SD卡、U盘）中的 bh 目录
        try:
            if os.path.exists("/storage"):
                for s in os.listdir("/storage"):
                    if s not in ["self", "emulated", "knox", "sdcard0", "runtime"]:
                        ext_path = os.path.join("/storage", s, "bh")
                        if os.path.isdir(ext_path): 
                            scan_tasks.append({"root": ext_path, "is_ext": True})
        except: pass
        
        # 插入用户定义的 extend 扩展路径（标记为外置）
        if extend and os.path.isdir(extend): 
            scan_tasks.insert(0, {"root": extend, "is_ext": True})

        # 🚀 [深度递归扫描]：递归查找目录下所有的 .m3u 和 .m3u8 文件
        for task in scan_tasks:
            path = task["root"]
            if not os.path.isdir(path): continue
            for root, _, files in os.walk(path):
                for name in files:
                    if name.lower().endswith(('.m3u', '.m3u8')):
                        f_path = os.path.join(root, name)
                        if f_path not in all_m3u_files: 
                            all_m3u_files.append(f_path)
                            file_storage_map[f_path] = task["is_ext"]

        # 📊 [关键部位：频道显示生成逻辑]
        all_raw_cats, final_index = [], {}
        folder_groups = {} # 小文件聚合容器
        sorted_files = sorted(all_m3u_files) # 按文件名排序
        
        for f_path in sorted_files:
            try:
                sz_raw = os.path.getsize(f_path)
                f_size_mb = sz_raw / 1048576
                
                # 🎯 [关键动作]：根据挂载属性补全星号☆
                is_ext = file_storage_map.get(f_path, False)
                star = " ☆" if is_ext else ""
                
                # 调用预扫引擎获取文件详情描述
                info = self._get_file_base_stats(f_path)
                f_info = f"({info['rem']})"
                
                # 🎯 [核心判定]：5M以上大文件单独作为一个频道展示
                if f_size_mb >= 5:
                    f_base = os.path.basename(f_path).rsplit('.', 1)[0]
                    t_name = f"{f_base} {f_info}{star}"
                    # Base64编码文件路径作为单一分类ID
                    tid = base64.b64encode(f"SINGLE|{f_path}".encode()).decode()
                    all_raw_cats.append({"type_id": tid, "type_name": t_name})
                    final_index[tid] = [f_path]
                else:
                    # 🎯 [核心判定]：5M以下的小文件，按所在的物理文件夹名称进行归类
                    folder_name = os.path.basename(os.path.dirname(f_path))
                    # 确保 bh 根目录下的文件显示为“根目录”分类
                    if folder_name == "bh" or not folder_name: folder_name = "根目录"
                    group_key = f"📁{folder_name}{star}"
                    if group_key not in folder_groups: folder_groups[group_key] = []
                    folder_groups[group_key].append(f_path)
            except: continue

        # 🎯 [文件夹聚合逻辑]：对归类后的文件进行分组（应用 CHANNEL_PAGE_SIZE 变量）
        p_size = self.CHANNEL_PAGE_SIZE if self.CHANNEL_PAGE_SIZE > 0 else 30
        for g_name, g_files in folder_groups.items():
            for i in range(0, len(g_files), p_size):
                chunk = g_files[i : i + p_size]
                # 若一个目录下文件过多，则自动增加 P1, P2 后缀
                page_num = (i // p_size) + 1
                suffix = f"-P{page_num}" if len(g_files) > p_size else ""
                final_t_name = f"{g_name}{suffix}"
                tid = base64.b64encode(final_t_name.encode()).decode()
                all_raw_cats.append({"type_id": tid, "type_name": final_t_name})
                final_index[tid] = chunk

        # 写入持久化缓存
        self.cache["categories"] = all_raw_cats
        self.cache["file_index"] = final_index
        self.cache["all_files"] = sorted_files
        self.inited = True
        gc.collect() # 执行垃圾回收释放扫描阶段临时开销

    def homeContent(self, filter):
        """ 返回已生成的频道分类列表 """
        return {"class": self.cache["categories"]}

    def categoryContent(self, tid, pg, filter, ext):
        """ 二级菜单：展示该分类下具体文件的分段列表 """
        if str(pg) != "1": return {"list": []}
        target_files = self.cache["file_index"].get(tid, [])
        v_list = []
        for f_path in target_files:
            if not os.path.exists(f_path): continue
            f_base = os.path.basename(f_path).rsplit('.', 1)[0]
            info = self._get_file_base_stats(f_path)
            total = info['count']
            
            # 根据性能阈值（line_limit）计算分页数量
            parts = (total // self.line_limit) + 1 if total > 0 else 1
            for i in range(parts):
                # 构造 ID：前缀P|段索引|路径
                v_id = base64.b64encode(f"P|{i}|{f_path}".encode()).decode()
                v_list.append({
                    "vod_id": v_id,
                    "vod_name": f"{f_base}({i+1}/{parts})" if parts > 1 else f_base,
                    "vod_pic": "https://img.icons8.com/color/200/m3u.png",
                    "vod_remarks": info['rem'] # 显示大小及条数备注
                })
        return {"list": v_list}

    def detailContent(self, array):
        """ 详情页逻辑：负责解析 M3U 内部行，提取标题和播放地址 """
        try:
            raw = base64.b64decode(array[0]).decode()
            parts = raw.split('|', 2)
            if len(parts) < 3: return {"list": []}
            p_idx, f_path = int(parts[1]), parts[2]
            info = self._get_file_base_stats(f_path)
            
            # 🚀 [编码自动探测逻辑]
            enc = 'utf-8'
            with open(f_path, 'rb') as f:
                head = f.read(2048)
                for e in ['utf-8', 'gb18030', 'cp936']:
                    try: head.decode(e); enc = e; break
                    except: pass

            play_urls, temp_name = [], ""
            skip, found = p_idx * self.line_limit, 0 # 计算当前段需要跳过的条数
            
            # 🚀 [流式解析 M3U 内容]
            with open(f_path, 'rb') as f:
                for line in f:
                    try: line_str = line.decode(enc, 'ignore').strip()
                    except: continue
                    if not line_str: continue
                    
                    # 匹配 #EXTINF 标题行
                    if line_str.upper().startswith("#EXTINF"):
                        temp_name = line_str.split(",")[-1].strip()
                        continue

                    # 匹配包含 :// 协议头的 URL 播放地址行
                    if "://" in line_str and not line_str.startswith("#"):
                        found += 1
                        if found <= skip:
                            temp_name = ""
                            continue
                        
                        # 若没提取到标题，则自动分配 CH 编号
                        name = temp_name if temp_name else f"CH{found}"
                        # 格式化存入播放列表，移除可能冲突的 $ 符
                        play_urls.append(f"{name.replace('$', '')}${line_str}")
                        temp_name = "" 
                        # 达到单页上限则退出循环
                        if len(play_urls) >= self.line_limit: break

            total_p = (info['count'] // self.line_limit) + 1
            # 构造详情内容说明文本，包含性能档位调试信息
            content = f"⚡总量:{info['size_str']} {info['count']}条 | 本段:{p_idx+1}/{total_p}集 {len(play_urls)}条 | 路径:{f_path} | 档位:{self.adaptive_tag}"

            return {"list": [{
                "vod_name": os.path.basename(f_path).rsplit('.', 1)[0],
                "vod_play_from": "本地M3U",
                "vod_play_url": "#".join(play_urls), # 聚合播放列表
                "vod_content": content
            }]}
        except: return {"list": []}

    def searchContent(self, key, quick):
        """ 本地搜索：按文件名模糊查找已缓存的所有 M3U 文件 """
        res = []
        for f in self.cache.get("all_files", []):
            if key in os.path.basename(f):
                info = self._get_file_base_stats(f)
                res.append({
                    "vod_id": base64.b64encode(f"P|0|{f}".encode()).decode(),
                    "vod_name": os.path.basename(f).rsplit('.', 1)[0],
                    "vod_pic": "https://img.icons8.com/color/200/search--v1.png",
                    "vod_remarks": info['rem']
                })
        return {"list": res}

    def playerContent(self, flag, id, vipFlags):
        """ 播放器预处理：包含 PingTV 等特定格式的 Base64 自动解密逻辑 """
        url = id.split('$')[-1] if '$' in id else id
        url = url.strip()

        # 🚀 [特殊线路解密逻辑：ost.ping-tv.com 类型]
        payload = url
        if "ost.ping-tv.com/" in url:
            payload = url.split("ost.ping-tv.com/")[-1]

        # 自动补全 Base64 填充并解码提取真实 [ua] 字段地址
        if payload.startswith("eyJ") and len(payload) > 20:
            try:
                missing_padding = len(payload) % 4
                if missing_padding: payload += '=' * (4 - missing_padding)
                decoded_str = base64.b64decode(payload).decode('utf-8', errors='ignore')
                match = re.search(r'"[ua]":"(http[^"]+)"', decoded_str)
                if match: url = match.group(1).replace('\\/', '/')
            except: pass

        # 🚀 [STB 令牌占位符过滤逻辑]
        if "[" in url and "]" in url:
            url = url.replace("[stb_token]", "null").replace("[time_start]", "0")
            url = url.replace("token=&", "token=null&").replace("token=", "token=null")
            url = url.rstrip('?').rstrip('&')

        # 构造标准的浏览器伪装请求头
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
            "Accept": "*/*", "Connection": "keep-alive"
        }
        return {"url": url, "header": headers, "parse": 0}

    def destroy(self):
        """ 销毁方法：清理对象引用并进行内存回收 """
        gc.collect()