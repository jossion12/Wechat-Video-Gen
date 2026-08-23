# 10 · 新增视觉风格设计（Noir / Ink / Vaporwave）

> 本文件是 3 种新视觉风格的设计规格与落地清单。实现细节（模板上下文、消息字典、TIMELINE、回复引用等）遵循 [`04-template.md`](./04-template.md)，本文件只补充**主题特有的设计决策**。

---

## 10.1 背景与目标

现有 4 种视觉风格：

| 风格 | 视觉气质 | 配色 | 字体 | 头像 |
|---|---|---|---|---|
| cyberpunk 赛博朋克 | 未来 / 冷峻 | 深色 + 霓虹蓝紫粉 | sans-serif | 六边形 |
| watercolor 手绘 | 治愈 / 文艺 | 莫兰迪米白 | 楷体 | 六边形 |
| pixel 复古 | 8bit / 游戏 | 黑底绿字 | 等宽 | 六边形 |
| comic 漫画 | 夸张 / 张力 | 高对比 | 粗黑 sans | 六边形 |

按"年代 / 情绪 / 配色 / 字体"四轴盘点，明显的视觉空白还有：

1. **东方古典 / 水墨** —— 与 watercolor 的"西方手绘"完全区分
2. **80–90s 复古未来 / 蒸汽波** —— 与 cyberpunk 的"反乌托邦未来"区分
3. **严肃黑白 / 经典电影** —— 与 comic 的"高饱和动作"形成冷暖对照

本次新增三种风格，目标是把"2 × 3 矩阵"凑齐：

```
         抽象度 ──→ 手绘    屏幕    经典
情绪
  暖                  watercolor           ink
  中                  comic      cyberpunk        noir
  冷                  pixel      vaporwave
```

---

## 10.2 设计原则（与既有约定一致）

- 不模仿任何真实社交平台（微信/WhatsApp/iMessage 等）的视觉元素
- 每个主题有独立的配色 / 字体 / 头像形状 / 气泡形状
- 片头 AI 声明卡 + 右下角 AI 角标 强制存在
- 模板仅做展示用 `for`/`if`，所有数据预处理仍在 `renderer.py`
- 所有模板共享同一份 `messages` / `participants` / `timeline` 上下文（见 04-template §4.2）
- `badge_style` 沿用现有的 `neon / minimal / retro` 三值，不新增枚举

---

## 10.3 三主题速览

| 项 | noir 黑白胶片 | ink 水墨 | vaporwave 蒸汽波 |
|---|---|---|---|
| 视觉气质 | 文学 / 戏剧 / 古典 | 静 / 有机 / 留白 | 躁 / 电子 / 梦幻 |
| 默认背景色 | `#f5f0e1` 米白 | `#f4ecd8` 宣纸 | `#1a0a2e` 深空蓝 |
| 配色体系 | 严格灰阶（仅黑白灰） | 米 + 墨 + 朱红 | 粉紫青渐变 + 深空 |
| 字体 | 衬线（Playfair/Source Serif → 系统衬线回退） | 楷体 / 仿宋 → Noto Serif CJK 回退 | 粗 sans（Impact/Arial）+ 铬金属渐变 |
| 头像形状 | 圆角正方形 + 黑描边 | 圆形 + 朱红描边（带 ±3° 倾斜） | 三角/圆混用 + 霓虹外发光 |
| 气泡边缘 | 硬直 + 1px 描边 | SVG 笔触毛边（feDisplacementMap） | 16px 圆角 + 渐变描边 |
| 系统消息 | 居中衬线大写 + 上下细线 "ACT II · NIGHT" | 朱红方章"印"+ 旋转 −5° | 铬金属字"システム"+ ◆ 装饰 |
| 时间戳 | 衬线斜体 "12:47 AM" | 楷体小字居中 "星期日 14:30" | 等宽字 + 罗马数字 "XV : XXVII" |
| AI 角标 | 白底黑字圆 (`minimal`) | 朱红方章 (`retro`) | 铬金属胶囊 + 霓虹光 (`neon`) |
| 适合 intent | teaching_simulation / 严肃 drama | story_visualization / 古装 drama | meme_sticker / 潮流 drama |
| 实现优先级 | **P0（先做）** | P1 | P2 |

---

## 10.4 Noir · 黑白胶片

### 10.4.1 视觉定位

经典黑白电影美学 —— 纯灰度、菲林颗粒、戏剧化光影、衬线字体、画框装饰、放映机灰尘。把对话剧场做成"老电影分镜"。

### 10.4.2 配色变量

