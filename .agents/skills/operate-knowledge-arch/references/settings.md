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
- `rebuild`: saved, but correct activation also needs a separately confirmed restart and a user-operated
  index rebuild. Never start that rebuild from this Skill.

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

Never bypass a rejected key by editing plugin files or storage. Never expose or modify passwords, API
keys, tokens, storage paths marked structural, or any key absent from `config-options`.
