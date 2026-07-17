# Research workflow

## 1. Establish scope cheaply

- Skip `doctor` when a preceding command already proved the API works.
- If the user names a paper, author, year, DOI, tag, or collection but the exact scope is uncertain, run:

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py catalog --query "terms"
```

- Use document and collection metadata to select the narrowest relevant collection. Do not load full
  documents merely to discover titles.

## 2. Retrieve compact evidence

For an exact question, use one query. For comparison or synthesis, decompose the question into 2-4
independent English retrieval queries when English papers are likely, while preserving important names,
DOIs, and technical terms.

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py search `
  --query "first focused query" --query "second focused query" --all
```

Prefer `--collection NAME` over `--all` when scope is known. Defaults return at most 10 fused hits with
1600 characters each. Increase `--limit` or `--max-chars` only when the question genuinely needs it;
hard limits are 20 hits and 4000 characters per hit.

The client performs deterministic reciprocal-rank fusion, chunk/content deduplication, context assembly,
and document metadata enrichment. It does not call any LLM endpoint.

## 3. Correct only material gaps

Inspect whether the evidence covers the entities, relationship, comparison dimensions, time period, and
counterevidence requested. If one material gap remains, issue one corrective search. Stop after that and
report unresolved gaps rather than expanding indefinitely.

When a precise passage or broader argument is essential, page through one document at a time:

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py read `
  --doc-id DOCUMENT_ID --start 0 --max-chars 12000
```

Continue from the returned `end` only if `has_more` is true and more text is necessary.

## 4. Answer from evidence

- Put citations directly after supported claims, using available title, author/year, page, and `doc_id`.
- Distinguish the source's claim from your inference. Label cross-source synthesis as synthesis.
- Note conflicting evidence and uncertainty.
- Do not invent page numbers, bibliographic fields, or findings.
- Keep quotations short; prefer paraphrase and synthesis.
- If local evidence is insufficient, say what was searched and what evidence is missing. Ask before using
  external web sources unless the user already requested them.
