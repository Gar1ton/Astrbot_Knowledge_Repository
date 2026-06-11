Form controls for the console: text **Input**, **Tag** pills, **Toggle** switch, and the custom **Select** dropdown. All share the warm surface, accent focus ring, and 9–10px radii.

```jsx
<Input placeholder="集合名称" />
<Input mono size="sm" defaultValue="knowledge_repository.db" />
<Tag label="transformer" />
<Tag label="rag" accent onRemove={() => {}} />
<Toggle checked={auto} onChange={setAuto} label="自动索引" />
<Select value={col} onChange={setCol} options={[{value:'papers',label:'papers'}]} />
```

- `Input`: `size` sm/md, `invalid` for danger ring, `mono` for IDs/model names.
- `Tag`: `accent` = active filter; `onRemove` shows a ×.
- `Toggle`: track turns accent when on; optional `label`.
- `Select`: pass `options={[{value,label}]}`; opens an animated popover with a check on the active row.
