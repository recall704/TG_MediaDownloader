"""
GreenVideo 视频下载 - Playwright 自动化版本
使用浏览器自动化确保加密逻辑完全正确

这个方案更可靠，因为：
1. 直接使用浏览器的 JavaScript 执行加密逻辑
2. 无需手动实现加密算法
3. 可以自动获取最新的密钥
"""

import argparse
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from patchright.async_api import async_playwright

# 常量定义
CHUNK_SIZE = 8192
MAX_FILENAME_BYTES = 255
DEFAULT_EXT = ".mp4"
SUPPORTED_VIDEO_EXTENSIONS = ("mp4", "webm", "mkv", "avi", "mov", "flv", "wmv", "m4v")
SYSTEM_PATH_LIMIT = 4096
DEFAULT_TIMEOUT = 300


class PlaywrightGreenVideoDownloader:
    def __init__(self, timeout=8000, max_retries=3, retry_delay=2):
        self.base_url = "https://greenvideo.cc"
        self.api_url = f"{self.base_url}/api/video/cnSimpleExtract"
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    async def extract_video_with_interception(
        self, video_url: str, headless: bool = False
    ):
        """
        使用网络拦截获取准确的请求和响应

        Args:
            video_url: 视频链接
            headless: 是否使用无头模式

        Returns:
            tuple: (result, headers) - 视频信息字典和响应headers
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            page = await browser.new_page()
            api_response = []
            response_ready = asyncio.Event()

            async def handle_response(response):
                if "/api/video/cnSimpleExtract" not in response.url:
                    return

                try:
                    response_text = await response.text()
                    logging.debug(f"API响应: HTTP {response.status}")

                    api_response.append(
                        {
                            "url": response.url,
                            "status": response.status,
                            "headers": dict(response.headers),
                            "body": response_text,
                        }
                    )

                    if response.status == 200:
                        try:
                            data = json.loads(response_text)
                            if data.get("code") == 200:
                                response_ready.set()
                                logging.info(f"✅ API调用成功: {data.get('message')}")
                            else:
                                logging.error(
                                    f"❌ API错误 {data.get('code')}: {response_text}, {response.url}"
                                )
                        except json.JSONDecodeError:
                            logging.error("响应JSON解析失败")
                except Exception as e:
                    logging.error(f"读取响应失败: {e}")

            page.on("response", lambda r: asyncio.create_task(handle_response(r)))

            await page.goto(
                self.base_url,
                wait_until="networkidle",
                timeout=30000,
                referer=self.base_url,
            )
            await page.fill('input[placeholder*="视频链接"]', video_url)
            await page.get_by_role("button", name="开始").click()

            logging.info("等待API响应...")
            try:
                await asyncio.wait_for(
                    response_ready.wait(), timeout=self.timeout / 1000
                )
                logging.info("收到成功响应")
                await asyncio.sleep(1.0)
            except asyncio.TimeoutError:
                logging.warning("等待响应超时，使用已记录的响应")

            await browser.close()

            # 查找成功的响应
            for resp in reversed(api_response):
                if resp["status"] != 200:
                    continue
                try:
                    result = json.loads(resp["body"])
                    if result.get("code") == 200:
                        return self._parse_response(result.get("data", {})), resp[
                            "headers"
                        ]
                except json.JSONDecodeError:
                    continue

            return None, {}

    def _parse_response(self, data):
        """解析 API 响应数据"""
        result = {
            "vid": data.get("vid"),
            "host": data.get("host"),
            "host_alias": data.get("hostAlias"),
            "title": data.get("displayTitle"),
            "status": data.get("status"),
            "downloads": [],
        }

        video_items = data.get("videoItemVoList", [])
        for item in video_items:
            # 只保留 URL 合法的 video 类型
            url = item.get("baseUrl")
            file_type = item.get("fileType")
            logging.info(f"url: {url}, file_type: {file_type}")

            # 判断 URL 是否合法（以 http:// 或 https:// 开头）
            is_valid_url = url and (
                url.startswith("http://") or url.startswith("https://")
            )

            # 只保留类型为 video 且 URL 合法的项
            if file_type == "video" and is_valid_url:
                download_info = {
                    "url": url,
                    "file_type": file_type,
                    "size": item.get("size"),
                }
                result["downloads"].append(download_info)

        return result

    def _get_file_extension(self, url: str) -> str:
        """从 URL 中提取文件扩展名"""
        parsed = urlparse(url)
        path = unquote(parsed.path)

        # 从路径中提取扩展名
        ext = os.path.splitext(path)[1]
        if ext:
            return ext

        # 从查询参数中提取扩展名
        query = parsed.query
        pattern = r"\.(" + "|".join(SUPPORTED_VIDEO_EXTENSIONS) + r")(?:&|$)"
        ext_match = re.search(pattern, query, re.IGNORECASE)
        if ext_match:
            return f".{ext_match.group(1)}"

        return DEFAULT_EXT

    def _sanitize_filename(self, filename: str, max_length: int = MAX_FILENAME_BYTES):
        """
        清理文件名，移除非法字符，确保不超过指定长度

        Args:
            filename: 原始文件名（不包括扩展名）
            max_length: 文件名的最大字节长度

        Returns:
            tuple: (safe_filename_bytes, truncated) - 安全的文件名（字节），是否被截断
        """
        # 移除非法字符
        filename = re.sub(r'[<>:"/\\|?*]', "_", filename)
        filename = filename.strip(". ")

        # 截断到最大长度
        truncated = False
        while len(filename.encode("utf-8")) > max_length:
            filename = filename[:-1]
            truncated = True

        # 确保文件名不为空
        if not filename:
            filename = "video"

        return filename.encode("utf-8"), truncated

    def _generate_safe_filename(
        self, title: str, ext: str, download_path: Path
    ) -> tuple[Path, bool]:
        """
        生成安全的文件名和路径

        Args:
            title: 原始标题
            ext: 文件扩展名
            download_path: 下载目录路径

        Returns:
            tuple: (filepath, truncated) - 完整文件路径和是否被截断的标志
        """
        dir_path_str = str(download_path)
        dir_bytes = len(dir_path_str.encode("utf-8")) + 1
        max_filename_bytes = min(MAX_FILENAME_BYTES, SYSTEM_PATH_LIMIT - dir_bytes)
        ext_bytes_len = len(ext.encode("utf-8"))
        max_name_bytes = max(10, max_filename_bytes - ext_bytes_len)

        # 处理扩展名过短的情况
        if max_name_bytes < 10:
            ext = ext[: max_filename_bytes - 10]
            max_name_bytes = 10

        # 清理并截断文件名
        safe_name_bytes, truncated = self._sanitize_filename(title, max_name_bytes)
        final_filename_bytes = safe_name_bytes + ext.encode("utf-8")

        # 二次截断检查
        while (
            len(final_filename_bytes) > max_filename_bytes and len(safe_name_bytes) > 10
        ):
            safe_name_bytes = safe_name_bytes[:-1]
            final_filename_bytes = safe_name_bytes + ext.encode("utf-8")
            truncated = True

        # 如果仍然超限，使用时间戳
        if len(final_filename_bytes) > max_filename_bytes:
            import time

            timestamp = str(int(time.time()))
            safe_name_bytes = f"video_{timestamp}".encode("utf-8")
            final_filename_bytes = safe_name_bytes + ext.encode("utf-8")
            logging.error("文件名过长，使用时间戳代替")

        safe_filename = safe_name_bytes.decode("utf-8")
        filename = safe_filename + ext

        if truncated:
            logging.warning(
                f"文件名过长已截断（{len(safe_name_bytes)}字节）: {title[:50]}..."
            )

        return download_path / filename, truncated

    async def _download_single_file(
        self,
        url: str,
        filepath: Path,
        file_info: dict,
        progress_callback=None,
        download_timeout: int = DEFAULT_TIMEOUT,
    ) -> bool:
        """
        下载单个文件，包含重试逻辑

        Args:
            file_info: 文件信息字典，会被传递给 progress_callback

        Returns:
            bool: 下载是否成功
        """
        retry_count = 0

        while retry_count <= self.max_retries:
            try:
                request_headers = {
                    "Referer": url,
                    "user-agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/140.0.0.0 Safari/537.36"
                    ),
                }

                response = requests.get(
                    url,
                    headers=request_headers,
                    stream=True,
                    timeout=download_timeout,
                )
                response.raise_for_status()

                total_size = int(response.headers.get("Content-Length", 0))
                downloaded_size = 0

                with open(filepath, "wb") as f:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            if progress_callback:
                                await progress_callback(
                                    downloaded_size, total_size, file_info
                                )
                            if total_size > 0:
                                progress = (downloaded_size / total_size) * 100
                                logging.debug(
                                    f"  进度: {progress:.1f}% "
                                    f"({downloaded_size}/{total_size} bytes)"
                                )

                logging.info(f"  ✅ 下载成功: {filepath}")
                return True

            except requests.exceptions.RequestException as e:
                retry_count += 1
                if retry_count <= self.max_retries:
                    logging.warning(
                        f"  ⚠️ 下载失败 (第{retry_count}次/{self.max_retries}重试): {e}"
                    )
                    logging.info(f"  等待 {self.retry_delay} 秒后重试...")
                    await asyncio.sleep(self.retry_delay)
                else:
                    logging.error(f"  ❌ 下载失败 (已重试{self.max_retries}次): {e}")

            except OSError as e:
                if e.errno == 36 or "too long" in str(e).lower():
                    logging.error(f"  ❌ 文件名过长: {e}")
                    full_path = str(filepath)
                    logging.error(
                        f"     路径长度: {len(full_path.encode('utf-8'))} 字节"
                    )
                    return False
                retry_count += 1
                if retry_count <= self.max_retries:
                    logging.warning(
                        f"  ⚠️ 文件系统错误 (第{retry_count}次/{self.max_retries}重试): {e}"
                    )
                    logging.info(f"  等待 {self.retry_delay} 秒后重试...")
                    await asyncio.sleep(self.retry_delay)
                else:
                    logging.error(
                        f"  ❌ 文件系统错误 (已重试{self.max_retries}次): {e}"
                    )

            except Exception as e:
                retry_count += 1
                if retry_count <= self.max_retries:
                    logging.warning(
                        f"  ⚠️ 下载失败 (第{retry_count}次/{self.max_retries}重试): {e}"
                    )
                    logging.info(f"  等待 {self.retry_delay} 秒后重试...")
                    await asyncio.sleep(self.retry_delay)
                else:
                    logging.error(f"  ❌ 下载失败 (已重试{self.max_retries}次): {e}")

        return False

    async def download_video(
        self,
        result,
        download_dir,
        download_timeout=DEFAULT_TIMEOUT,
        progress_callback=None,
    ):
        """
        下载视频文件

        下载失败时会自动重试，重试次数和间隔由 max_retries 和 retry_delay 参数决定。
        文件名过长错误（errno 36）不会重试。

        Args:
            result: 视频信息字典
            download_dir: 下载目录路径
            download_timeout: 下载超时时间（秒）
            progress_callback: 进度回调函数

        Returns:
            list: 下载成功的文件路径列表
        """
        if not result or not result.get("downloads"):
            logging.warning("没有可下载的视频")
            return []

        download_path = Path(download_dir)
        download_path.mkdir(parents=True, exist_ok=True)

        downloaded_files = []

        for i, download in enumerate(result["downloads"], 1):
            url = download["url"]
            title = result.get("title", f"video_{i}")
            ext = self._get_file_extension(url)

            logging.info(f"正在下载视频 {i}/{len(result['downloads'])}")
            logging.info(f"  URL: {url}")

            filepath, _ = self._generate_safe_filename(title, ext, download_path)
            logging.info(f"  保存到: {filepath}")

            file_info = {
                "current_file": i,
                "total_files": len(result["downloads"]),
                "filename": filepath.name,
                "url": url,
                "filepath": str(filepath),
            }

            success = await self._download_single_file(
                url, filepath, file_info, progress_callback, download_timeout
            )

            if success:
                downloaded_files.append(str(filepath))

        return downloaded_files

    def print_result(self, result: dict | None):
        """打印提取结果"""
        if not result:
            logging.warning("未获取到视频信息")
            return

        separator = "=" * 50
        logging.info(f"\n{separator}")
        logging.info("         视频信息")
        logging.info(separator)
        logging.info(f"标题: {result['title']}")
        logging.info(f"平台: {result['host_alias']} ({result['host']})")
        logging.info(f"视频ID: {result['vid']}")
        logging.info(f"状态: {result['status']}")
        logging.info(f"\n{separator}")
        logging.info("         下载链接")
        logging.info(separator)

        for i, download in enumerate(result["downloads"], 1):
            logging.info(f"  类型: {download['file_type']}")
            logging.info(f"  URL: {download['url']}")


async def main():
    """主函数"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="GreenVideo 视频下载链接提取工具 (Playwright版本)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s "https://v.douyin.com/Yf7fNbul2fc/"
  %(prog)s -u "https://www.bilibili.com/video/BV1xx411c7mD"
  %(prog)s --url "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --quiet --headless
  %(prog)s -u "https://v.douyin.com/Yf7fNbul2fc/" -d ./downloads
  %(prog)s --url "https://www.bilibili.com/video/BV1xx411c7mD" --download /path/to/save
        """,
    )

    parser.add_argument(
        "-u",
        "--url",
        dest="url",
        type=str,
        required=True,
        help="视频链接（支持抖音、B站、YouTube等1000+平台）",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        dest="quiet",
        action="store_true",
        help="静默模式，只输出JSON结果",
    )
    parser.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        help="使用无头模式（不显示浏览器窗口）",
    )
    parser.add_argument(
        "--no-hint", dest="no_hint", action="store_true", help="不显示使用提示"
    )
    parser.add_argument(
        "-d", "--download", dest="download_dir", type=str, help="下载视频到指定目录"
    )

    args = parser.parse_args()
    downloader = PlaywrightGreenVideoDownloader()

    if not args.quiet:
        logging.info(f"正在解析视频: {args.url}")
        logging.info("使用 Playwright 自动化方式")

    result, _ = await downloader.extract_video_with_interception(
        args.url, headless=args.headless
    )

    if args.download_dir:
        if result:
            downloaded_files = await downloader.download_video(
                result, args.download_dir
            )
            if downloaded_files:
                logging.info(f"✅ 下载完成！共下载 {len(downloaded_files)} 个文件")
                for filepath in downloaded_files:
                    logging.info(f"   - {filepath}")
            else:
                logging.error("❌ 下载失败")
        else:
            logging.error("❌ 无法下载：解析视频信息失败")
    elif args.quiet:
        if result:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"error": "解析失败"}, ensure_ascii=False))
    else:
        downloader.print_result(result)

    if not args.no_hint and not args.quiet and not args.download_dir:
        logging.info("\n提示:")
        logging.info("- 支持抖音、B站、YouTube、Instagram、TikTok等1000+平台")
        logging.info("- 使用 --headless 参数可隐藏浏览器窗口")
        logging.info("- 使用 -d/--download 参数可下载视频到指定目录")
        logging.info("- 静默模式适合脚本调用")


if __name__ == "__main__":
    asyncio.run(main())
