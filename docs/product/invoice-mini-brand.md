# 发票小程序配色与 Logo（2026-11-12，历史方案）

此方案已被用户否定，由 [V3 视觉修订](invoice-mini-brand-v3.md) 替代。

## 设计决策

采用深墨蓝、暖白与香槟金。主按钮 #243E62，汇总卡 #172B4D，页面背景 #F5F4F0，正文 #1D2939，辅助文字 #667085，点缀 #C6A66A。金色不用于浅底小字；成功和错误保留语义颜色。

仅更新小程序视觉，不改网站、业务接口、权限或数据库。共享样式及导航图标生成脚本可复用；原生组件方案不引入依赖或运行成本，部署沿用微信开发者工具，符合现有架构。Logo 的票据语义属于发票模块，不放入平台通用品牌。

## Logo

- 使用内置 image_gen，通过 imagegen 技能生成；工具未公开具体模型版本。
- 成品：`apps/invoice-miniprogram/assets/logo-v2.png`，已接入首页、发票页和我的页面。
- 历史 Logo 移至 `docs/product/assets/invoice-logo-v1.png`，避免旧大图继续占用小程序包体积。
- 微信后台账号头像需要管理员另行上传，本地资源更新不等于后台头像更新。
- 底部导航使用独立的代码绘制图标，运行 `scripts/design/generate-invoice-tabs.ps1` 可重建；未使用生成式 Logo 代替功能图标。

### 完整生成提示词

Create one production-ready square app icon for a Chinese invoice and reimbursement assistant. logo-brand. Sophisticated restrained Swiss graphic design. Full bleed solid midnight ink navy background #172B4D, no outer rounded corner masking (platform crops it). One large centered warm ivory receipt/document silhouette, softly rounded upper corners and a very subtle two-notch receipt base, with a bold geometric checkmark integrated into the lower right in muted champagne gold #C6A66A. Two short navy horizontal lines within the document suggest invoice entries. Flat vector-like crisp geometry, balanced optical weight, generous 20 percent safe margin, instantly legible at 32px. Calm professional premium productivity brand, not a banking crest. Exactly one icon, no text, no letters, no numbers, no watermark, no mockup, no surrounding layout, no metallic texture, no gradients, no shadows, no extra symbols. Deliver a high quality square PNG.

## 验证与发布

检查资源引用、包体积、文字对比度及现有客户端回归。微信开发者工具编译、真机小尺寸图标及视觉验收仍需完成。体验版确认后发布；回退恢复上一版小程序与账号头像，不需数据库操作。
