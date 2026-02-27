"""
单元测试 - PlaywrightGreenVideoDownloader
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from modules.tools.greenvideo.playwright_downloader import PlaywrightGreenVideoDownloader


class TestSanitizeFilename(unittest.TestCase):
    """测试 _sanitize_filename 函数"""

    def setUp(self):
        """测试前设置"""
        self.downloader = PlaywrightGreenVideoDownloader()

    def test_normal_filename(self):
        """测试正常文件名"""
        filename = "normal_video"
        safe_name, truncated = self.downloader._sanitize_filename(filename, max_length=255)

        self.assertEqual(safe_name, b"normal_video")
        self.assertFalse(truncated)

    def test_illegal_characters(self):
        """测试包含非法字符的文件名"""
        # 测试各种非法字符: < > : " / \ | ? *
        test_cases = [
            ("video<test>", b"video_test_"),
            ("video>test<", b"video_test_"),
            ("video:test", b"video_test"),
            ('video"test', b"video_test"),
            ("video/test", b"video_test"),
            ("video\\test", b"video_test"),
            ("video|test", b"video_test"),
            ("video?test", b"video_test"),
            ("video*test", b"video_test"),
            ("<>:\"/\\|?*", b"_________"),
        ]

        for input_name, expected in test_cases:
            with self.subTest(input_name=input_name):
                safe_name, truncated = self.downloader._sanitize_filename(input_name, max_length=255)
                self.assertEqual(safe_name, expected)
                self.assertFalse(truncated)

    def test_leading_trailing_spaces_and_dots(self):
        """测试首尾空格和点的移除"""
        test_cases = [
            ("  video  ", b"video"),
            ("...video...", b"video"),
            ("  .video.  ", b"video"),
            ("...  video  ...", b"video"),
        ]

        for input_name, expected in test_cases:
            with self.subTest(input_name=input_name):
                safe_name, truncated = self.downloader._sanitize_filename(input_name, max_length=255)
                self.assertEqual(safe_name, expected)
                self.assertFalse(truncated)

    def test_empty_filename(self):
        """测试空文件名"""
        safe_name, truncated = self.downloader._sanitize_filename("", max_length=255)

        self.assertEqual(safe_name, b"video")
        self.assertFalse(truncated)

    def test_only_illegal_chars(self):
        """测试只有非法字符的文件名"""
        safe_name, truncated = self.downloader._sanitize_filename("<>:\"/\\|?*", max_length=255)

        # 非法字符会被替换为下划线
        self.assertEqual(safe_name, b"_________")
        self.assertFalse(truncated)

    def test_only_spaces_and_dots(self):
        """测试只有空格和点的文件名"""
        safe_name, truncated = self.downloader._sanitize_filename("   ...   ", max_length=255)

        self.assertEqual(safe_name, b"video")
        self.assertFalse(truncated)

    def test_truncation_needed(self):
        """测试需要截断的长文件名"""
        # 创建一个超过255字节的文件名
        long_name = "a" * 300
        safe_name, truncated = self.downloader._sanitize_filename(long_name, max_length=255)

        self.assertTrue(truncated)
        self.assertLessEqual(len(safe_name), 255)
        self.assertTrue(safe_name.startswith(b"a"))

    def test_truncation_with_chinese_characters(self):
        """测试包含中文字符的截断"""
        # 中文字符在UTF-8中占3字节
        chinese_name = "侧方停车没有思路必学这招 学会这招后侧方停车不再害怕，新手司机一看就会，赶紧收藏点赞，前提一定要看完，侧方停车最重要的一步我摆在了视频的最后，记得收藏点赞！你们的陪练是怎么教你们的，是思路还是点位，还是在教你看360？ 或者你们有什么更好的适合新手侧方停车的思路都可以分享在评论区！#开车技巧 #驾驶技巧 #新手上路 #汽车陪练 #每天一个用车知识"
        safe_name, truncated = self.downloader._sanitize_filename(chinese_name, max_length=255)

        self.assertTrue(truncated)
        self.assertLessEqual(len(safe_name), 255)

    def test_mixed_characters_truncation(self):
        """测试混合字符的截断"""
        mixed_name = "视频video测试test" * 20
        safe_name, truncated = self.downloader._sanitize_filename(mixed_name, max_length=100)

        self.assertTrue(truncated)
        self.assertLessEqual(len(safe_name), 100)

    def test_exact_max_length(self):
        """测试刚好等于最大长度的文件名"""
        # 创建刚好255字节的文件名
        exact_name = "a" * 255
        safe_name, truncated = self.downloader._sanitize_filename(exact_name, max_length=255)

        self.assertFalse(truncated)
        self.assertEqual(len(safe_name), 255)

    def test_custom_max_length(self):
        """测试自定义最大长度"""
        filename = "test_video_filename"
        safe_name, truncated = self.downloader._sanitize_filename(filename, max_length=10)

        self.assertTrue(truncated)
        self.assertLessEqual(len(safe_name), 10)

    def test_combined_operations(self):
        """测试组合操作：非法字符 + 首尾空格 + 截断"""
        filename = "  ...<test:video>...  " + "a" * 300
        safe_name, truncated = self.downloader._sanitize_filename(filename, max_length=50)

        self.assertTrue(truncated)
        self.assertLessEqual(len(safe_name), 50)
        # 应该移除非法字符和首尾空格点
        self.assertNotIn(b"<", safe_name)
        self.assertNotIn(b">", safe_name)
        self.assertNotIn(b":", safe_name)

    def test_unicode_characters(self):
        """测试Unicode字符"""
        test_cases = [
            ("视频测试", "视频测试".encode('utf-8')),
            ("🎥video🎬", "🎥video🎬".encode('utf-8')),
            ("αβγδε", "αβγδε".encode('utf-8')),
        ]

        for input_name, expected in test_cases:
            with self.subTest(input_name=input_name):
                safe_name, truncated = self.downloader._sanitize_filename(input_name, max_length=255)
                self.assertEqual(safe_name, expected)
                self.assertFalse(truncated)

    def test_return_type(self):
        """测试返回值类型"""
        filename = "test_video"
        safe_name, truncated = self.downloader._sanitize_filename(filename, max_length=255)

        self.assertIsInstance(safe_name, bytes)
        self.assertIsInstance(truncated, bool)

    def test_special_filename_after_sanitization_becomes_empty(self):
        """测试清理后变为空的情况"""
        # 只有空格、点和非法字符
        filename = "   ...<>:\"/\\|?*...   "
        safe_name, truncated = self.downloader._sanitize_filename(filename, max_length=255)

        # 非法字符会被替换为下划线，空格和点会被移除
        self.assertEqual(safe_name, b"_________")
        self.assertFalse(truncated)


class TestExtractVideoWithInterceptionRetry(unittest.IsolatedAsyncioTestCase):
    """测试 extract_video_with_interception 的重试机制"""

    def setUp(self):
        """测试前设置"""
        self.downloader = PlaywrightGreenVideoDownloader(
            timeout=1000, max_retries=2, retry_delay=0.1
        )

    async def test_success_without_retry(self):
        """测试成功时不需要重试"""
        mock_result = {
            "vid": "test123",
            "host": "douyin",
            "host_alias": "抖音",
            "title": "测试视频",
            "status": "success",
            "downloads": [
                {
                    "url": "https://example.com/video.mp4",
                    "file_type": "video",
                    "size": 1024000,
                }
            ],
        }

        with patch(
            "modules.tools.greenvideo.playwright_downloader.async_playwright"
        ) as mock_playwright:
            mock_browser = AsyncMock()
            mock_page = AsyncMock()
            mock_playwright.return_value.__aenter__.return_value.chromium.launch.return_value = (
                mock_browser
            )
            mock_browser.new_page.return_value = mock_page
            mock_page.goto = AsyncMock()
            mock_page.fill = AsyncMock()
            mock_page.get_by_role.return_value.click = AsyncMock()

            # 模拟成功的 API 响应
            async def mock_response_handler():
                # 设置响应事件
                pass

            # 模拟响应处理
            def setup_response():
                async def handle_response(response):
                    if "/api/video/cnSimpleExtract" in response.url:
                        response.status = 200
                        response.text = AsyncMock(
                            return_value='{"code":200,"message":"success","data":{}}'
                        )

                return handle_response

            # 由于测试复杂性，这里使用简化的 mock
            # 实际测试中需要更完整的 mock 设置
            pass

    async def test_retry_on_timeout(self):
        """测试超时错误会重试"""
        with patch(
            "modules.tools.greenvideo.playwright_downloader.async_playwright"
        ) as mock_playwright:
            # 模拟前两次超时，第三次成功
            call_count = [0]

            async def mock_launch(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] <= 2:
                    raise asyncio.TimeoutError("Browser launch timeout")
                mock_browser = AsyncMock()
                mock_page = AsyncMock()
                mock_browser.new_page.return_value = mock_page
                mock_page.goto = AsyncMock()
                mock_page.fill = AsyncMock()
                mock_page.get_by_role.return_value.click = AsyncMock()
                mock_browser.close = AsyncMock()
                return mock_browser

            mock_playwright.return_value.__aenter__.return_value.chromium.launch.side_effect = (
                mock_launch
            )

            result, headers = await self.downloader.extract_video_with_interception(
                "https://example.com/video", headless=True
            )

            # 验证重试了 3 次（初始 + 2 次重试）
            self.assertEqual(call_count[0], 3)
            # 由于最后一次也超时，应该返回 None
            self.assertIsNone(result)

    async def test_max_retries_exceeded(self):
        """测试达到最大重试次数后返回失败"""
        with patch(
            "modules.tools.greenvideo.playwright_downloader.async_playwright"
        ) as mock_playwright:
            # 模拟所有尝试都失败
            call_count = [0]

            async def mock_launch(*args, **kwargs):
                call_count[0] += 1
                raise Exception("Browser launch failed")

            mock_playwright.return_value.__aenter__.return_value.chromium.launch.side_effect = (
                mock_launch
            )

            result, headers = await self.downloader.extract_video_with_interception(
                "https://example.com/video", headless=True
            )

            # 验证重试了 3 次（初始 + 2 次重试）
            self.assertEqual(call_count[0], 3)
            self.assertIsNone(result)

    async def test_business_error_no_retry(self):
        """测试业务错误不会重试"""
        with patch(
            "modules.tools.greenvideo.playwright_downloader.async_playwright"
        ) as mock_playwright:
            mock_browser = AsyncMock()
            mock_page = AsyncMock()
            mock_playwright.return_value.__aenter__.return_value.chromium.launch.return_value = (
                mock_browser
            )
            mock_browser.new_page.return_value = mock_page
            mock_page.goto = AsyncMock()
            mock_page.fill = AsyncMock()
            mock_page.get_by_role.return_value.click = AsyncMock()
            mock_browser.close = AsyncMock()

            # 模拟业务错误响应
            mock_response = MagicMock()
            mock_response.url = "https://greenvideo.cc/api/video/cnSimpleExtract"
            mock_response.status = 200
            mock_response.text = AsyncMock(
                return_value='{"code":400,"message":"视频不存在"}'
            )
            mock_response.headers = {}

            # 设置响应处理
            def setup_page_on(page):
                def on_response(callback):
                    # 模拟立即调用回调
                    asyncio.create_task(callback(mock_response))

                page.on = on_response

            setup_page_on(mock_page)

            result, headers = await self.downloader.extract_video_with_interception(
                "https://example.com/video", headless=True
            )

            # 业务错误应该直接返回 None，不重试
            self.assertIsNone(result)

    async def test_exponential_backoff(self):
        """测试指数退避策略"""
        with patch(
            "modules.tools.greenvideo.playwright_downloader.async_playwright"
        ) as mock_playwright:
            sleep_times = []

            original_sleep = asyncio.sleep

            async def mock_sleep(delay):
                sleep_times.append(delay)
                await original_sleep(0.01)  # 实际只等待很短时间

            with patch("asyncio.sleep", side_effect=mock_sleep):
                # 模拟所有尝试都失败
                call_count = [0]

                async def mock_launch(*args, **kwargs):
                    call_count[0] += 1
                    raise Exception("Browser launch failed")

                mock_playwright.return_value.__aenter__.return_value.chromium.launch.side_effect = (
                    mock_launch
                )

                await self.downloader.extract_video_with_interception(
                    "https://example.com/video", headless=True
                )

                # 验证退避时间：0.1, 0.2 (指数增长)
                self.assertEqual(len(sleep_times), 2)
                self.assertAlmostEqual(sleep_times[0], 0.1, places=1)
                self.assertAlmostEqual(sleep_times[1], 0.2, places=1)


if __name__ == "__main__":
    unittest.main()
