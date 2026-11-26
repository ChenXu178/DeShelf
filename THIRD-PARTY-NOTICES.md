# 第三方组件与许可声明 · Third-Party Notices

卷帙 DeShelf（下称"本软件"）由 © 2026 永远的兰兰 (Lanlan Eternal) 以 MIT License 发布，
完整许可文本见仓库根目录的 [LICENSE](LICENSE)。本文件列出本软件使用或参考的第三方组件，
以及它们各自的许可与使用范围。

> 一句话版本：**本软件不打包、不分发任何书籍内容、字体文件或商业素材。**
> 所有第三方组件均按其原许可使用，未做与本软件许可冲突的再授权。

---

## 一、桌面版（Windows EXE / Python 源码）

### 运行时组件（随 EXE 一并打包）

| 组件 | 版本 | 用途 | 许可 |
|---|---|---|---|
| Python | 3.15 | 运行时 | PSF License Agreement |
| Tcl/Tk（tkinter） | 9.0 | 图形界面 | BSD-style License（Tcl/Tk License） |
| Pillow（PIL） | 13.x | 封面绘制与格式转码、主题缩略图（ImageTk） | MIT-CMU License |
| html2image | 2.0.x | 调用本机浏览器，把版面 CSS 渲成预览图 | MIT License |
| requests、websocket-client | 2.x / 1.x | html2image 的依赖 | Apache License 2.0 |
| urllib3、charset-normalizer | 2.x / 3.x | 上述依赖的间接依赖 | MIT License |
| certifi | 2026.x | 上述依赖的间接依赖（CA 证书包） | MPL-2.0 |
| idna | 3.x | 上述依赖的间接依赖 | BSD-3-Clause License |

### 构建期组件（只在打包时使用，不参与运行逻辑）

| 组件 | 版本 | 用途 | 许可 |
|---|---|---|---|
| PyInstaller | 6.x | 打包为单文件 EXE | GPL-2.0 with bootloader exception |

### 简繁比对数据（静态数据，不含第三方源码）

| 数据 | 来源 | 用途 | 许可 |
|---|---|---|---|
| 繁→简单字对照表 | OpenCC `TSCharacters.txt`（3,221 对） | 判断两行是否同一段文字，**不改写正文** | Apache License 2.0 |
| zh2Hans 单字表 | zhconv 1.4.3（547 对） | 补齐常用字映射，同上用途 | GPL-2.0-or-later |

说明：

- PyInstaller 的 **bootloader exception** 明确允许用其打包的程序以任意许可（含闭源、含 MIT）分发，
  因此 EXE 不受 GPL 传染。
- Pillow 在「生成内置封面」「读取/转码同名封面图」「显示主题缩略图」时被调用；
  缺 Pillow 时程序照常运行，只是导出的 EPUB 不带生成的封面。
- html2image 只在打开「选择版面主题」时用到；截图由**你本机已安装的** Chrome / Edge / Chromium
  完成，**本软件不打包、不分发任何浏览器**。本机没有这类浏览器时该窗口会提示安装，其余功能不受影响。
- 简繁对照表以静态字符数据内联（仅比对用）。其中 zhconv 的 547 对为 GPL-2.0-or-later 字表数据；
  若要完全避开 GPL，可只保留 OpenCC 部分，去重命中率会略降。

## 二、网页版（单文件 HTML）

网页版不依赖任何 CDN 或运行时库，所有代码内联在同一个 `.html` 文件里。

| 组件 | 用途 | 许可 |
|---|---|---|
| OpenCC 繁→简对照表（3,221 对） | 简繁重复行的**比对**（仅判断两行是否同一段，**不改写正文**） | Apache License 2.0 |
| zhconv zh2Hans 字表（547 对） | 同上，补齐常用字映射 | GPL-2.0-or-later |
| 不蒜子（Busuanzi）访问计数器 | 仅统计页面访问次数（可选加载） | 第三方服务 |

- 对照表以静态数据形式内联，不含 OpenCC / zhconv 的源码或可执行程序。
- 除访问计数脚本外，网页版**不加载** Google Fonts 等任何第三方资源；离线打开时计数器不请求，
  功能不受影响。
- 联网只在你主动触发时发生：勾选「插图链接校验」逐条读响应头、「封面 → 下载网络封面」取一张图；
  正文不会离开浏览器。
- 封面与正文使用**系统自带字体**（Windows 上为楷体 `simkai.ttf`），
  **本软件不打包、不分发任何字体文件**。

## 三、未使用的技术与素材（明确声明）

为避免误解，以下内容**没有**被使用：

- 没有内置任何字体文件（楷体、宋体等均为调用系统字体）；
- 没有内置任何浏览器（主题预览调用本机已安装的 Chrome / Edge / Chromium）；
- 没有内置任何图片素材（封面由图元自绘，或直接使用用户自己目录里的同名图片）；
- 没有内置任何书籍正文、样例章节或受版权保护的文本；
- 不含任何后台或隐蔽的网络请求：联网只发生在你主动勾选的插图链接校验 / 插图下载、
  主动填写的网络封面链接，以及网页版可选的访问计数器。

## 四、如果你的使用场景需要更宽松/更严格的条款

- 想**闭源分发**：MIT 允许，但必须保留 `Copyright (c) 2026 Lanlan Eternal` 与 LICENSE 全文，
  且不能把作者改成自己的名字后声称原创；
- 想**用于商业产品**：同样允许，无需付费、无需事先告知，但仍需保留署名与许可文本；
- 想**移除署名后分发**：这是 MIT 唯一禁止的事，请勿这样做。

---

© 2026 永远的兰兰 · Lanlan Eternal · MIT License
