Display primitives: **Card** surface, **Badge** origin/status pill, **StatusChip** stage indicator, and **QuotaBar** usage meter.

```jsx
<Card>选择文档查看详情</Card>
<Card featured>Research Agent</Card>
<Badge tone="info">本地上传</Badge>
<Badge tone="violet">Zotero 同步</Badge>
<Badge tone="warn">已脱管</Badge>
<StatusChip status="ready">就绪</StatusChip>
<StatusChip status="degraded">待处理</StatusChip>
<QuotaBar ratio={0.298} label="R2 对象存储" detail="3.2 GB / 10 GB" />
```

- `Card`: `featured` adds gradient hairline + glow; `pad={false}` removes padding.
- `Badge tone`: neutral · accent · info · ok · warn · danger · violet.
- `StatusChip status`: ready · degraded (pulses) · off · info.
- `QuotaBar`: fill turns warn at ratio ≥ 0.8, danger at ≥ 0.95.
