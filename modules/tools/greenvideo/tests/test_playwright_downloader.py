"""
单元测试 - PlaywrightGreenVideoDownloader._sanitize_filename
"""

import unittest
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


if __name__ == "__main__":
    unittest.main()
