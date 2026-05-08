from modules.plugins.greenvideo_plugin.greenvideo_plugin import _strip_tags


class TestStripTags:
    def test_strips_tags_at_end(self):
        assert _strip_tags("我羡路人皆得见，卿身侧畔自寻常。#手写 #诗词") == "我羡路人皆得见，卿身侧畔自寻常。"

    def test_no_tags_unchanged(self):
        assert _strip_tags("普通标题") == "普通标题"

    def test_tags_only_returns_original(self):
        assert _strip_tags("#手写 #诗词") == "#手写 #诗词"

    def test_empty_string(self):
        assert _strip_tags("") == ""

    def test_whitespace_after_tags(self):
        assert _strip_tags("  标题内容  #tag1 #tag2  ") == "标题内容"

    def test_tags_at_beginning_content_at_end(self):
        assert (
            _strip_tags("#手写 #诗词 我羡路人皆得见，卿身侧畔自寻常。")
            == "#手写 #诗词 我羡路人皆得见，卿身侧畔自寻常。"
        )

    def test_tags_in_middle_preserved(self):
        assert _strip_tags("标题#tag中间#结尾") == "标题"
