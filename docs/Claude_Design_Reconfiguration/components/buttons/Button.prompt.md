Pill-shaped primary action control used across every console toolbar, modal, and form.

```jsx
<Button variant="primary" onClick={save}>上传文档</Button>
<Button variant="outline" size="sm">移动集合</Button>
<Button variant="ghost" size="sm">取消</Button>
<Button variant="danger" size="sm">删除</Button>
<Button loading>保存中</Button>
```

- `variant`: `primary` (filled accent) · `outline` (accent hairline) · `ghost` (quiet neutral) · `danger` (destructive).
- `size`: `sm` (12px) · `md` (13px, default).
- `loading` shows a spinner and disables the button. Always pills (`--radius-pill`); presses scale to 0.97.
