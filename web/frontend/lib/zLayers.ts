// ─── z-index 量表（浮层层级单一真源） ─────────────────────────────
//
// 所有浮层（popover / dropdown / tooltip / modal / toast）的 z-index 必须取自此处，
// 禁止再写散落的 magic number。配套约定：浮层要 portal 到 document.body，
// 否则祖先的 stacking context（backdrop-filter / transform / position+z-index）
// 与 overflow 会把它关住，z-index 再大也escape不出去。
//
// 量表单调递增，且 dropdown / tooltip 刻意高于 dialog：
// 这样「modal 内打开的 Select」「popover 上的 tooltip」portal 到 body 后，
// 仍能正确盖在 modal 之上。CSS 侧的同名变量见 styles/tokens.css `:root`。

export const Z = {
  base: 0,
  raised: 10,     // 固定外壳：TopBar、Rail（sticky）
  widget: 100,    // 常驻小部件 / 登录遮罩：BuildWidget、LoginScreen
  dialog: 1000,   // modal 遮罩 + 对话框：ds/Modal、各面板全屏弹窗、dir-picker
  panel: 1100,    // 浮动开发面板：PerfPanel、TerminalPanel
  dropdown: 1200, // Select 下拉 / popover / 菜单（高于 dialog 以支持 modal 内嵌套）
  tooltip: 1300,  // Tooltip
  progressDock: 1350, // 统一进度面板（左下角浮动停靠）：Modal 之上、Toast 之下
  toast: 1400,    // 全局通知，永远最顶
} as const;

export type ZLayer = keyof typeof Z;
