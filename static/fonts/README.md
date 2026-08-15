# 中文字体目录

本目录用于放置**开源许可（OFL / Apache 2.0）**的中文字体，供 Word 转 PDF
（`tools/word_to_pdf`）与 PDF 加水印（`tools/pdf_watermark`）在渲染 PDF 时
优先加载，避免服务器缺少中文字体导致输出乱码。

## 推荐字体

- **Noto Sans SC**（思源黑体，SIL OFL 1.1 许可）：
  `https://fonts.google.com/noto/specimen/Noto+Sans+SC`
  下载 Regular 字重后重命名为 `NotoSansSC-Regular.ttf` 放入本目录。

## 部署说明

- 项目代码按以下顺序查找字体，**第一个存在的即使用**：

  1. `static/fonts/NotoSansSC-Regular.ttf`（本目录，随仓库分发，推荐）
  2. `C:/Windows/Fonts/msyh.ttc` / `simhei.ttf` / `simsun.ttc`（Windows 开发机）
  3. `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`（Linux，安装 `fonts-noto-cjk`）
  4. `/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc`（Linux，安装 `fonts-wqy-zenhei`）
  5. `/System/Library/Fonts/PingFang.ttc`（macOS）

- Linux 生产服务器如不方便提交字体文件，安装系统包即可：

  ```bash
  sudo apt install -y fonts-noto-cjk
  ```

  验证：`fc-list | grep -i noto`。

## 许可提醒

不要将微软雅黑（msyh）、宋体（SimSun）等**专有字体**复制进本目录分发——
它们有商业许可限制，只能作为开发机上的运行时查找候选（代码中已有）。
