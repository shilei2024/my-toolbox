# 发票小程序视觉修订 V3（2026-11-13）

## 当前方向

用户否定上一版配色与过于简单的票据勾选 Logo。本版改为石灰白页面、梅灰操作色与铜色点缀；Logo 改用折纸构成的立体票夹徽记，增加层次与辨识度。

| 用途 | 色值 |
| --- | --- |
| 页面 | #F4F1ED |
| 正文 | #302B33 |
| 辅助文字 | #716975 |
| 主按钮与导航选中 | #514054 |
| 汇总卡渐层 | #352C3E → #504052 |
| 汇总卡辅助文字 | #E4DAE3 |
| 装饰点缀 | #BA9879 |

视觉范围仅涉及小程序样式、导航图标与 Logo；接口、网站、数据库、权限与业务规则不变。复用现有共享样式和图标脚本，无新依赖或服务成本，沿用微信发布流程与上一版本回退。模块 Logo 不改变平台品牌，符合现有架构边界。

## 资源

当前 Logo：`apps/invoice-miniprogram/assets/logo-v3.png`。V1/V2 在 `docs/product/assets/` 保留，不进入当前小程序包。使用内置 image_gen 重新生成，不宣称工具未公开的模型版本。后台账号头像需管理员单独上传。

### 完整提示词

Design a refined, distinctive premium app icon for an invoice organization assistant. Single square finished icon, no mockups or text. Art direction: an architectural folded-paper monogram, three interlocking wide folded ribbons forming an elegant upright folio/ledger silhouette with a diamond-shaped negative space in the center. Deliberate asymmetry, clever continuous folding structure, approximately 4 broad planes and clean precise beveled edges; expressive silhouette, intentional visual detail without clutter. Warm porcelain ivory front surfaces, muted brushed bronze fold edges, muted mauve shaded side planes; deep smoky aubergine graphite background (#352C3E). Sculptural shallow relief, restrained soft studio light, sophisticated editorial identity, tactile matte ceramic and paper, very subtle shadows; absolutely no glossy plastic, no jewel, no bright metallic shine, no heraldry. Related to organizing and collecting paper records through folding geometry, NOT a literal receipt with printed lines, NOT a checkmark, NOT a money sign, NOT a shopping bag. Full-bleed solid aubergine square, centered emblem occupies 64 percent of canvas, ample safe margin for circular crop. Legible at 48 pixels with rich craft at full resolution. Single image, one symbol, no text, no letters, no watermark, no frame.

## 验收

检查主要文字在暖白、白色及渐层最浅端的对比度，核对资源引用与源码目录体积。微信真机视觉、圆形裁切及小尺寸识别验收待完成，尚未发布。视觉修改不扩大业务回归范围；前一轮 9 项测试结果仅对应前一轮，不能替代本版真机验收。
