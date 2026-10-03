# task26100555

## rtf_text — 流式 RTF 正文提取库

面向无障碍阅读器：从照护者提供的 RTF 材料中提取可朗读的 Unicode 正文，
隐藏文字、图片数据、超链接指令等不会混入输出。处理状态全部保存在内存中。

### 用法

```python
from rtf_text import RtfTextExtractor

ext = RtfTextExtractor()
ext.feed(chunk1)          # bytes，可在任意字节处断开
ext.feed(chunk2)
print(ext.get_text())     # 已产生的正文
text = ext.finish()       # 结束导入，返回完整正文
```

### 支持的 RTF 子集

- 嵌套分组 `{...}`；`\uc`、`\v` 等设置随分组恢复。
- 控制词：字母 + 可选有符号整数参数；紧随的单个空格为分隔符。
- 字符转义 `\\`、`\{`、`\}` 输出字符本身；原始 CR/LF 忽略。
- `\ansicpg` 指定文档编码（仅 1252 / 936，默认 1252）；
  相邻 `\'hh` 转义字节按文档编码组字（如两个 GBK 字节还原一个汉字）。
- `\uN` 输出 UTF-16 码元，合法代理对合成一个码点；
  `\ucN` 指定每个 `\u` 后的回退项个数（默认 1）。
- `fonttbl`/`colortbl`/`stylesheet`/`info`/`pict`/`object`/`fldinst`
  目的地分组及 `{\* ...}` 分组整组忽略；`fldrslt` 正常输出。
- `\v` / `\v0` 开启/取消隐藏；`\binN` 跳过 N 个原始字节（忽略分组内同样生效）。
- `\par`、`\line` 输出换行，`\tab` 输出制表符；未列出的字母控制词忽略。

### 测试

```bash
python3 -m pytest tests/ -q
```