| 变量 | 值 | 用途 |
|---|---|---|
| `--bg` | `{{ background }}` 默认 `#f5f0e1` | 画布底色（象牙白，模拟电影银幕） |
| `--paper` | `#f5f0e1` | 浅色面板 |
| `--ink` | `#0a0a0a` | 主文字 / 描边 |
| `--ink-soft` | `#2a2a2a` | 次级文字 |
| `--grey` | `#666666` | 时间戳 / 弱化文字 |
| `--grey-light` | `#cccccc` | 分隔线 |
| `--self-bg` | `#0a0a0a` | 自己气泡底（纯黑反色） |
| `--self-text` | `#f5f0e1` | 自己气泡文字 |
| `--other-bg` | `#ffffff` | 他人气泡底（纯白） |
| `--other-text` | `#0a0a0a` | 他人气泡文字 |
| `--reply-bar` | `#0a0a0a` | 回复引用竖条 |

> 模板里禁止出现非灰阶色值；唯一例外是 `badge_style="minimal"` 渲染时使用纯黑 / 纯白，仍属灰阶。

### 10.4.3 字体栈

```
标题: "Playfair Display", "Times New Roman", "Noto Serif CJK SC", "STSong", "SimSun", serif
正文: "Source Serif Pro", "Georgia", "Noto Serif CJK SC", "STSong", "SimSun", serif
系统消息: 同正文 + font-feature-settings: "smcp" + italic
时间戳: 同正文 + italic
```

> 字体可用性：Dockerfile 需新增 `fonts-noto-cjk` 已在场；新增 Google Fonts 由模板加载失败时自动回退到系统衬线。
> 不在 MVE 阶段下载 web font，**全部使用系统衬线回退**，等模板稳定后再考虑自托管。

### 10.4.4 头像

- 形状：`border-radius: 8px`（圆角正方形），不再是六边形
- 描边：`border: 2px solid var(--ink)`
- 缺头像占位：白底 + 黑色衬线首字母（字号 56px）
- 排列：保持左/右贴边规则

### 10.4.5 气泡

**自己气泡**：

| 属性 | 值 |
|---|---|
| 背景 | `var(--self-bg)` 纯黑 |
| 文字 | `var(--self-text)` 象牙白 |
| 边框 | 无 |
| 圆角 | `border-radius: 4px`（极轻微，模拟电影画框） |
| 阴影 | `box-shadow: 0 2px 12px rgba(0,0,0,0.45)`（银幕深度） |
| 动画 | 入场 `transform: scaleY(0) → scaleY(1)` 0.3s（影院幕布升起感） |

**他人气泡**：

| 属性 | 值 |
|---|---|
| 背景 | `var(--other-bg)` 纯白 |
| 文字 | `var(--ink)` 纯黑 |
| 边框 | `1px solid var(--ink)` |
| 圆角 | `border-radius: 4px` |
| 阴影 | `box-shadow: 0 2px 12px rgba(0,0,0,0.45)` |
| 动画 | 入场 `opacity 0→1` 0.3s（缓慢淡入） |

### 10.4.6 系统消息与时间戳

**系统消息**：经典电影"幕"分隔

```
————————————————— ACT II · NIGHT —————————————————
```

- 横线：`1px solid var(--ink)`，左右各占 ~30%
- 中间文字：衬线大写 + 斜体 + 字号 26px + `letter-spacing: 0.15em`
- 左侧角标：小字 `REEL 01`（按消息序号自增）

**时间戳**：

- 衬线斜体小字：`12:47 AM`
- 字号 22px，颜色 `var(--ink-soft)`
- 无背景，居中显示

### 10.4.7 标题栏

- 居中衬线斜体大标题
- 字号 64px
- 装饰：标题下方一条 `1px solid var(--ink)` 细线 + 再下方一条 0.5px 短线（双线效果，类书籍章节标题）
- 不显示副标题

### 10.4.8 背景层叠

从下到上 4 层：

1. **`var(--bg)`** 实色（默认象牙白）
2. **菲林颗粒**：内嵌 SVG `feTurbulence baseFrequency=0.9 numOctaves=2` → `feColorMatrix` 转灰阶 → `opacity: 0.10`
3. **四角暗角**：`radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,0.25) 100%)`
4. **8mm 胶片齿孔**：左右两侧各 ~80px 宽的"齿孔带"——`repeating-linear-gradient` 垂直方向每 80px 一个黑色小矩形

> 注：所有装饰必须在 `z-index: 0` 以下，确保 `background_image_url` 用户上传图不会与之冲突。

### 10.4.9 AI 角标与片头声明

**AI 角标**：`badge_style="minimal"`

- 右下角 64×64 圆（`border-radius: 50%`）
- 底色 `#ffffff`，描边 `2px solid var(--ink)`
- 内嵌衬线大写 "AI"，字号 28px，颜色 `var(--ink)`

**片头声明**（1 秒）：

