# Enhanced Memory 前端主题色系表

来源目录：`D:\Program Files\Git Lib\astrbot-plugin-enhanced-memory\web\frontend`

正式主题文件位于：`web\frontend\styles\themes\*.css`

默认主题：`theme-moirai`

## 主题总览

| 色系编号 | 显示名 | CSS 类名 | 风格定位 | 主题文件 |
|---|---|---|---|---|
| `moirai` | Moirai | `.theme-moirai` | 淡薰衣草 + 古金 | `styles/themes/moirai.css` |
| `venus` | Venus | `.theme-venus` | 象牙石材 + 绯红 + 金色 | `styles/themes/venus.css` |
| `nox` | Nox | `.theme-nox` | 黑白灰标准色 | `styles/themes/nox.css` |
| `juno` | Cirrus | `.theme-juno` | 云感 SaaS 蓝灰 + 橙 | `styles/themes/juno.css` |
| `augustus` | Augustus | `.theme-augustus` | 象牙白 + 靛蓝 + 金橙 | `styles/themes/augustus.css` |
| `selune` | Aether | `.theme-selune` | 暗色科技 + 钢蓝灰 + 薄荷绿 | `styles/themes/selune.css` |
| `folio` | Folio | `.theme-folio` | 纸浆米色 + 石墨灰 | `styles/themes/folio.css` |

## 核心色值

| 色系编号 | 显示名 | 亮色主背景 | 亮色主色 | 亮色强调色 | 暗色背景 | 暗色主色 | 暗色强调色 |
|---|---|---|---|---|---|---|---|
| `moirai` | Moirai | `oklch(0.978 0.008 295)` | `oklch(0.53 0.130 295)` | `oklch(0.679 0.106 70)` | `oklch(0.11 0.010 288)` | `oklch(0.64 0.105 295)` | `oklch(0.767 0.113 80)` |
| `venus` | Venus | `oklch(0.975 0.006 75)` | `oklch(0.52 0.205 25)` | `oklch(0.42 0.10 75)` | `oklch(0.145 0.012 220)` | `oklch(0.62 0.22 25)` | `oklch(0.82 0.13 82)` |
| `nox` | Nox | `oklch(1 0 0)` | `oklch(0.205 0 0)` | `oklch(0.205 0 0)` | `oklch(0.145 0 0)` | `oklch(0.922 0 0)` | `oklch(0.985 0 0)` |
| `juno` | Cirrus | `oklch(0.98 0.005 225)` | `oklch(0.56 0.08 240)` | `oklch(0.62 0.12 50)` | `oklch(0.16 0.03 250)` | `oklch(0.65 0.09 240)` | `oklch(0.78 0.12 50)` |
| `augustus` | Augustus | `oklch(0.975 0.008 88)` | `oklch(0.65 0.155 80)` | `oklch(0.48 0.165 50)` | `oklch(0.11 0.020 252)` | `oklch(0.76 0.168 81)` | `oklch(0.74 0.200 46)` |
| `selune` | Aether | `oklch(0.97 0.008 250)` | `oklch(0.63 0.11 175)` | `oklch(0.44 0.07 250)` | `oklch(0.16 0.02 250)` | `oklch(0.63 0.11 175)` | `oklch(0.83 0.02 250)` |
| `folio` | Folio | `oklch(0.92 0.05 86)` | `oklch(0.38 0.015 265)` | `oklch(0.38 0.015 265)` | `oklch(0.18 0.01 265)` | `oklch(0.78 0.025 86)` | `oklch(0.90 0.03 86)` |

## 主题预览色

这些颜色出现在登录页和设置页的主题选择小圆点里。

| 色系编号 | 显示名 | 预览色 |
|---|---|---|
| `moirai` | Moirai | `oklch(0.53 0.130 295)` |
| `nox` | Nox | `oklch(0.45 0.08 260)` |
| `venus` | Venus | `oklch(0.60 0.18 5)` |
| `juno` | Cirrus | `oklch(0.52 0.12 220)` |
| `augustus` | Augustus | `oklch(0.58 0.14 55)` |
| `selune` | Aether | `oklch(0.55 0.10 200)` |
| `folio` | Folio | `oklch(0.48 0.09 140)` |

## 复用建议

| 场景 | 推荐色系编号 | 原因 |
|---|---|---|
| 默认记忆类插件 | `moirai` | 和 Enhanced Memory 当前默认风格一致，淡紫 + 古金有识别度 |
| 管理后台 / SaaS 工具 | `juno` | 蓝灰 + 软橙，专业、干净、可读性强 |
| 暗色科技感界面 | `selune` | 深色优先，钢蓝灰结构配薄荷绿 CTA |
| 文档库 / 知识库 / 笔记感 | `folio` | 纸浆米色 + 石墨灰，适合阅读和归档 |
| 强品牌感 / 视觉冲击 | `venus` | 绯红 + 金色更有情绪和识别度 |
| 仪式感 / 史诗感页面 | `augustus` | 象牙、靛蓝、金橙组合更庄重 |
| 极简默认兼容 | `nox` | 标准黑白灰，适合作为保底主题 |

## 可直接复用的主题编号

```ts
const themeIds = [
  'moirai',
  'venus',
  'nox',
  'juno',
  'augustus',
  'selune',
  'folio',
]
```

