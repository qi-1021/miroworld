"""
t9 文件格式支持测试：

验证 FileParser 对 docx/html/htm/epub/odt/rtf 的文本提取（纯 stdlib），
并确认 Config.ALLOWED_EXTENSIONS 与前端 accept 同步。
"""
import os
import zipfile

import pytest

from app.config import Config
from app.utils.file_parser import FileParser


def _write(path: str, content: str) -> str:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


@pytest.fixture()
def tmp(tmp_path):
    return tmp_path


# ---------------------------------------------------------------------------
# 各格式 fixture 构建
# ---------------------------------------------------------------------------
def _make_docx(path: str) -> str:
    from io import BytesIO
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr(
            'word/document.xml',
            '<w:document xmlns:w="urn:o"><w:body>'
            '<w:p><w:r><w:t>第一章 开始</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>天气很好，我们出发。</w:t></w:r></w:p>'
            '</w:body></w:document>',
        )
    with open(path, 'wb') as f:
        f.write(buf.getvalue())
    return path


def _make_html(path: str, htm_alt: bool = False) -> str:
    content = (
        '<html><head><title>潜伏标题</title><style>p{color:red}</style></head>'
        '<body><h1>大标题</h1><p>第一段正文内容。</p>'
        '<script>var x=1;</script><p>第二段正文。</p></body></html>'
    )
    return _write(path, content)


def _make_epub(path: str) -> str:
    from io import BytesIO
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip')
        z.writestr('OEBPS/ch1.xhtml', '<html><body><p>第一章内容。</p></body></html>')
        z.writestr('OEBPS/ch2.xhtml', '<html><body><p>第二章内容。</p></body></html>')
    with open(path, 'wb') as f:
        f.write(buf.getvalue())
    return path


def _make_odt(path: str) -> str:
    from io import BytesIO
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('mimetype', 'application/vnd.oasis.opendocument.text')
        z.writestr(
            'content.xml',
            '<office:document-content xmlns:text="urn:o">'
            '<office:body><office:text>'
            '<text:p>段落一。</text:p><text:p>段落二。</text:p>'
            '</office:text></office:body></office:document-content>',
        )
    with open(path, 'wb') as f:
        f.write(buf.getvalue())
    return path


def _make_rtf(path: str) -> str:
    rtf = (r'{\rtf1\ansi\deff0{\fonttbl{\f0 Arial;}}\f0 '
           r'Hello \b bold\b0 world!\par Second line.\par}')
    with open(path, 'w', encoding='latin-1') as f:
        f.write(rtf)
    return path


# ---------------------------------------------------------------------------
# 1. 各新格式提取
# ---------------------------------------------------------------------------
class TestNewFormats:
    def test_docx(self, tmp):
        p = _make_docx(str(tmp / 'a.docx'))
        text = FileParser.extract_text(p)
        assert '第一章 开始' in text
        assert '天气很好' in text

    def test_html(self, tmp):
        p = _make_html(str(tmp / 'b.html'))
        text = FileParser.extract_text(p)
        assert '第一段正文内容' in text
        assert '第二段正文' in text
        # script/style 内容不进入正文
        assert 'var x' not in text
        assert 'red}' not in text

    def test_htm_alias(self, tmp):
        p = _make_html(str(tmp / 'c.htm'), htm_alt=True)
        text = FileParser.extract_text(p)
        assert '第一段正文内容' in text

    def test_epub(self, tmp):
        p = _make_epub(str(tmp / 'd.epub'))
        text = FileParser.extract_text(p)
        assert '第一章内容' in text
        assert '第二章内容' in text

    def test_odt(self, tmp):
        p = _make_odt(str(tmp / 'e.odt'))
        text = FileParser.extract_text(p)
        assert '段落一' in text
        assert '段落二' in text

    def test_rtf(self, tmp):
        p = _make_rtf(str(tmp / 'f.rtf'))
        text = FileParser.extract_text(p)
        # 控制字/字体表被剥离，正文保留
        assert 'Second line' in text
        assert 'fonttbl' not in text
        assert '\\par' not in text