| 阶段 | 时长 | 效果 |
|---|---|---|
| 黑屏 | 0.0–0.3s | 整屏纯黑 |
| 颗粒淡入 | 0.3–0.6s | grain layer opacity 0→1 |
| 打字机文本 | 0.6–0.9s | 衬线白字 `width: 0 → 100%` + `steps(20)` |
| 持续 + 淡出 | 0.9–1.3s | 文字保持 0.1s，然后整层淡出 |

### 10.4.10 特殊元素处理

| 元素 | 处理 |
|---|---|
| emoji | `filter: grayscale(1) contrast(1.1)` + `1px solid var(--ink)` 描边 |
| 图片 | `filter: grayscale(1) contrast(1.1) brightness(0.95)` + `1px solid var(--ink)` 描边 + 8px 圆角 |
| 视频封面 | 同图片，外加 `box-shadow: 0 2px 12px rgba(0,0,0,0.45)` |
| 回复引用 | 左侧 `3px solid var(--ink)` 竖条；发送者名衬线斜体粗体；正文衬线 |

### 10.4.11 与 4.9 默认约定的差异

| 约定项 | 默认 | noir 覆盖 |
|---|---|---|
| 头像 | 六边形 | 圆角正方形 + 2px 黑描边 |
| 自己气泡 | 蓝紫渐变半透明 + 霓虹蓝边 | 纯黑 + 无边 + 4px 圆角 |
| 他人气泡 | 白色半透明 + 淡白边 | 纯白 + 1px 黑边 + 4px 圆角 |
| 系统消息 | 紫色半透明 + 左右霓虹紫边 | 居中衬线大写 + 上下细横线 |
| 时间戳 | 霓虹蓝胶囊 | 衬线斜体无背景 |
| emoji 投影 | 霓虹 | 灰度 + 黑描边 |
| 字体栈 | Noto Sans CJK → PingFang → 微软雅黑 | 衬线栈（Playfair → Times → Noto Serif CJK） |

---

## 10.5 Ink · 水墨

### 10.5.1 视觉定位

东方水墨画美学 —— 宣纸 + 墨韵 + 朱印 + 竖排装饰。完全脱离"屏幕 UI 拟物"路线，把对话剧场做成"卷轴/册页"。

### 10.5.2 配色变量

| 变量 | 值 | 用途 |
|---|---|---|
| `--bg` | `{{ background }}` 默认 `#f4ecd8` | 宣纸米色 |
| `--paper` | `#f4ecd8` | 浅色面板 |
| `--paper-light` | `#fcfaf2` | 他人气泡（更白的纸） |
| `--ink-deep` | `#1a1a1a` | 主墨色 / 描边 |
| `--ink-soft` | `#4a4a4a` | 次级墨色 |
| `--ink-light` | `#8a8578` | 弱化墨色 |
| `--seal-red` | `#b8332b` | 朱砂红（强调色） |
| `--seal-red-deep` | `#8a2520` | 深朱红 |
| `--self-bg` | `linear-gradient(180deg, rgba(26,26,26,0.18) 0%, rgba(26,26,26,0.06) 100%)` | 自己气泡（淡墨晕染） |
| `--self-text` | `#1a1a1a` | 自己气泡文字 |
| `--other-bg` | `#fcfaf2` | 他人气泡 |
| `--other-text` | `#1a1a1a` | 他人气泡文字 |
| `--reply-bar` | `#b8332b` | 回复引用竖条（朱红） |

### 10.5.3 字体栈

```
标题: "STKaiti", "KaiTi", "楷体", "Noto Serif CJK SC", "Songti SC", "STSong", serif
正文: "STFangsong", "FangSong", "仿宋", "Noto Serif CJK SC", "Songti SC", "STSong", serif
系统消息(印): 同标题 + bold + uppercase(罗马)
时间戳: 同正文 + 字号略小
```

> 楷体/仿宋在 macOS / Windows 原生可用，Linux 走 Noto Serif CJK SC 回退；
> Dockerfile 中 `fonts-noto-cjk` 已安装，**无需新增字体**。

### 10.5.4 头像

- 形状：`border-radius: 50%`（圆形朱印）
- 描边：`border: 2px solid var(--seal-red)`
- 缺头像占位：朱红底 + 白色楷体首字母
- **每张头像随机旋转 ±3°**（用 inline style `transform: rotate(N deg)` 注入），模拟印章按压角度
- 投影：`box-shadow: 0 1px 4px rgba(184,51,43,0.25)`（朱印微微渗透纸面）

### 10.5.5 气泡

**笔触毛边实现**：用 SVG `<filter>` 定义 `feTurbulence + feDisplacementMap`，对气泡的 `clip-path` 或 `mask` 应用，使边缘呈现不规则笔触感。

