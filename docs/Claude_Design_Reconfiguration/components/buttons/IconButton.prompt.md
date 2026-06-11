Square quiet button for a single icon — toolbar toggles, close/collapse controls.

```jsx
<IconButton title="收起来源面板" active={showSources} onClick={toggle}>
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2"/><line x1="15" y1="3" x2="15" y2="21"/>
  </svg>
</IconButton>
```

- `active` switches to the accent-soft surface (use for panel-open / selected toggles).
- `size` sets the square edge (default 28px). Always feed it a 13–15px Lucide-style stroke icon.
