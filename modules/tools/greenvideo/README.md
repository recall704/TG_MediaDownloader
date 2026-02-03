

## 安装依赖

```bash
uv add patchright
uv run patchright install chromium
```


## 单元测试

```bash
uv run python -m pytest modules/tools/greenvideo/tests/test_playwright_downloader.py -v
```