| 属性 | 自己气泡 | 他人气泡 |
|---|---|---|
| 背景 | `--self-bg` 淡墨渐变 | `--other-bg` 浅纸色 |
| 文字 | `--self-text` 墨黑 | `--other-text` 墨黑 |
| 边框 | 无（靠边缘毛边形成边界） | 无 |
| 圆角 | `border-radius: 12px` + 笔触 mask | `border-radius: 12px` + 笔触 mask |
| 阴影 | `box-shadow: 1px 2px 0 rgba(26,26,26,0.15)`（墨痕投影） | 同 |
| 装饰 | 气泡末端可加一颗小墨点（`::after` 伪元素） | 无 |

入场动画：自己气泡 `opacity 0→1 + translateX(20px → 0)` 0.4s（墨色由浓转淡且向右铺开）；他人气泡 `opacity 0→1 + translateX(-20px → 0)` 0.4s。

### 10.5.6 系统消息与时间戳

**系统消息**：朱红方印

- 居中显示 `80×80 px` 方块
- `border: 3px solid var(--seal-red)`
- 内嵌一个白色楷体字（"印" / "令" / "签"，或者 `sys.text` 的首字），字号 48px
- `transform: rotate(-5deg)` 整体旋转（朱印歪斜感）
- 投影：`box-shadow: 1px 2px 0 rgba(184,51,43,0.3)`
- 装饰：方印右侧可附小字楷体"某年某月"竖排

**时间戳**：

- 楷体小字居中：`星期日 · 14:30`（使用全角点号）
- 字号 22px，颜色 `--ink-soft`
- 无背景，无边框

### 10.5.7 标题栏

- 居中楷体大标题，字号 60px
- 装饰：标题下方一条 1px 墨线（左右不对称长：左侧 30% 右侧 70%，模拟手写）
- 标题右侧附 36×36 朱红小方印，旋转 -5°

### 10.5.8 背景层叠

1. **`var(--bg)`** 宣纸米色实色
2. **宣纸纤维**：内嵌 SVG `feTurbulence baseFrequency=1.5 numOctaves=3` → `opacity: 0.15`
3. **顶部笔触装饰**：title 区上方有一条 ~30px 高的横向笔触横线（用 SVG `<path>` + `stroke-linecap: round` + `stroke-width: 8`），`opacity: 0.4`
4. **底部远山墨影**：canvas 底部 30% 高度叠一道山脊 SVG path，用 linear-gradient 从 `rgba(26,26,26,0)` 顶部过渡到 `rgba(26,26,26,0.18)` 底部，`opacity: 0.6`

### 10.5.9 AI 角标与片头声明

**AI 角标**：`badge_style="retro"`

- 右下角 56×56 朱红方印
- `border: 3px solid var(--seal-red)`，底色 `var(--seal-red)`
- 内嵌白色楷体"AI"或印章体篆字，字号 26px
- `transform: rotate(-5deg)`

**片头声明**（1 秒）：卷轴展开

| 阶段 | 时长 | 效果 |
|---|---|---|
| 宣纸铺底 | 0.0–0.2s | 整屏宣纸纹理 `opacity 0→1` |
| 卷轴展开 | 0.2–0.9s | 中央一条 4px 朱红竖线从左向右"扫"过（`transform: scaleX(0→1)`，原点在左） |
| 文字浮现 | 0.5–0.9s | 楷体"本对话由 AI 生成 · 仅供创意表达"在竖线扫过的同时逐字 fade-in |
| 淡出 | 0.9–1.3s | 整层淡出到 chat 场景 |

### 10.5.10 特殊元素处理

| 元素 | 处理 |
|---|---|
| emoji | **保色**；`filter: drop-shadow(2px 2px 0 rgba(26,26,26,0.3))` 模拟墨印投影 |
| 图片 | `filter: sepia(0.25) contrast(0.95) brightness(1.02)` + 8px 圆角 + 2px 墨色描边 |
| 视频封面 | 同图片 |
| 回复引用 | 左侧 `3px solid var(--seal-red)` 竖条；发送者名楷体粗体；正文楷体 |

### 10.5.11 与 4.9 默认约定的差异

| 约定项 | 默认 | ink 覆盖 |
|---|---|---|
| 头像 | 六边形 | 圆形朱印 + 随机倾斜 ±3° |
| 自己气泡 | 蓝紫渐变 + 霓虹蓝边 | 淡墨渐变 + 笔触毛边 + 无描边 |
| 他人气泡 | 白色半透明 + 淡白边 | 浅纸色 + 笔触毛边 + 无描边 |
| 系统消息 | 紫色半透明 + 左右霓虹紫边 | 朱红方印（旋转 −5°） |
| 时间戳 | 霓虹蓝胶囊 | 楷体居中无背景 |
| 字体栈 | Noto Sans CJK → PingFang → 微软雅黑 | STKaiti → KaiTi → Noto Serif CJK |

