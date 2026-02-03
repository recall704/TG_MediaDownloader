"""
GreenVideo 视频下载 - Playwright 自动化版本
使用浏览器自动化确保加密逻辑完全正确

这个方案更可靠，因为：
1. 直接使用浏览器的 JavaScript 执行加密逻辑
2. 无需手动实现加密算法
3. 可以自动获取最新的密钥
"""

import asyncio
import json
import argparse
import os
import re
import logging
from pathlib import Path
from urllib.parse import urlparse, unquote
import requests

from patchright.async_api import async_playwright


class PlaywrightGreenVideoDownloader:
    def __init__(self, timeout=8000):
        self.base_url = "https://greenvideo.cc"
        self.api_url = f"{self.base_url}/api/video/cnSimpleExtract"
        self.timeout = timeout

    async def extract_video_with_interception(self, video_url, headless=False):
        """
        使用网络拦截获取准确的请求和响应

        Args:
            video_url: 视频链接
            headless: 是否使用无头模式（不显示浏览器窗口）

        Returns:
            tuple: (result, headers) - 视频信息字典和响应headers
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            page = await browser.new_page()

            # 存储请求和响应 - 使用 asyncio 保证正确存储
            api_response = []
            response_ready = asyncio.Event()

            # 监听响应 - 使用更可靠的方式
            async def handle_response(response):
                if "/api/video/cnSimpleExtract" in response.url:
                    try:
                        response_text = await response.text()
                        logging.info(f"捕获到API响应: HTTP {response.status}")

                        # 解析JSON看看内容
                        try:
                            data = json.loads(response_text)
                            if data.get("code") == 200:
                                logging.info(f"✅ 成功: {data.get('message')}")
                            else:
                                logging.error(
                                    f"❌ 错误 {data.get('code')}: {data.get('message')}"
                                )
                        except Exception as e:
                            logging.error(f"解析响应JSON失败: {e}")

                        api_response.append(
                            {
                                "url": response.url,
                                "status": response.status,
                                "headers": dict(response.headers),
                                "body": response_text,
                            }
                        )
                        logging.debug(f"响应体摘要: {response_text[:150]}...")

                        # 只有成功（200）时才设置事件，或者尝试几次后超时
                        if response.status == 200:
                            # 如果成功，尝试解析，如果code是200就标记完成
                            try:
                                result = json.loads(response_text)
                                if result.get("code") == 200:
                                    response_ready.set()
                            except Exception as e:
                                logging.error(f"解析响应结果失败: {e}")

                    except Exception as e:
                        logging.error(f"读取响应失败: {e}")

            # 设置响应监听（在事件循环中）
            page.on(
                "response",
                lambda response: asyncio.create_task(handle_response(response)),
            )

            # 访问网站
            await page.goto(
                self.base_url,
                wait_until="networkidle",
                timeout=30 * 1000,
                referer=self.base_url,
            )

            # 填写输入框并点击开始按钮
            await page.fill('input[placeholder*="视频链接"]', video_url)
            await page.get_by_role("button", name="开始").click()

            # 等待响应就绪，最多等待10秒
            logging.info("等待API响应...")
            try:
                await asyncio.wait_for(response_ready.wait(), timeout=self.timeout)
                logging.info("收到成功响应！")
                # 再等待一点时间确保响应完全处理
                await asyncio.sleep(1.0)
            except asyncio.TimeoutError:
                logging.warning("警告: 等待响应超时，但已记录所有响应")

            # 关闭浏览器
            await browser.close()

            # 返回结果和headers
            if api_response:
                # 查找成功的响应（可能有多个，取最后一个成功的）
                for resp in reversed(api_response):
                    if resp["status"] == 200:
                        try:
                            result = json.loads(resp["body"])
                            if result.get("code") == 200:
                                return (
                                    self._parse_response(result.get("data", {})),
                                    resp["headers"],
                                )
                            elif result.get("code") == 530:
                                logging.error(
                                    f"API错误: {result.get('message', '未知错误')}"
                                )
                                continue
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

    def _get_file_extension(self, url):
        """从 URL 中提取文件扩展名"""
        parsed = urlparse(url)
        path = unquote(parsed.path)
        # 尝试从路径中获取扩展名
        ext = os.path.splitext(path)[1]
        if ext:
            return ext
        # 如果没有扩展名，尝试从查询参数中获取
        query = parsed.query
        ext_match = re.search(
            r"\.(mp4|webm|mkv|avi|mov|flv|wmv|m4v)(?:&|$)", query, re.IGNORECASE
        )
        if ext_match:
            return f".{ext_match.group(1)}"
        # 默认返回 .mp4
        return ".mp4"

    def _sanitize_filename(self, filename, max_length=255):
        """
        清理文件名，移除非法字符，确保不超过指定长度

        Args:
            filename: 原始文件名（不包括扩展名）
            max_length: 文件名的最大字节长度（默认255）

        Returns:
            tuple: (safe_filename_bytes, truncated) - 安全的文件名（字节），是否被截断
        """
        # 移除或替换非法字符
        illegal_chars = r'[<>:"/\\|?*]'
        filename = re.sub(illegal_chars, "_", filename)
        # 移除首尾空格和点
        filename = filename.strip(". ")

        # 检查是否需要截断
        name_part_bytes = len(filename.encode('utf-8'))
        truncated = name_part_bytes > max_length

        # 截短文件名
        while len(filename.encode('utf-8')) > max_length:
            filename = filename[:-1]

        # 确保文件名不为空
        if not filename:
            filename = "video"

        return filename.encode('utf-8'), truncated

    async def download_video(
        self, result, download_dir, download_timeout=300, progress_callback=None
    ):
        """
        下载视频文件

        Args:
            result: 视频信息字典
            download_dir: 下载目录路径
            progress_callback: 进度回调函数，签名为 async def callback(current, total, file_info, reply_message)

        Returns:
            list: 下载成功的文件路径列表
        """
        if not result or not result.get("downloads"):
            logging.warning("没有可下载的视频")
            return []

        # 确保下载目录存在
        download_path = Path(download_dir)
        download_path.mkdir(parents=True, exist_ok=True)

        # 计算目录路径的字节长度（用于限制完整路径）
        dir_path_str = str(download_path)
        dir_bytes = len(dir_path_str.encode('utf-8')) + 1  # +1 for path separator

        downloaded_files = []

        for i, download in enumerate(result["downloads"], 1):
            url = download["url"]
            title = result.get("title", f"video_{i}")

            # 计算可用字节数：系统限制 - 目录路径长度
            # Linux 系统路径限制通常为 4096 字节，但文件名通常限制为 255 字节（ext4）
            max_filename_bytes = min(255, 4096 - dir_bytes)

            # 获取扩展名
            ext = self._get_file_extension(url)
            ext_bytes_len = len(ext.encode('utf-8'))

            # 计算文件名部分可用的最大字节数
            max_name_bytes = max_filename_bytes - ext_bytes_len

            if max_name_bytes < 10:
                max_name_bytes = 10
                ext = ext[:max_filename_bytes - 10]

            # 清理并截断文件名（不包括扩展名）
            safe_name_bytes, name_truncated = self._sanitize_filename(title, max_name_bytes)

            # 组合文件名和扩展名
            final_filename_bytes = safe_name_bytes + ext.encode('utf-8')

            # 二次检查：如果仍然超限，继续截断
            truncated = name_truncated
            while len(final_filename_bytes) > max_filename_bytes and len(safe_name_bytes) > 10:
                safe_name_bytes = safe_name_bytes[:-1]
                final_filename_bytes = safe_name_bytes + ext.encode('utf-8')
                truncated = True

            # 如果还是不行，使用时间戳
            if len(final_filename_bytes) > max_filename_bytes:
                import time
                timestamp = str(int(time.time()))
                safe_name_bytes = f"video_{timestamp}".encode('utf-8')
                final_filename_bytes = safe_name_bytes + ext.encode('utf-8')
                logging.error(f"  文件名过长，使用时间戳代替")

            safe_filename = safe_name_bytes.decode('utf-8')

            if truncated:
                logging.warning(f"文件名过长已截断（{len(safe_name_bytes)}字节）: {title[:50]}...")

            filename = safe_filename + ext
            filepath = download_path / filename

            logging.info(f"正在下载视频 {i}/{len(result['downloads'])}")
            logging.warning(f'{result['downloads']}')
            logging.info(f"  URL: {url}")
            logging.info(f"  保存到: {filepath}")
            logging.debug(f"  文件名长度: {len(final_filename_bytes)} 字节")

            # 准备文件信息用于进度回调
            file_info = {
                "current_file": i,
                "total_files": len(result["downloads"]),
                "filename": filename,
                "url": url,
                "filepath": str(filepath),
            }

            try:
                # 使用流式下载，传递headers
                request_headers = {
                    "Referer": url,
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
                }
                logging.info(f"download from {url}, headers: {request_headers}")
                response = requests.get(
                    url, headers=request_headers, stream=True, timeout=download_timeout
                )
                response.raise_for_status()

                # 获取文件大小用于显示进度
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded_size = 0

                with open(filepath, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            # 调用进度回调
                            if progress_callback:
                                await progress_callback(
                                    downloaded_size, total_size, file_info
                                )
                            # 显示下载进度（控制台）
                            if total_size > 0:
                                progress = (downloaded_size / total_size) * 100
                                logging.debug(
                                    f"  进度: {progress:.1f}% ({downloaded_size}/{total_size} bytes)"
                                )

                downloaded_files.append(str(filepath))
                logging.info(f"  ✅ 下载成功: {filepath}")

            except requests.exceptions.RequestException as e:
                logging.error(f"  ❌ 下载失败: {e}")
            except OSError as e:
                if e.errno == 36 or "too long" in str(e).lower():
                    logging.error(f"  ❌ 文件名仍然过长: {e}")
                    logging.error(f"     文件名长度: {len((dir_path_str + '/' + filename).encode('utf-8'))} 字节")
                else:
                    logging.error(f"  ❌ 文件系统错误: {e}")
            except Exception as e:
                logging.error(f"  ❌ 下载失败: {e}")

        return downloaded_files

    def print_result(self, result):
        """打印提取结果"""
        if not result:
            logging.warning("未获取到视频信息")
            return

        logging.info("\n" + "=" * 50)
        logging.info("         视频信息")
        logging.info("=" * 50)
        logging.info(f"标题: {result['title']}")
        logging.info(f"平台: {result['host_alias']} ({result['host']})")
        logging.info(f"视频ID: {result['vid']}")
        logging.info(f"状态: {result['status']}")
        logging.info("\n" + "=" * 50)
        logging.info("         下载链接")
        logging.info("=" * 50)

        for i, download in enumerate(result["downloads"], 1):
            logging.info(f"   类型: {download['file_type']}")
            logging.info(f"   URL: {download['url']}")


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
        "-d",
        "--download",
        dest="download_dir",
        type=str,
        help="下载视频到指定目录",
    )

    args = parser.parse_args()

    downloader = PlaywrightGreenVideoDownloader()

    if not args.quiet:
        logging.info(f"正在解析视频: {args.url}")
        logging.info("使用 Playwright 自动化方式")

    # 使用网络拦截方式提取视频
    result, headers = await downloader.extract_video_with_interception(
        args.url, headless=args.headless
    )

    if args.download_dir:
        # 下载模式
        if result:
            downloaded_files = await downloader.download_video(result, args.download_dir)
            if downloaded_files:
                logging.info(f"✅ 下载完成！共下载 {len(downloaded_files)} 个文件")
                for filepath in downloaded_files:
                    logging.info(f"   - {filepath}")
            else:
                logging.error("❌ 下载失败")
        else:
            logging.error("❌ 无法下载：解析视频信息失败")
    elif args.quiet:
        # 静默模式 - 输出 JSON
        if result:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"error": "解析失败"}, ensure_ascii=False))
    else:
        downloader.print_result(result)

    # 提示
    if not args.no_hint and not args.quiet and not args.download_dir:
        logging.info("\n提示:")
        logging.info("- 支持抖音、B站、YouTube、Instagram、TikTok等1000+平台")
        logging.info("- 使用 --headless 参数可隐藏浏览器窗口")
        logging.info("- 使用 -d/--download 参数可下载视频到指定目录")
        logging.info("- 静默模式适合脚本调用")


if __name__ == "__main__":
    asyncio.run(main())
