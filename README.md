# task26100555
流式 RTF 正文提取库。

## 用法

```python
from rtf_extract import RtfExtractor

ex = RtfExtractor()
ex.feed(chunk1)          # bytes，可在任意字节处断开
ex.feed(chunk2)
print(ex.get_text())     # 到目前已产生的正文
text = ex.finish()       # 结束导入并返回全部正文
```

- 仅处理题目约定的 RTF 子集；未列出的字母控制词忽略。
- 支持 `\ansicpg` 1252 / 936（默认 1252）、`\'hh`、`\\` `\{` `\}`、
  `\uN`（含代理对合成）、`\ucN` 回退跳过、`\v` / `\v0` 隐藏、
  `\par` `\line` `\tab`、`\binN` 原始字节跳过，
  以及 fonttbl / colortbl / stylesheet / info / pict / object / fldinst
  目的地分组与 `\*` 可忽略分组（fldrslt 正文正常输出）。
- 全部状态仅保存在内存中，逐字节输入与整份输入结果一致。

## 测试

```sh
python3 -m pytest tests/ -q
```