---

## 10.6 Vaporwave · 蒸汽波

### 10.6.1 视觉定位

80–90s 复古未来主义 —— 落日渐变、透视网格地板、片假名装饰、铬金属质感、几何线条。cyberpunk 是"反乌托邦未来"，vaporwave 是"怀旧的未来想象"。

### 10.6.2 配色变量

| 变量 | 值 | 用途 |
|---|---|---|
| `--bg` | `{{ background }}` 默认 `#1a0a2e` | 深空蓝画布底 |
| `--deep-space` | `#1a0a2e` | 深空蓝 |
| `--sunset-pink` | `#ff6ec7` | 热粉（强调色 1） |
| `--sunset-purple` | `#9d4edd` | 电紫 |
| `--neon-cyan` | `#00f5ff` | 霓虹青（强调色 2） |
| `--sunset-orange` | `#ff9e00` | 落日橙 |
| `--chrome-a` | `#ffffff` | 铬金属渐变顶层 |
| `--chrome-b` | `#00f5ff` | 铬金属渐变中层 |
| `--chrome-c` | `#9d4edd` | 铬金属渐变底层 |
| `--self-bg` | `linear-gradient(135deg, rgba(0,245,255,0.85) 0%, rgba(157,78,221,0.85) 100%)` | 自己气泡 |
| `--self-text` | `#ffffff` | 自己气泡文字 |
| `--other-bg` | `rgba(26,10,46,0.7)` | 他人气泡（深空蓝半透明） |
| `--other-text` | `#f5e6ff` | 他人气泡文字 |
| `--text` | `#f5e6ff` | 主文字 |
| `--text-dim` | `#b794d6` | 弱化文字 |
| `--reply-bar` | `#ff6ec7` | 回复引用竖条（热粉） |

### 10.6.3 字体栈

```
标题: "Audiowide", "Orbitron", "Impact", "Helvetica Neue", "Arial Black", "Noto Sans CJK SC", sans-serif
正文: "Helvetica Neue", "Arial", "Noto Sans CJK SC", "PingFang SC", sans-serif
系统消息: 同正文 + bold + uppercase + letter-spacing 0.2em
时间戳: "Courier New", "Lucida Console", monospace
```

> Audiowide / Orbitron 是 Google Fonts，MVE 阶段不下载，**统一回退到 Impact / Arial Black**。
> 铬金属效果通过 CSS `background: linear-gradient(...) ; background-clip: text; color: transparent` 实现，不依赖字体本身。

### 10.6.4 头像

- 形状：**按 participant id 奇偶混用**：
  - 奇数 id → `clip-path: polygon(50% 0%, 100% 100%, 0% 100%)`（三角形）
  - 偶数 id → `border-radius: 50%`（圆形）
- 描边：`border: 2px solid var(--neon-cyan)`
- 投影：`box-shadow: 0 0 12px var(--neon-cyan), 0 0 24px var(--sunset-pink)`（双色霓虹光晕）
- 缺头像占位：深空蓝底 + 白色 sans 大写首字母（字号 56px）

### 10.6.5 气泡

| 属性 | 自己气泡 | 他人气泡 |
|---|---|---|
| 背景 | `--self-bg` 青→紫渐变 85% 不透明 | `--other-bg` 深空蓝 70% 不透明 |
| 文字 | `--self-text` 白 | `--other-text` 浅紫 |
| 描边 | `2px solid var(--sunset-pink)` | `1px solid var(--neon-cyan)` |
| 圆角 | `border-radius: 16px` | `border-radius: 16px` |
| 阴影 | `0 0 16px rgba(255,110,199,0.6)` | `0 0 12px rgba(0,245,255,0.4)` |
| 动画 | 入场 `transform: translateY(20px → 0)` + `opacity 0→1` 0.4s | 同 |

### 10.6.6 系统消息与时间戳

**系统消息**：铬金属字 + 片假名装饰

- 文字"システム"或英文"■ SYSTEM ■"（chrome 渐变字体效果）
- 字号 30px，`letter-spacing: 0.3em`
- 左右各一个 `◆` 装饰符，颜色 `var(--neon-cyan)`
- 装饰下方一道 1px 渐变线（青→粉→紫→粉→青）

**时间戳**：

- 等宽字 + 罗马数字："XV : XXVII"（15:27）
- 或者保留阿拉伯但用 chrome 渐变描边样式
- 字号 22px，颜色 `var(--neon-cyan)`

### 10.6.7 标题栏

