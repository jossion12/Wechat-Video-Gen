状态栏图标 — 来源 Microsoft Fluent UI System Icons

仓库：https://github.com/microsoft/fluentui-system-icons
许可：MIT License（见仓库根目录 LICENSE 文件）

本目录收录状态栏所需的最小子集（24px 变体）：

  alarm-24.svg         Clock Alarm - 闹钟
  bluetooth-24.svg     Bluetooth - 蓝牙
  wifi-24.svg          WiFi - Wi-Fi（仅 24px color 版，因为 regular 版不存在）
  battery-0..10.svg    Battery 0~10 - 电池（按电量 0~100 映射到 0~10 取就近一档）

如需扩展（Cellular 1-5 / Cellular 3G-5G / WiFi Warning 等），从原仓库
`/assets/<IconName>/SVG/ic_fluent_<name>_<size>_<variant>.svg` 选取并按上方
命名规则覆盖即可。建议保持 24px regular/filled 作为预览尺寸，32px 用于
1080x1920 录制画布（CSS 控制实际渲染尺寸）。

对应后端拷贝位置：`backend/app/assets/icons/status-bar/` —— 模板渲染时由
`app/renderer.py` 读入并 inline 到 HTML。
