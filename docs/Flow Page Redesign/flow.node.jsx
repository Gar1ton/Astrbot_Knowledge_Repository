/* flow.node.jsx — Langflow 规范节点。统一一套美术（原方案 B）。
   kind: "pipe" 管线环节 | "dest" 用户可进入的真实界面（更显眼 + 跳转入口）。
   端口 handle 由 diagram 层统一绘制，不在节点内。导出 window.FlowNode。 */
const { label, STAGE_META, STATUS_TEXT, DEP_META } = window.FLOW;

const STATUS_VAR = { ready: "var(--st-ready)", degraded: "var(--st-warn)", off: "var(--st-off)", info: "var(--st-info)" };

const FIELD_LABEL = {
  embedding: "PROVIDER", vector_store: "BACKEND", ask: "MODE", graph: "ENABLED", sync: "ENABLED",
  ingest: "STORE", retrieval: "STRATEGY",
};

function StatusChip({ status }) {
  const c = STATUS_VAR[status];
  return (
    <span className="st-chip" style={{ color: c, borderColor: "color-mix(in srgb," + c + " 30%, transparent)", background: "color-mix(in srgb," + c + " 9%, transparent)" }}>
      <span className={"st-dot" + (status === "degraded" ? " st-dot--pulse" : "")} style={{ background: c }} />
      {STATUS_TEXT[status]}
    </span>
  );
}

function Field({ label: lab, locked, children }) {
  return (
    <div className="field">
      <div className="field-label">{lab}{locked && <span className="field-lock">{window.UIIcon.lock}</span>}</div>
      {children}
    </div>
  );
}

function Segmented({ options, value, onChange, disabled, status, justActivated }) {
  return (
    <div className="seg">
      {options.map((o) => {
        const active = o === value;
        return (
          <button key={o} type="button"
            className={"seg-opt" + (active ? " is-active" : "") + (active && justActivated ? " seg-flash" : "")}
            style={active ? { "--seg-accent": STATUS_VAR[status] } : undefined}
            disabled={disabled || active}
            onClick={(e) => { e.stopPropagation(); if (!active) onChange(o); }}>
            {label(o)}
          </button>
        );
      })}
    </div>
  );
}

function ReadonlyField({ value }) { return <div className="ro-field">{label(value)}</div>; }

function DepRow({ dep, installing, onInstall }) {
  const meta = DEP_META[dep.key] || { name: dep.key };
  return (
    <div className="dep-row" onClick={(e) => e.stopPropagation()}>
      <span className="dep-ico">{window.UIIcon.alert}</span>
      <div className="dep-text">
        <span className="dep-name">{window.FLOW.i18n.missing_dep}：{meta.name}</span>
        <code className="dep-pip">{dep.pip_spec}</code>
      </div>
      <button type="button" className="dep-btn" disabled={installing === dep.key}
        onClick={(e) => { e.stopPropagation(); onInstall(dep); }}>
        {installing === dep.key ? window.FLOW.i18n.installing : window.FLOW.i18n.install_now}
      </button>
    </div>
  );
}

window.FlowNode = function FlowNode({
  stage, depMap, installing, saving, justActivatedValue, selected, onSelect, onSwitch, onInstall, onOpen,
}) {
  const meta = STAGE_META[stage.id];
  const isOff = stage.status === "off";
  const isDest = meta.kind === "dest";
  const switchable = stage.id in window.FLOW.SWITCH_MAP && stage.candidates.length > 1;
  const stColor = STATUS_VAR[stage.status];
  const detailParts = window.FLOW.buildDetail(stage);
  const missing = stage.required_deps.map((k) => depMap.get(k)).filter((d) => d && !d.installed);

  return (
    <div
      className={"node" + (isDest ? " node--dest" : "") + (selected ? " is-selected" : "") + (isOff ? " is-off" : "")}
      onClick={onSelect}
      style={{ "--st": stColor }}>
      <span className="node-stripe" />

      <div className="node-head">
        <span className="node-ico">
          <window.StageIcon name={meta.icon} />
          {isDest && <span className="node-ico-portal" aria-hidden>{window.UIIcon.portal}</span>}
        </span>
        <div className="node-titles">
          <div className="node-title-row">
            <span className="node-title">{meta.name}</span>
            <span className={"node-role" + (isDest ? " node-role--dest" : "")}>{meta.role}</span>
          </div>
          <span className="node-step">STAGE {String(meta.idx).padStart(2, "0")}</span>
        </div>
        <StatusChip status={stage.status} />
      </div>

      <p className="node-desc">{meta.desc}</p>

      <div className="node-body">
        {switchable ? (
          <Field label={FIELD_LABEL[stage.id]}>
            <Segmented options={stage.candidates} value={stage.current}
              onChange={(v) => onSwitch(stage, v)} disabled={saving}
              status={stage.status} justActivated={justActivatedValue === stage.current} />
          </Field>
        ) : (
          <Field label={FIELD_LABEL[stage.id]} locked><ReadonlyField value={stage.current} /></Field>
        )}

        {detailParts.length > 0 && (
          <div className="meta-strip">{detailParts.map((p, i) => <span key={i} className="meta-chip">{p}</span>)}</div>
        )}

        {switchable && stage.consequence !== "none" && (
          <div className={"conseq" + (stage.consequence === "rebuild" ? " conseq--warn" : "")}>
            {stage.consequence === "rebuild" ? window.FLOW.i18n.consequence_rebuild : window.FLOW.i18n.consequence_restart}
          </div>
        )}

        {missing.map((dep) => <DepRow key={dep.key} dep={dep} installing={installing} onInstall={onInstall} />)}

        {/* 跳转入口：dest 用主按钮，pipe（如 graph）用次级文字链接 */}
        {meta.link && (
          <button type="button"
            className={"open-link" + (isDest ? " open-link--primary" : "")}
            onClick={(e) => { e.stopPropagation(); onOpen(meta.link); }}>
            {meta.link.label}
            <span className="open-arrow" aria-hidden>{window.UIIcon.arrow}</span>
          </button>
        )}
      </div>
    </div>
  );
};