- 居中 Impact / Arial Black 粗体大标题
- 字号 72px
- **铬金属渐变文字**：`background: linear-gradient(180deg, var(--chrome-a) 0%, var(--chrome-b) 50%, var(--chrome-c) 100%); -webkit-background-clip: text; color: transparent`
- 装饰：标题下方漂浮 2-3 个片假名（"ミク" "ボーカル" "エモい"），`opacity: 0.18`，随机位置

### 10.6.8 背景层叠（主题灵魂）

从下到上 6 层：

1. **`var(--bg)`** 深空蓝实色
2. **落日渐变**：`linear-gradient(180deg, rgba(255,110,199,0.85) 0%, rgba(157,78,221,0.85) 35%, rgba(26,10,46,0) 75%)`，覆盖 canvas 上 60%
3. **落日**：在 canvas 65% 高度、水平居中放一个 `width: 800px; height: 800px` 的圆形，`background: radial-gradient(circle, var(--sunset-orange) 0%, var(--sunset-pink) 40%, transparent 80%)`，`opacity: 0.85`
4. **透视网格地板**：canvas 下 40% 高度用 `perspective: 800px; transform: rotateX(60deg); transform-origin: 50% 0%;` 容器，内嵌 `repeating-linear-gradient` 制造网格线（青色细线 + 热粉粗线），网格延伸到地平线（消失点在落日中心）
5. **漂浮片假名**：`body::before` 在背景层输出 5-8 个固定位置的片假名字符（"ミク" "セカイ" "バーチャル" "ドリーム"），`opacity: 0.18`，`font-size: 48-96px`，`color: var(--sunset-pink)`，每个字轻微 `transform: rotate(-5deg)` 至 `rotate(8deg)` 之间
6. **扫描线**：`repeating-linear-gradient(0deg, rgba(0,245,255,0.04) 0px, rgba(0,245,255,0.04) 1px, transparent 1px, transparent 4px)` 覆盖整屏，`opacity: 0.5`

### 10.6.9 AI 角标与片头声明

**AI 角标**：`badge_style="neon"`

- 右下角胶囊形 80×40，`border-radius: 20px`
- 底色 `var(--deep-space)`，描边 `2px solid var(--neon-cyan)`
- 铬金属"AI"字
- `box-shadow: 0 0 12px var(--neon-cyan)`

**片头声明**（1 秒）：网格升起 + 落日出现

| 阶段 | 时长 | 效果 |
|---|---|---|
| 网格升起 | 0.0–0.5s | 网格地板 `transform: translateY(100% → 0)`（从底部升起） |
| 落日升起 | 0.2–0.7s | 落日圆 `opacity 0→0.85` + `transform: scale(0.5 → 1)` |
| 文字浮现 | 0.6–0.9s | 铬金属"本对话由 AI 生成 · 仅供创意表达"逐字 fade-in |
| 整体淡出 | 0.9–1.3s | 整层淡出到 chat 场景 |

### 10.6.10 特殊元素处理

| 元素 | 处理 |
|---|---|
| emoji | **保色 + 双色霓虹光**：`filter: drop-shadow(0 0 8px var(--sunset-pink)) drop-shadow(0 0 16px var(--neon-cyan))` |
| 图片 | 12px 圆角 + 2px 青描边 + `box-shadow: 0 0 16px rgba(0,245,255,0.4)` |
| 视频封面 | 同图片 |
| 回复引用 | 左侧 `3px solid var(--sunset-pink)` 竖条；发送者名 sans 粗体；正文 sans；右侧（自己）切到 `var(--neon-cyan)` |

### 10.6.11 与 4.9 默认约定的差异

| 约定项 | 默认 | vaporwave 覆盖 |
|---|---|---|
| 头像 | 六边形 | 三角/圆混用 + 双色霓虹光晕 |
| 自己气泡 | 蓝紫渐变 + 霓虹蓝边 | 青→紫渐变 + 热粉描边 + 16px 圆角 + 洋红光 |
| 他人气泡 | 白色半透明 + 淡白边 | 深空蓝半透明 + 青描边 + 16px 圆角 + 青光 |
| 系统消息 | 紫色半透明 + 左右霓虹紫边 | 铬金属字 + ◆ 装饰 + 渐变细线 |
| 时间戳 | 霓虹蓝胶囊 | 等宽罗马数字 |
| emoji 投影 | 霓虹 | 双色霓虹 drop-shadow |
| 字体栈 | Noto Sans CJK → PingFang → 微软雅黑 | Impact / Arial Black + Helvetica + 铬金属渐变 |

---

## 10.7 横向对比速查

