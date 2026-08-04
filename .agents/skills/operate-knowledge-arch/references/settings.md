# Settings workflow

## 1. Inspect before proposing

List the runtime-writable keys and their consequences:

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py config-options
```

Read the current effective value, optionally for one section:

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py config-show --section SECTION
```

Secret-shaped keys are redacted even if the API already masks them.

## 2. Preview the exact mutation

Convert the user's natural-language intent to one writable `SECTION KEY VALUE` tuple. Run without
`--apply` first:

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py `
  config-set SECTION KEY VALUE
```

Show the returned current value, proposed value, and consequence:

- `none`: saved without restart or rebuild.
- `restart`: saved, then a separately confirmed plugin restart is needed.
- `rebuild`: saved, but correct activation also needs a separately confirmed restart and an index
  rebuild. Section 4 covers that rebuild; never start it as a silent side effect of the config change.

Ask for explicit confirmation of the exact diff. A vague earlier request to "configure it" is not
confirmation of a newly discovered value or consequence.

## 3. Apply only after confirmation

After confirmation, repeat the same command with `--apply`. Do not combine multiple unreviewed changes.

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py `
  config-set SECTION KEY VALUE --apply
```

Report the API result. If a restart is required, preview it first:

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py restart
```

Explain that the WebUI connection will briefly drop. Only after separate confirmation run:

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py restart --apply
```

## 4. Index rebuild

`index-rebuild --apply` is the programmatic equivalent of the WebUI "重建索引" button. It is a
mutation: run it only when the user asks for a rebuild, never on your own initiative.

Check the state first — it is read-only and often makes the rebuild unnecessary:

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py index-status
```

- `pending_reindex_count: 0` and `compatible: true`: nothing to rebuild. Say so instead of rebuilding.
- `active_job` is not null: a rebuild is already running. Report its `progress_percent` and wait;
  starting another one does nothing, because the server is single-flight and returns the same job.
- `auto_rebuild_enabled: true` (default since v1.1.2): the plugin drains the queue by itself after a
  short debounce. Documents that just arrived are usually already handled — say that before offering a
  manual rebuild, and prefer waiting one debounce window over rebuilding immediately.
- `auto_rebuild_enabled: false`: a manual rebuild is the only way the queue gets drained. Offer either
  the rebuild or `config-set vector_db auto_rebuild_enabled true`, which needs no restart.

Preview before applying:

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py index-rebuild
```

Report `pending_reindex_count` and the effect: every pending document is re-embedded, and when the
index is incompatible the server clears the whole vector collection first, so retrieval stays degraded
until the rebuild finishes. Ask for explicit confirmation, then:

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py index-rebuild --apply --wait
```

Without `--wait` the command returns as soon as the background job starts; poll `index-status` for
progress. With `--wait` it polls until a terminal status. A `status: "timeout"` result means the client
stopped observing — the rebuild is still running. Report that honestly and keep polling `index-status`;
never describe it as cancelled and never start a second rebuild.

A `final_status` of `partial_failure` means some documents failed and stayed queued. Report the failed
count and the first error rather than claiming success.

Never bypass a rejected key by editing plugin files or storage. Never expose or modify passwords, API
keys, tokens, storage paths marked structural, or any key absent from `config-options`.
