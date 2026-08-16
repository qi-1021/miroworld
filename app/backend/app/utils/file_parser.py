"""
文件解析工具
支持PDF、Markdown、TXT、DOCX、HTML/HTM、EPUB、ODT、RTF 文件的文本提取。

- PDF：依赖 PyMuPDF（fitz）
- DOCX / EPUB / ODT：zipfile + XML（Word/EPUB/ODF 都是 OPC/zip 容器）
- HTML / HTM：HTMLParser（纯 stdlib，忽略 script/style 等标签）
- RTF：正则提取（处理控制字 \\par \\line 等）
"""

import io
import os
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree as ET


class FileParser:
    """文件解析器"""

    SUPPORTED_EXTENSIONS = {
        '.pdf', '.md', '.markdown', '.txt',
        '.docx', '.html', '.htm', '.epub', '.odt', '.rtf',
    }

    @classmethod
    def extract_text(cls, file_path: str) -> str:
        """
        从文件中提取文本

        Args:
            file_path: 文件路径

        Returns:
            提取的文本内容
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        suffix = path.suffix.lower()

        if suffix not in cls.SUPPORTED_EXTENSIONS:
            raise ValueError(f"不支持的文件格式: {suffix}")

        if suffix == '.pdf':
            return cls._extract_from_pdf(file_path)
        elif suffix in {'.md', '.markdown'}:
            return cls._extract_from_md(file_path)
        elif suffix == '.txt':
            return cls._extract_from_txt(file_path)
        elif suffix == '.docx':
            return cls._extract_from_docx(file_path)
        elif suffix in {'.html', '.htm'}:
            return cls._extract_from_html(file_path)
        elif suffix == '.epub':
            return cls._extract_from_epub(file_path)
        elif suffix == '.odt':
            return cls._extract_from_odt(file_path)
        elif suffix == '.rtf':
            return cls._extract_from_rtf(file_path)

        raise ValueError(f"无法处理的文件格式: {suffix}")

    # ------------------------------------------------------------------
    # 各格式提取实现
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_from_pdf(file_path: str) -> str:
        """从PDF提取文本"""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("需要安装PyMuPDF: pip install PyMuPDF")

        text_parts = []
        with fitz.open(file_path) as doc:
            for page in doc:
                text = page.get_text()
                if text.strip():
                    text_parts.append(text)

        return "\n\n".join(text_parts)

    @staticmethod
    def _extract_from_md(file_path: str) -> str:
        """从Markdown提取文本"""
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()

    @staticmethod
    def _extract_from_txt(file_path: str) -> str:
        """从TXT提取文本"""
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()

    @staticmethod
    def _read_bytes(path: str) -> bytes:
        """读取文件字节（PDF/压缩容器用）"""
        with open(path, 'rb') as f:
            return f.read()

    @staticmethod
    def _strip_xml_tags(xml_bytes: bytes) -> str:
        """把一段 XML 文本（去掉声明后）按标签内容拼成文本。"""
        try:
            root = ET.fromstring(xml_bytes)
            return _ET_text(root)
        except Exception:
            # 兜底：直接去掉标签标签
            return re.sub(r'<[^>]+>', '\n', xml_bytes.decode('utf-8', 'ignore'))

    @staticmethod
    def _clean_paragraphs(text: str) -> str:
        """折叠因段落/标签标记产生的连续空行与首尾空白。"""
        text = re.sub(r'\n\s*\n+', '\n', text)
        return text.strip()

    # ---- DOCX（OOXML：zip 容器，正文在 word/document.xml）----
    @staticmethod
    def _extract_from_docx(file_path: str) -> str:
        data = FileParser._read_bytes(file_path)
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise ValueError("不是有效的 DOCX 文件（zip 容器无效）")

        # 正文：word/document.xml；段落 <w:p> 换行，制表 <w:tab> 处理
        with z.open('word/document.xml') as f:
            xml_bytes = f.read()
        xml_bytes = xml_bytes\
            .replace(b'<w:tab/>', b'\t')\
            .replace(b'<w:tab />', b'\t')\
            .replace(b'<w:br/>', b'\n')\
            .replace(b'<w:br />', b'\n')\
            .replace(b'</w:p>', b'\n')
        return FileParser._clean_paragraphs(FileParser._strip_xml_tags(xml_bytes))

    # ---- HTML / HTM ----
    @staticmethod
    def _extract_from_html(file_path: str) -> str:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            html = f.read()
        parser = _HTMLTextParser()
        try:
            parser.feed(html)
        except Exception:
            # 极端畸形 HTML 兜底
            return re.sub(r'<[^>]+>', ' ', html)
        return parser.get_text()

    # ---- EPUB（zip 容器，正文为 *.xhtml / *.html）----
    @staticmethod
    def _extract_from_epub(file_path: str) -> str:
        data = FileParser._read_bytes(file_path)
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise ValueError("不是有效的 EPUB 文件（zip 容器无效）")

        names = z.namelist()
        # 排序：优先按容器内 spined 顺序读取；没有明确 order 时按文件名稳定排序
        parts = []
        for name in names:
            low = name.lower()
            if not (low.endswith('.xhtml') or low.endswith('.html') or low.endswith('.htm')):
                continue
            with z.open(name) as f:
                html = f.read().decode('utf-8', 'ignore')
            parts.append(FileParser._html_to_text(html))
        return "\n\n".join(p for p in parts if p.strip())

    # ---- ODT（zip 容器，正文在 content.xml）----
    @staticmethod
    def _extract_from_odt(file_path: str) -> str:
        data = FileParser._read_bytes(file_path)
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise ValueError("不是有效的 ODT 文件（zip 容器无效）")

        try:
            with z.open('content.xml') as f:
                xml_bytes = f.read()
        except KeyError:
            raise ValueError("ODT 缺少 content.xml")

        # <text:p>/<text:h> 是段落/标题分隔
        xml_bytes = xml_bytes\
            .replace(b'</text:p>', b'\n')\
            .replace(b'</text:h>', b'\n')
        return FileParser._clean_paragraphs(FileParser._strip_xml_tags(xml_bytes))

    # ---- RTF（正则提取控制字）----
    @staticmethod
    def _extract_from_rtf(file_path: str) -> str:
        # RTF 是 7-bit 风格文本，非 ASCII 用 \'xx / \uN 转义；以 latin-1 读入保证字节无损，
        # 再由 _rtf_to_text 解码转义序列。
        with open(file_path, 'r', encoding='latin-1') as f:
            rtf = f.read()
        return _rtf_to_text(rtf)

    @staticmethod
    def _html_to_text(html: str) -> str:
        parser = _HTMLTextParser()
        try:
            parser.feed(html)
        except Exception:
            return re.sub(r'<[^>]+>', ' ', html)
        return parser.get_text()

    # ------------------------------------------------------------------
    # 多文件
    # ------------------------------------------------------------------
    @classmethod
    def extract_from_multiple(cls, file_paths: List[str]) -> str:
        """
        从多个文件提取文本并合并

        Args:
            file_paths: 文件路径列表

        Returns:
            合并后的文本
        """
        all_texts = []

        for i, file_path in enumerate(file_paths, 1):
            try:
                text = cls.extract_text(file_path)
                filename = Path(file_path).name
                all_texts.append(f"=== 文档 {i}: {filename} ===\n{text}")
            except Exception as e:
                all_texts.append(f"=== 文档 {i}: {file_path} (提取失败: {str(e)}) ===")

        return "\n\n".join(all_texts)


# ---------------------------------------------------------------------------
# HTML 文本提取（纯 stdlib，忽略 script/style/nav 等非正文标签）
# ---------------------------------------------------------------------------
class _HTMLTextParser(HTMLParser):
    """提取 HTML 可读文本，段落/块级标签换行，忽略 script/style。"""

    _BLOCK_TAGS = {
        'p', 'div', 'br', 'li', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'tr', 'table', 'section', 'article', 'header', 'footer', 'blockquote',
    }
    _SKIP_TAGS = {'script', 'style', 'head', 'title', 'meta', 'link', 'noscript'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS and self._skip_depth == 0:
            self._parts.append('\n')

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self._BLOCK_TAGS and self._skip_depth == 0:
            self._parts.append('\n')

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        text = ''.join(self._parts)
        # 折叠因块级标签产生的多余空行
        text = re.sub(r'\n\s*\n', '\n', text)
        text = re.sub(r'[ \t]+\n', '\n', text)
        text = re.sub(r'\n[ \t]+', '\n', text)
        return text.strip()


def _ET_text(elem: ET.Element):
    """递归拼接 ElementTree 元素文本，保留显式插入的 \\n。"""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_ET_text(child))
        if child.tail:
            parts.append(child.tail)
    return ''.join(parts)


# ---------------------------------------------------------------------------
# RTF 文本提取（正则：去控制字，保留可见字符与段落）
# ---------------------------------------------------------------------------
# 元数据/样式目的地（{\<dest> ... }）应整组丢弃（fonttbl/colortbl/…）
_RTF_SKIP_DESTS = {
    'fonttbl', 'colortbl', 'stylesheet', 'info', 'creatim', 'revtim',
    'printim', 'generator', 'comment', 'pict', 'footer', 'footerf',
    'footerl', 'footerr', 'header', 'headerf', 'headerl', 'headerr',
    'themedata', 'colorschememapping', 'latentstyles', 'listtable',
    'listoverridetable', 'datastore', 'rsidtbl', 'stylesheet',
}
# RTF 转义：\\xxx 为十六进制，重音符 \{ \} \\ 等为字面量；\uNNNN? 为 unicode。
_RTF_UNICODE = re.compile(r'\\u(-?\d+)\s?')
_RTF_HEX = re.compile(r"\\'([0-9a-fA-F]{2})")
_RTF_CONTROL = re.compile(r'\\[a-zA-Z]+-?\d*( ?|\*)')
_RTF_SPECIAL = re.compile(r'\\([\\{}])')
_RTF_PAR = re.compile(r'\\par[db]? ?|\\line ?|\\page\b|\\pard ?|\\~')
_RTF_GROUP = re.compile(r'[{}]')


def _rtf_remove_dest_groups(text: str) -> str:
    """移除形如 {\\dest ...} 的元数据/样式目的地组（处理嵌套花括号）。

    返回移除了这些分组的新字符串，其余原样保留。
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == '{' and i + 1 < n and text[i + 1] == '\\':
            # 读取控制字，判断是否命中跳过目的地
            j = i + 2
            while j < n and text[j].isalpha():
                j += 1
            dest = text[i + 2:j]
            if dest in _RTF_SKIP_DESTS:
                # 找到配对的 }（处理嵌套 { }）
                depth = 1
                k = j
                while k < n and depth > 0:
                    if text[k] == '{':
                        depth += 1
                    elif text[k] == '}':
                        depth -= 1
                    k += 1
                i = k  # 跳过整个组
                continue
            out.append(text[i])
            i += 1
        else:
            out.append(text[i])
            i += 1
    return ''.join(out)


