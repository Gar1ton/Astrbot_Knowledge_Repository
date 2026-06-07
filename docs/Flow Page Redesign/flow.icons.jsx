/* flow.icons.jsx — 占位线性图标（无真实图标库时的占位）。导出到 window。 */
const I = ({ d, children, sw = 1.6 }) => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none"
       stroke="currentColor" strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round">
    {d ? <path d={d} /> : children}
  </svg>
);

// 每个阶段一个占位字形
const STAGE_ICON = {
  doc:   <I><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /><path d="M9 13h6M9 17h4" /></I>,
  spark: <I><path d="M12 3v4M12 17v4M3 12h4M17 12h4" /><path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z" /></I>,
  db:    <I><ellipse cx="12" cy="5.5" rx="7" ry="2.6" /><path d="M5 5.5v6c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6v-6" /><path d="M5 11.5v6c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6v-6" /></I>,
  layers:<I><path d="M12 3 3 8l9 5 9-5-9-5z" /><path d="M3 13l9 5 9-5" /></I>,
  graph: <I><circle cx="6" cy="6" r="2.4" /><circle cx="18" cy="9" r="2.4" /><circle cx="9" cy="18" r="2.4" /><path d="M8 7.2l8 0.6M7.6 16l1.2-7.4M16.4 11l-6 5.4" /></I>,
  chat:  <I><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-5A8 8 0 1 1 21 12z" /><path d="M9 11h6M9 14h4" /></I>,
  cloud: <I><path d="M7 18a4 4 0 0 1-.6-7.95A5.5 5.5 0 0 1 17 9.5a3.5 3.5 0 0 1-.5 8.5z" /><path d="M12 13v5M9.5 15.5 12 13l2.5 2.5" /></I>,
};

const UI = {
  lock:    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>,
  alert:   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 9v4M12 17h.01" /><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg>,
  refresh: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7L21 8" /><path d="M21 3v5h-5" /></svg>,
  plus:    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>,
  minus:   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M5 12h14" /></svg>,
  fit:     <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 9V5a1 1 0 0 1 1-1h4M20 9V5a1 1 0 0 0-1-1h-4M4 15v4a1 1 0 0 0 1 1h4M20 15v4a1 1 0 0 0-1 1h-4" /></svg>,
  chevron: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6" /></svg>,
  check:   <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg>,
  x:       <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>,
  arrow:   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h13M13 6l6 6-6 6" /></svg>,
  portal:  <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M7 17 17 7M9 7h8v8" /></svg>,
};

window.StageIcon = ({ name }) => STAGE_ICON[name] || STAGE_ICON.doc;
window.UIIcon = UI;