# ---------------------------------------------------------------------------
# 2. 扩展名/支持集一致性与校验
# ---------------------------------------------------------------------------
class TestExtensions:
    def test_supported_extensions_include_new(self):
        for ext in ('docx', 'html', 'htm', 'epub', 'odt', 'rtf'):
            assert f'.{ext}' in FileParser.SUPPORTED_EXTENSIONS

    def test_config_allowed_extensions_include_new(self):
        for ext in ('docx', 'html', 'htm', 'epub', 'odt', 'rtf'):
            assert ext in Config.ALLOWED_EXTENSIONS

    def test_allowed_matches_supported(self):
        # Config 不带点集合 与 FileParser 带点集合 对齐
        for dot_ext in FileParser.SUPPORTED_EXTENSIONS:
            assert dot_ext.lstrip('.') in Config.ALLOWED_EXTENSIONS

    def test_unsupported_raises_value_error(self, tmp):
        p = _write(str(tmp / 'x.zzz'), 'not a known type')
        with pytest.raises(ValueError):
            FileParser.extract_text(p)

    def test_missing_file_raises_not_found(self, tmp):
        with pytest.raises(FileNotFoundError):
            FileParser.extract_text(str(tmp / 'nope.txt'))

    def test_supported_extensions_case_insensitive(self, tmp):
        p = _make_html(str(tmp / 'UPPER.HTML'))
        # 重命名后后缀大写仍可解析
        os.rename(p, str(tmp / 'UPPER.HTML'))
        assert '第一段正文内容' in FileParser.extract_text(str(tmp / 'UPPER.HTML'))


# ---------------------------------------------------------------------------
# 3. 原格式不回归
# ---------------------------------------------------------------------------
class TestLegacyFormats:
    def test_txt(self, tmp):
        p = _write(str(tmp / 'plain.txt'), '纯文本内容。')
        assert '纯文本内容' in FileParser.extract_text(p)

    def test_md(self, tmp):
        p = _write(str(tmp / 'doc.md'), '# 标题\n正文')
        assert '标题' in FileParser.extract_text(p)

    def test_markdown_alias(self, tmp):
        p = _write(str(tmp / 'doc.markdown'), 'markdown 正文')
        assert 'markdown 正文' in FileParser.extract_text(p)

    def test_extract_from_multiple(self, tmp):
        t1 = _write(str(tmp / 'a.txt'), '甲')
        t2 = _write(str(tmp / 'b.md'), '乙')
        bad = _write(str(tmp / 'c.zzz'), 'x')
        out = FileParser.extract_from_multiple([t1, t2, bad])
        assert '甲' in out and '乙' in out
        assert '提取失败' in out


# ---------------------------------------------------------------------------
# 4. 非法压缩容器 / 畸形文件不崩
# ---------------------------------------------------------------------------
class TestMalformed:
    def test_docx_bad_zip(self, tmp):
        # 扩展名 docx 但非 zip 容器
        p = _write(str(tmp / 'bad.docx'), 'not a zip')
        with pytest.raises(ValueError):
            FileParser.extract_text(p)

    def test_odt_bad_zip(self, tmp):
        p = _write(str(tmp / 'bad.odt'), 'not a zip')
        with pytest.raises(ValueError):
            FileParser.extract_text(p)

    def test_epub_bad_zip(self, tmp):
        p = _write(str(tmp / 'bad.epub'), 'not a zip')
        with pytest.raises(ValueError):
            FileParser.extract_text(p)

    def test_rtf_garbage_does_not_crash(self, tmp):
        # 畸形 RTF：仅含大量控制字也能产出文本（空串也接受，不抛异常）
        p = _write(str(tmp / 'g.rtf'), '{\\rtf1\\ansi\\b\\i\\f0 x}')
        assert isinstance(FileParser.extract_text(p), str)
