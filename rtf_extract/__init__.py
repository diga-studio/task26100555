"""流式 RTF 正文提取库。

上层按任意字节片段送入 RTF 数据，已解析出的正文以 Unicode 文本返回。
全部处理状态仅保存在内存中。
"""

from .parser import RtfParser

__all__ = ["RtfExtractor"]


class RtfExtractor:
    """流式 RTF 正文提取器。

    用法::

        ex = RtfExtractor()
        ex.feed(chunk1)
        ex.feed(chunk2)
        text = ex.get_text()
        ex.finish()
        text = ex.get_text()
    """

    def __init__(self) -> None:
        self._parser = RtfParser()

    def feed(self, data: bytes) -> None:
        """送入一段 RTF 原始字节，可在任意字节处断开。"""
        self._parser.feed(data)

    def get_text(self) -> str:
        """返回到目前为止已产生的正文文本（不清空内部状态）。"""
        return self._parser.get_text()

    def finish(self) -> str:
        """结束导入，冲刷内部缓冲并返回全部正文。"""
        self._parser.finish()
        return self._parser.get_text()