| 维度 | noir | ink | vaporwave |
|---|---|---|---|
| 年代感 | 经典好莱坞（1930–60s） | 古代东方 | 80–90s 复古未来 |
| 情绪轴 | 冷 / 戏剧 | 静 / 留白 | 躁 / 梦幻 |
| 主色 | 灰阶 | 米 + 墨 + 朱 | 粉 + 紫 + 青 |
| 字体 | 衬线 | 楷体 / 仿宋 | 粗 sans + 铬金属 |
| 头像形状 | 圆角方 | 圆（朱印） | 三角 / 圆（霓虹） |
| 气泡边缘 | 硬直 | 笔触毛边 | 渐变圆角 |
| 系统消息 | 居中衬线大写 + 细线 | 朱红方印 | 铬金属字 + ◆ |
| 时间戳 | 衬线斜体 | 楷体 | 罗马数字 |
| 背景复杂度 | 4 层（颗粒 + 暗角 + 胶片孔） | 4 层（纤维 + 笔触 + 远山） | 6 层（渐变 + 落日 + 网格 + 片假名 + 扫描线） |
| SVG filter | 无（仅 turbulence 用于颗粒） | **有**（feDisplacementMap 用于笔触） | 无（仅 CSS） |
| 适合 intent | teaching / 严肃 drama | 古风 story / drama | 潮流 meme / drama |
| badge_style | minimal | retro | neon |
| 默认背景 | `#f5f0e1` | `#f4ecd8` | `#1a0a2e` |

---

## 10.8 实现顺序与理由

| 顺序 | 主题 | 工作量 | 风险 | 理由 |
|---|---|---|---|---|
| **P0** | noir | 中 | 低 | 纯灰阶 + 衬线字体 + 系统 CSS 技术，**无 SVG filter**，最易验证模板引擎对新主题的支持；失败成本低 |
| **P1** | ink | 中-高 | 中 | 引入 **SVG `feDisplacementMap`**，需要在 Playwright 中验证 filter 渲染；笔触边缘效果主观性强，需多轮微调 |
| **P2** | vaporwave | 高 | 高 | 透视网格 + 6 层背景 + 铬金属渐变 + 多个动画叠加，**最容易出性能 / 视觉回归**；作为收尾，能吸收 noir / ink 调通后沉淀的工具函数 |

每个主题完成后必须：

1. 通过 `backend/tests/test_renderer.py` 全部 4.12 验收项（在该主题的 fixture 下）
2. 生成 1 个示例 MP4 人工目检
3. 提交一个 commit，再启动下一个

---

## 10.9 落地清单（每个主题，按 04-template §4.11 七步）

每实现一个主题，按以下顺序提交：

| # | 改动点 | 文件 / 位置 |
|---|---|---|
| 1 | 新建 Jinja2 模板 | `backend/templates/<theme>_chat.html.j2` |
| 2 | 扩展 Pydantic Literal | `backend/app/dsl.py` 的 `ChatScene.style_theme` 与 `VideoDSL.template` |
| 3 | 扩展渲染分发 | `backend/app/renderer.py` 的 `render_dsl()` switch 加新分支 |
| 4 | 前端类型同步 | `frontend/src/types.ts`：`VideoTemplate` / `StyleTheme` / `STYLE_THEME_LABELS` / `THEME_DEFAULT_BACKGROUND` 各加 1 项 |
| 5 | 前端 UI 适配 | `frontend/src/App.tsx`：`HeaderEditor` 主题选择器 + `StaticPreview` 的预览主题色（如需要） |
| 6 | 添加示例 | `examples/<theme>.json` |
| 7 | 测试 | `backend/tests/test_renderer.py`：该主题的最小配置 + 4.12 全部验收项 |

> 步骤 4、5 在三主题全部完成时合并提交更省事（P0 / P1 / P2 各自的步骤 1-3、6、7 各自提交一次独立 commit，步骤 4、5 留到最后统一改）。

---

## 10.10 测试计划

### 10.10.1 单元测试（`backend/tests/test_renderer.py`）

每个主题新增 1 个 fixture，覆盖以下场景（与 4.12 既有验收项一致 + 主题特有）：

| 测试场景 | 预期 |
|---|---|
| 最小配置（2 参与者 / 1 文本消息） | 渲染出合法 HTML，包含 `<title>Dialogue Theater — <Theme></title>` |
| 自己消息（`align=right` 或 `id="me"`） | 带 `.msg.self` |
| 图片消息 | 生成 `<img>` 标签，无 broken src |
| 视频消息 | 渲染播放按钮 + duration |
| emoji 消息 | 渲染为大 emoji（noir 需验证 `filter: grayscale(1)` 出现在 inline style 或 class） |
| timestamp 消息 | 渲染为 `.time-stamp` |
| sys 消息 | 渲染为幕间字幕（无头像） |
| 连续消息 | 每次都显示头像 |
| TIMELINE | 包含 `__disclaimer__` 首条 |
| AI 角标 | 始终存在 |
| 缺 text 的 text 消息 | 报错 |
| 缺头像 URL | 用默认占位（形状由主题决定：noir 圆角方 / ink 圆 / vaporwave 三角或圆） |
| 高敏感词 / 真实平台名 | 校验错误 |
| reply_to 引用 | 渲染 `.reply-quote` 块（noir 黑条 / ink 朱红 / vaporwave 热粉） |

