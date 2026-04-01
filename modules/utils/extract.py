#!/usr/bin/env python3
"""
URL 解析模块
从字符串中提取 URL
"""

import re
import argparse
from typing import Optional
from urllib.parse import urlparse


def extract_url(text: str) -> Optional[str]:
    """
    从字符串中提取 URL

    Args:
        text: 包含 URL 的字符串

    Returns:
        提取到的 URL，如果没有找到则返回 None
    """
    url_pattern = r'https?://[^\s<>"\'{}|\\^`\[\]]+'

    match = re.search(url_pattern, text)

    if match:
        return match.group(0)
    return None


def is_telegram_link(url: str) -> bool:
    """
    判断是否为 t.me 域名链接

    Args:
        url: URL 字符串

    Returns:
        是否为 t.me 链接
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
        return parsed.hostname in ("t.me", "telegram.me")
    except Exception:
        return False


def extract_magnet(text: str) -> Optional[str]:
    """
    从字符串中提取磁力链接

    Args:
        text: 包含磁力链接的字符串

    Returns:
        提取到的第一个磁力链接，如果没有找到则返回 None
    """
    magnet_pattern = r"magnet:\?(?:[-\w.]+=[^&\s]+(?:&[-\w.]+=[^&\s]+)*)"
    match = re.search(magnet_pattern, text)

    if match:
        return match.group(0)
    return None


def main():
    """主函数，用于命令行测试"""
    parser = argparse.ArgumentParser(
        description="从字符串中提取 URL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python url_parse.py "请访问 https://example.com 获取更多信息"
  python url_parse.py -t "这是一个测试字符串 https://test.com"
        """,
    )

    parser.add_argument("text", nargs="?", help="包含 URL 的字符串")

    parser.add_argument(
        "-t", "--text", dest="text_alt", help="包含 URL 的字符串（替代位置参数）"
    )

    args = parser.parse_args()

    input_text = args.text or args.text_alt

    if not input_text:
        parser.print_help()
        print("\n错误: 请提供包含 URL 的字符串")
        return 1

    url = extract_url(input_text)

    if url:
        print(f"提取到的 URL: {url}")
        return 0
    else:
        print("未找到 URL")
        return 1


if __name__ == "__main__":
    exit(main())
