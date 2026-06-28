# -*- coding: utf-8 -*-
import os, base64, re, json
from base.spider import Spider

class Spider(Spider):
    # ==========================================
    # 🔍 【关键字设置】
    # ==========================================
    SEARCH_KEY = "淫荡"  # 这里输入你要搜索的关键字
    
    def init(self, extend):
        # 固定根目录
        self.root_dir = "/storage/emulated/0/VodPlus/wwwroot/文件类[文]"
        self.search_results = {
            "json": [],  # JSON文件搜索结果
            "m3u": [],   # M3U文件搜索结果
            "txt": []    # TXT文件搜索结果
        }
        self.total_matches = 0
        self.keyword = ""
        self.inited = True

    def getName(self):
        return "本地文件搜索器"

    def _search_in_file(self, file_path, keyword):
        """在单个文件中搜索关键词"""
        try:
            keyword_lower = keyword.lower()
            file_lower = file_path.lower()
            match_count = 0
            matched_lines = []
            matched_items = []  # 存储匹配的具体条目
            
            # 根据文件类型选择不同的搜索策略
            if file_lower.endswith('.json'):
                # JSON文件搜索vod_name字段
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    try:
                        data = json.load(f)
                        for item in data.get('list', []):
                            vod_name = item.get('vod_name', '')
                            if keyword_lower in vod_name.lower():
                                match_count += 1
                                matched_lines.append(vod_name)
                                matched_items.append(item)
                    except:
                        # 如果不是标准JSON格式，按文本搜索
                        f.seek(0)
                        content = f.read()
                        pattern = r'"vod_name"\s*:\s*"([^"]*' + re.escape(keyword) + r'[^"]*)"[^}]*"vod_play_url"\s*:\s*"([^"]+)"'
                        matches = re.findall(pattern, content, re.IGNORECASE)
                        match_count = len(matches)
                        for name, url in matches:
                            matched_lines.append(name)
                            matched_items.append({"vod_name": name, "vod_play_url": url})
                
                if match_count > 0:
                    return {
                        "path": file_path,
                        "count": match_count,
                        "ext": "json",
                        "matched_lines": matched_lines,
                        "matched_items": matched_items
                    }
            
            elif file_lower.endswith('.m3u'):
                # M3U文件搜索
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    temp_name = ""
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        if line.upper().startswith("#EXTINF"):
                            parts = line.split(',', 1)
                            if len(parts) > 1:
                                temp_name = parts[1].strip()
                        
                        elif "://" in line and not line.startswith("#"):
                            if keyword_lower in line.lower() or (temp_name and keyword_lower in temp_name.lower()):
                                match_count += 1
                                # 获取名称
                                if temp_name:
                                    name = temp_name
                                elif ',' in line:
                                    name = line.split(',', 1)[0].strip()
                                else:
                                    name = f"频道{match_count}"
                                
                                # 获取URL
                                if ',' in line:
                                    url = line.split(',', 1)[1].strip()
                                else:
                                    url = line.strip()
                                
                                matched_lines.append(f"{name} - {url}")
                                matched_items.append({"name": name, "url": url})
                            
                            temp_name = ""
                
                if match_count > 0:
                    return {
                        "path": file_path,
                        "count": match_count,
                        "ext": "m3u",
                        "matched_lines": matched_lines,
                        "matched_items": matched_items
                    }
            
            elif file_lower.endswith('.txt'):
                # TXT文件搜索
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if keyword_lower in line.lower() and '://' in line:
                            match_count += 1
                            matched_lines.append(line)
                            # 解析名称和URL
                            if ',' in line:
                                name, url = line.split(',', 1)
                            else:
                                name = f"频道{match_count}"
                                url = line
                            matched_items.append({"name": name.strip(), "url": url.strip()})
                
                if match_count > 0:
                    return {
                        "path": file_path,
                        "count": match_count,
                        "ext": "txt",
                        "matched_lines": matched_lines,
                        "matched_items": matched_items
                    }
        except:
            pass
        return None

    def homeContent(self, filter):
        """执行搜索并返回有匹配的分类"""
        self.keyword = self.SEARCH_KEY.strip()
        if not self.keyword:
            return {"class": [{"type_id": "0", "type_name": "请输入搜索关键词"}]}
        
        # 重置搜索结果
        self.search_results = {"json": [], "m3u": [], "txt": []}
        self.total_matches = 0
        
        if not os.path.isdir(self.root_dir):
            return {"class": [{"type_id": "0", "type_name": "目录不存在"}]}
        
        # 递归遍历所有文件，搜索关键词
        for root, dirs, files in os.walk(self.root_dir):
            for file in files:
                if file.lower().endswith(('.json', '.m3u', '.txt')):
                    file_path = os.path.join(root, file)
                    result = self._search_in_file(file_path, self.keyword)
                    if result:
                        ext = result['ext']
                        self.search_results[ext].append(result)
                        self.total_matches += result['count']
        
        # 只显示有匹配的分类
        classes = []
        
        # JSON分类 - 只有有匹配时才显示
        if self.search_results["json"]:
            total_json_matches = sum(r['count'] for r in self.search_results["json"])
            classes.append({
                "type_id": "json",
                "type_name": f"📋 JSON文件 · 关键词「{self.keyword}」({total_json_matches}条)"
            })
        
        # M3U分类 - 只有有匹配时才显示
        if self.search_results["m3u"]:
            total_m3u_matches = sum(r['count'] for r in self.search_results["m3u"])
            classes.append({
                "type_id": "m3u",
                "type_name": f"📺 M3U文件 · 关键词「{self.keyword}」({total_m3u_matches}条)"
            })
        
        # TXT分类 - 只有有匹配时才显示
        if self.search_results["txt"]:
            total_txt_matches = sum(r['count'] for r in self.search_results["txt"])
            classes.append({
                "type_id": "txt",
                "type_name": f"📄 TXT文件 · 关键词「{self.keyword}」({total_txt_matches}条)"
            })
        
        if not classes:
            classes = [{"type_id": "0", "type_name": f"未找到包含「{self.keyword}」的文件"}]
        
        return {"class": classes}

    def categoryContent(self, tid, pg, filter, ext):
        """返回选中文件类型中所有匹配的文件"""
        if str(pg) != "1":
            return {"page": 1, "pagecount": 1, "list": []}
        
        if tid not in self.search_results or not self.search_results[tid]:
            return {"list": []}
        
        # 选择图标
        if tid == "json":
            icon = "https://img.icons8.com/color/200/json--v1.png"
        elif tid == "m3u":
            icon = "https://img.icons8.com/color/200/opened-folder.png"
        else:  # txt
            icon = "https://img.icons8.com/color/200/txt.png"
        
        items = []
        for result in self.search_results[tid]:
            file_path = result['path']
            rel_path = os.path.relpath(file_path, self.root_dir)
            
            # 生成文件ID
            file_id = base64.b64encode(
                f"{tid}|{file_path}|{result['count']}".encode()
            ).decode()
            
            items.append({
                "vod_id": file_id,
                "vod_name": rel_path,
                "vod_pic": icon,
                "vod_remarks": f"匹配{result['count']}条 · {self.keyword}"
            })
        
        return {
            "page": 1,
            "pagecount": 1,
            "limit": 100,
            "total": len(items),
            "list": items
        }

    def detailContent(self, array):
        """返回选中文件内的所有匹配内容"""
        if not array:
            return {"list": []}
        
        try:
            file_id = str(array[0])
            data = base64.b64decode(file_id).decode()
            file_type, file_path, match_count = data.split('|', 2)
            
            # 找到对应的搜索结果
            target_result = None
            for result in self.search_results[file_type]:
                if result['path'] == file_path:
                    target_result = result
                    break
            
            if not target_result:
                return {"list": []}
            
            play_urls = []
            
            if file_type == "json":
                # 使用已保存的匹配项
                for item in target_result['matched_items']:
                    vod_play_url = item.get('vod_play_url', '')
                    if vod_play_url:
                        # 处理多个播放地址
                        urls = vod_play_url.split('#')
                        for url in urls:
                            if '$' in url:
                                name, url_addr = url.split('$', 1)
                                b64_url = base64.b64encode(url_addr.encode('utf-8')).decode()
                                play_urls.append(f"{name}${b64_url}")
            
            else:  # m3u/txt
                for item in target_result['matched_items']:
                    name = item.get('name', f"频道{len(play_urls)+1}")
                    url = item.get('url', '')
                    if url:
                        b64_url = base64.b64encode(url.encode('utf-8')).decode()
                        play_urls.append(f"{name}${b64_url}")
            
            if not play_urls:
                return {"list": []}
            
            # 构建详情
            file_name = os.path.basename(file_path)
            content = f"文件路径: {file_path}\n关键词: {self.keyword}\n匹配数量: {len(play_urls)}条"
            
            return {"list": [{
                "vod_id": file_id,
                "vod_name": file_name,
                "vod_pic": "https://img.icons8.com/color/200/search.png",
                "vod_play_from": f"搜索「{self.keyword}」",
                "vod_play_url": "#".join(play_urls),
                "vod_content": content
            }]}
            
        except Exception as e:
            print(f"解析出错: {e}")
            return {"list": []}

    def playerContent(self, flag, id, vipFlags):
        """返回播放地址"""
        try:
            # 解码获取真实URL
            url = base64.b64decode(id).decode()
        except:
            url = id
        
        return {
            "url": url,
            "parse": 0,
            "header": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        }

    def destroy(self):
        return "destroy"