def _rtf_decode_hex(match):
    try:
        return chr(int(match.group(1), 16))
    except ValueError:
        return ''


def _rtf_to_text(rtf: str) -> str:
    text = rtf or ''
    # 1) 丢弃 RTF 头部关键字与元数据目的地组
    text = re.sub(r'\{\\rtf1?\d?[^ {}\n]* ?', '', text, count=1)
    text = _rtf_remove_dest_groups(text)
    # 2) 段落 / 换行控制字 → 换行
    text = _RTF_PAR.sub('\n', text)
    # 3) unicode 控制字 \uNNNN? → 对应字符（\ucN 的 fallback 记号一并丢弃）
    text = re.sub(r'\\uc\d+', '', text)
    text = _RTF_UNICODE.sub(lambda m: _safe_chr(int(m.group(1))), text)
    # 4) 十六进制 \'xx → 字符（latin-1）
    text = _RTF_HEX.sub(_rtf_decode_hex, text)
    # 5) 一般控制字（\word, \wordN, 可选空格/星号）
    text = _RTF_CONTROL.sub('', text)
    # 6) 保留字面量 \{ \} \\  → { } \
    text = _RTF_SPECIAL.sub(lambda m: m.group(1), text)
    # 7) 去掉剩余花括号（结构组只留内容）
    text = _RTF_GROUP.sub('', text)
    # 8) 折叠多余空格 / 连续空行
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'[ \t]+$', '', text, flags=re.M)
    text = re.sub(r'\n\s*\n', '\n', text)
    return text.strip()


def _safe_chr(code: int) -> str:
    try:
        return chr(code)
    except (ValueError, OverflowError):
        return ''


def split_text_into_chunks(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50
) -> List[str]:
    """
    将文本分割成小块

    Args:
        text: 原始文本
        chunk_size: 每块的字符数
        overlap: 重叠字符数

    Returns:
        文本块列表
    """
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        # 尝试在句子边界处分割
        if end < len(text):
            # 查找最近的句子结束符
            for sep in ['。', '！', '？', '.\n', '!\n', '?\n', '\n\n', '. ', '! ', '? ']:
                last_sep = text[start:end].rfind(sep)
                if last_sep != -1 and last_sep > chunk_size * 0.3:
                    end = start + last_sep + len(sep)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # 下一个块从重叠位置开始
        start = end - overlap if end < len(text) else len(text)

    return chunks