### 10.10.2 主题特有测试

| 主题 | 额外测试 |
|---|---|
| noir | 渲染产物 HTML 中除 AI badge / disclaimer 文字外，**不含任何彩色 hex**（抽样检查） |
| ink | SVG `<filter>` 标签存在；至少 1 处 `feDisplacementMap` 引用 |
| vaporwave | `body::before` / `body::after` 中含至少 3 个片假名字符；`.title` 含 `background-clip: text` |

### 10.10.3 录屏验证

对每个主题的示例 JSON 跑一遍 `/api/render`，下载 MP4 后人工目检：

- 片头 1 秒声明卡动画是否正常
- 消息入场动画是否符合设计
- 落日渐变 / 颗粒 / 网格等装饰层是否影响文字可读性
- AI 角标在右下角不遮挡关键内容
- 回复引用块竖条颜色对应主题

### 10.10.4 性能基线

在 4 worker 并发下，记录每个主题：

- 最小配置（5 条消息）渲染时长
- 中等配置（30 条消息）渲染时长
- 不应超过 cyberpunk baseline 的 1.5 倍（vaporwave 因多层背景需重点关注）

---

## 10.11 风险与决策记录

| # | 风险 / 决策 | 应对 |
|---|---|---|
| R1 | noir 全灰阶可能让图片消息显得沉闷 | 用 `grayscale + contrast + brightness` 微调，配合黑描边提升戏剧感 |
| R2 | ink 的 SVG `feDisplacementMap` 在不同 Chromium 版本渲染不一致 | 在 Dockerfile 锁定 Playwright Chromium 版本；为 displacement 强度设上限（≤5px）防止失控 |
| R3 | vaporwave 透视网格在某些屏幕比例下消失点偏离落日 | 消失点固定在 canvas 水平 50%、垂直 65%（与落日中心重合），与 1080×1920 比例强耦合 |
| R4 | 衬线字体（noir）在 Docker 内 fallback 到 Noto Serif CJK SC，视觉差异 | 接受 fallback；后续可自托管 Playfair Display / Source Serif Pro 到 `static/fonts/` |
| R5 | vaporwave 片假名漂浮层若位置随机可能导致动画卡顿 | 全部用 CSS 静态定位，不用 JS 随机；预生成 5-8 个固定位置 |
| R6 | 用户上传的 `background_image_url` 与主题背景层叠加可能视觉冲突 | 沿用现有实现：透明叠加在主题背景之上；调低 opacity（noir 0.15 / ink 0.25 / vaporwave 0.20） |
| R7 | 头像形状变化（圆角方 / 圆 / 三角）打破现有"六边形统一"约定 | 接受差异；将"统一六边形"从 4.9 约定降级为"cyberpunk / watercolor / pixel / comic 共用默认"，由各模板覆盖 |
| R8 | 三主题同时上线对前端主题选择器 UI 造成拥挤 | 主题选择器使用卡片网格 2×2 / 3 列布局，noir / ink / vaporwave 各加预览缩略图（CSS 静态预览即可） |

---

## 10.12 已确认的决策

> 本节记录与用户对齐过的关键决策，避免实现时反复确认。

1. **三主题 id**：`noir` / `ink` / `vaporwave`
2. **三主题中文标签**：`黑白胶片` / `水墨` / `蒸汽波`
3. **实现顺序**：noir → ink → vaporwave（P0 → P1 → P2）
4. **badge_style 复用**：`noir→minimal` / `ink→retro` / `vaporwave→neon`，不新增枚举
5. **emoji 处理**：noir 强制 `grayscale(1)`，ink / vaporwave 保色
6. **示例 intent**：noir=`teaching_simulation` / ink=`story_visualization` / vaporwave=`meme_sticker`
7. **设计文档位置**：`docs/10-new-themes-design.md`（本文件）
8. **交叉引用更新**：`docs/04-template.md` §4.1 表格新增三行（状态列：设计完成，待实现）

---

## 10.13 后续参考

- 模板上下文结构、消息字典、TIMELINE 规则 → [`04-template.md`](./04-template.md) §4.2 – §4.10
- 添加新风格的 7 步流程 → [`04-template.md`](./04-template.md) §4.11
- 模板测试 checklist → [`04-template.md`](./04-template.md) §4.12
- 数据模型扩展点 → [`02-data-model.md`](./02-data-model.md) §2.3 / §2.4
- API 兼容 → [`03-api.md`](./03-api.md)
