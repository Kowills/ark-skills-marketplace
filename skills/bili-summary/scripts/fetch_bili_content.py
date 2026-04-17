#!/usr/bin/env python3
"""fetch_bili_content.py — 获取B站UP主近期动态和视频字幕
Usage: python fetch_bili_content.py <UP主名字> [天数, 默认1]
"""

import argparse
import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
import sys


class BilibiliFetcher:
    """B站内容获取器，封装获取UP主动态和视频字幕的核心逻辑"""

    def __init__(self, author_name: str, days: int):
        self.author_name = author_name
        self.days = days
        self.user_uid: Optional[str] = None
        self.dynamic_count: int = 0
        self.video_count: int = 0
        self.subtitle_count: int = 0
        self.errors: List[str] = []
        self.cutoff_date: str = self._calculate_cutoff_date()
        self.today: str = datetime.now().strftime("%Y-%m-%d")
        self.out_dir: Path = Path.home() / "bili-data" / author_name / self.today

    @staticmethod
    def _run_opencli(args: List[str]) -> Optional[str]:
        """执行 opencli 命令并返回输出"""
        try:
            result = subprocess.run(
                ["opencli"] + args,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None

    def _calculate_cutoff_date(self) -> str:
        """计算截止日期（N天前的今天）"""
        cutoff = datetime.now() - timedelta(days=self.days)
        return cutoff.strftime("%Y-%m-%d")

    def _extract_date_from_detail(self, time_str: str) -> Optional[str]:
        """从详情时间字符串提取日期"""
        from datetime import datetime
        # 格式1: 2026年04月17日（完整年份）
        match = re.search(r'(\d{4})年(\d{2})月(\d{2})日', time_str)
        if match:
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        # 格式2: 04月17日（只有月日，补当前年份）
        match = re.search(r'(\d{2})月(\d{2})日', time_str)
        if match:
            year = datetime.now().year
            return f"{year}-{match.group(1)}-{match.group(2)}"
        return None

    def search_author_uid(self) -> bool:
        """搜索UP主获取UID，优先精确匹配"""
        print(f">>> 搜索UP主: {self.author_name}")
        search_json = self._run_opencli(["bilibili", "search", self.author_name, "--type", "user", "--format", "json"])

        if not search_json:
            print("ERROR: 搜索失败或未找到结果")
            return False

        try:
            results = json.loads(search_json)
        except json.JSONDecodeError:
            print("ERROR: 搜索结果解析失败")
            return False

        if not results:
            print(f"ERROR: 未找到UP主 '{self.author_name}'")
            return False

        # 优先精确匹配
        for user in results:
            if user.get("title") == self.author_name:
                url = user.get("url")
                break
        else:
            # fallback 到第一个结果
            url = results[0].get("url")

        if not url:
            print("ERROR: 无法获取UP主URL")
            return False

        # 从URL提取UID
        match = re.search(r'(\d+)$', url)
        if not match:
            print(f"ERROR: 无法从URL提取UID: {url}")
            return False

        self.user_uid = match.group(1)
        print(f"    找到 UID: {self.user_uid}")
        return True

    def get_dynamics(self) -> List[Dict[str, Any]]:
        """获取动态列表，返回处理后的动态信息数组"""
        print(f">>> 获取动态列表 (最近 {self.days} 天)")
        print(f"    截止日期: {self.cutoff_date}")

        # 计算需要获取的页数
        pages = min((self.days // 3) + 1, 5)
        feed_json = self._run_opencli(["bilibili", "feed", self.user_uid, "--limit", "30", "--pages", str(pages), "--format", "json"])

        if not feed_json:
            print("ERROR: 获取动态失败")
            return []

        try:
            feed = json.loads(feed_json)
        except json.JSONDecodeError:
            print("ERROR: 动态解析失败")
            return []

        print(f"    获取到 {len(feed)} 条动态")

        dynamics: List[Dict[str, Any]] = []
        for item in feed:
            dtype = item.get("type", "")
            url = item.get("url", "")
            title = item.get("title", "").replace("|", "｜").replace("\n", " ")
            time = item.get("time", "")
            likes = item.get("likes", 0)

            # 提取ID
            bvid = None
            dyn_id = None
            if dtype == "video":
                match = re.search(r'(BV[A-Za-z0-9]+)', url)
                if match:
                    bvid = match.group(1)
                    dyn_id = f"video_{bvid}"
            else:
                match = re.search(r'(\d+)$', url)
                if match:
                    dyn_id = match.group(1)

            dynamics.append({
                "type": dtype,
                "url": url,
                "title": title,
                "time": time,
                "likes": likes,
                "bvid": bvid,
                "dyn_id": dyn_id
            })

        return dynamics

    def get_feed_detail(self, dyn_id: str) -> Tuple[Optional[str], Optional[str]]:
        """获取动态详情，返回(text, time)"""
        detail_json = self._run_opencli(["bilibili", "feed-detail", dyn_id, "--format", "json"])
        if not detail_json:
            self.errors.append(f"feed-detail 失败: {dyn_id}")
            return None, None

        try:
            detail = json.loads(detail_json)
        except json.JSONDecodeError:
            self.errors.append(f"feed-detail 解析失败: {dyn_id}")
            return None, None

        # 保存原始JSON
        if self.user_uid:
            (self.out_dir / "dynamics").mkdir(parents=True, exist_ok=True)
            detail_file = self.out_dir / "dynamics" / f"{dyn_id}.json"
            with open(detail_file, "w", encoding="utf-8") as f:
                json.dump(detail, f, ensure_ascii=False, indent=2)

        # 提取text和time
        text = None
        time_str = None
        for item in detail:
            if item.get("field") == "text":
                text = item.get("value", "")
            elif item.get("field") == "time":
                time_str = item.get("value", "")

        return text, time_str

    def get_subtitle(self, bvid: str) -> Optional[str]:
        """获取视频字幕，返回拼接后的文本"""
        sub_json = self._run_opencli(["bilibili", "subtitle", bvid, "--format", "json"])
        if not sub_json or sub_json == "[]":
            return None

        try:
            subtitles = json.loads(sub_json)
        except json.JSONDecodeError:
            return None

        if not subtitles:
            return None

        text = " ".join(item.get("content", "") for item in subtitles)
        text = text.strip()

        if text:
            (self.out_dir / "subtitles").mkdir(parents=True, exist_ok=True)
            subtitle_file = self.out_dir / "subtitles" / f"{bvid}.txt"
            with open(subtitle_file, "w", encoding="utf-8") as f:
                f.write(text)

        return text if text else None

    def process_dynamics(self, dynamics: List[Dict[str, Any]]) -> str:
        """处理所有动态，返回合并后的Markdown内容"""
        combined_lines: List[str] = []

        for dyn in dynamics:
            dtype = dyn["type"]
            durl = dyn["url"]
            dtitle = dyn["title"]
            dtime = dyn["time"]
            dlikes = dyn["likes"]
            bvid = dyn["bvid"]
            dyn_id = dyn["dyn_id"]

            if not dyn_id:
                continue

            print(f"  处理动态: [{dtype}] {dyn_id} - {dtitle[:40]}...")

            detail_text: Optional[str] = None
            detail_time: Optional[str] = dtime

            if dtype != "video":
                # 非视频需要获取详情
                detail_text, detail_time = self.get_feed_detail(dyn_id)

                # 如果feed-detail没有text字段，fallback使用feed中的title
                if not detail_text:
                    detail_text = dtitle

            # 时间过滤 - 对所有类型都生效
            if detail_time:
                detail_date = self._extract_date_from_detail(detail_time)
                if detail_date and detail_date < self.cutoff_date:
                    print(f"    跳过（超出时间范围: {detail_date}）")
                    continue

            self.dynamic_count += 1

            subtitle_text: Optional[str] = None
            if dtype == "video" and bvid:
                self.video_count += 1
                print(f"    获取视频字幕: {bvid}")
                subtitle_text = self.get_subtitle(bvid)
                if subtitle_text:
                    self.subtitle_count += 1
                    print(f"    字幕获取成功 ({len(subtitle_text)} 字符)")
                else:
                    print("    该视频无字幕")

            # 添加到combined
            combined_lines.append(f"### [{dtype}] {dtitle}")
            combined_lines.append(f"- 时间: {detail_time or dtime}")
            combined_lines.append(f"- 点赞: {dlikes}")
            combined_lines.append(f"- 链接: {durl}")
            combined_lines.append("")

            if detail_text and detail_text != dtitle:
                combined_lines.append("**内容：**")
                combined_lines.append("")
                combined_lines.append(detail_text)
                combined_lines.append("")

            if subtitle_text:
                combined_lines.append("**视频字幕：**")
                combined_lines.append("")
                combined_lines.append(subtitle_text)
                combined_lines.append("")

            combined_lines.append("---")
            combined_lines.append("")

        return "".join(line + "\n" for line in combined_lines)

    def write_manifest(self):
        """写入manifest.json"""
        manifest = {
            "author": self.author_name,
            "uid": self.user_uid,
            "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "date_range": f"最近 {self.days} 天 (截止 {self.cutoff_date})",
            "total_dynamics": self.dynamic_count,
            "video_count": self.video_count,
            "subtitle_count": self.subtitle_count,
            "errors": self.errors
        }

        manifest_file = self.out_dir / "manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    def write_combined(self, content: str):
        """写入combined.md"""
        fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_range_line = f"最近 {self.days} 天（截止 {self.cutoff_date}）"
        video_line = f"{self.video_count} 个（其中 {self.subtitle_count} 个有字幕）"

        header = f"""# {self.author_name} — B站动态汇总

- **UID**: {self.user_uid}
- **获取时间**: {fetch_time}
- **时间范围**: {date_range_line}
- **动态数量**: {self.dynamic_count} 条
- **视频数量**: {video_line}
- **UP主主页**: https://space.bilibili.com/{self.user_uid}

---

"""

        combined_file = self.out_dir / "combined.md"
        with open(combined_file, "w", encoding="utf-8") as f:
            f.write(header)
            f.write(content)

    def check_opencli(self) -> bool:
        """检查opencli是否已安装"""
        try:
            subprocess.run(["opencli", "--help"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def run(self) -> bool:
        """执行完整获取流程"""
        # 检查依赖
        if not self.check_opencli():
            print("ERROR: opencli 未安装")
            return False

        # 创建输出目录
        (self.out_dir / "dynamics").mkdir(parents=True, exist_ok=True)
        (self.out_dir / "subtitles").mkdir(parents=True, exist_ok=True)

        # 步骤1: 搜索获取UID
        if not self.search_author_uid():
            return False

        # 步骤2: 获取动态列表
        dynamics = self.get_dynamics()

        # 步骤3: 处理动态（即使 0 条也继续生成输出）
        combined_content = self.process_dynamics(dynamics)

        # 步骤4: 写入manifest
        self.write_manifest()

        # 步骤5: 写入combined.md
        self.write_combined(combined_content)

        # 输出结果
        print()
        print("=== 完成 ===")
        print(f"  动态: {self.dynamic_count} 条")
        print(f"  视频: {self.video_count} 个 (字幕: {self.subtitle_count} 个)")
        print(f"  输出目录: {self.out_dir}")
        print(f"  合并文件: {self.out_dir}/combined.md")

        if self.errors:
            print(f"  警告: {len(self.errors)} 个错误")
            for err in self.errors:
                print(f"    - {err}")

        return True


def main():
    parser = argparse.ArgumentParser(description="获取B站UP主近期动态和视频字幕")
    parser.add_argument("author_name", help="UP主名字")
    parser.add_argument("days", nargs="?", type=int, default=1, help="天数 (默认: 1)")
    args = parser.parse_args()

    fetcher = BilibiliFetcher(args.author_name, args.days)
    success = fetcher.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
