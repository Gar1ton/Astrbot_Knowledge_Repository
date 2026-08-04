# Research workflow

## 1. Establish scope cheaply

- Skip `doctor` when a preceding command already proved the API works.
- If the user names a paper, author, year, DOI, tag, or collection but the exact scope is uncertain, run:

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py catalog --query "terms"
```

- Use document and collection metadata to select the narrowest relevant collection. Do not load full
  documents merely to discover titles.

## 2. Select and call the evidence mode

Choose the least expensive mode that matches the question:

- `default`: one exact lookup or a narrow factual question; one query, one round.
- `enhanced`: explanation, comparison, or synthesis across a few dimensions; plan 2-4 focused
  subqueries and use at most one corrective round.
- `deep_thinking`: broad, contested, multi-hop, or counterevidence-sensitive research; first lock a
  concrete collection, then work within the endpoint's returned query and round limits.

Preserve names, DOI fragments, and technical terms. Prefer English subqueries for English papers.

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py ask-evidence `
  --question "original user question" --query "focused retrieval query" `
  --mode default --all
```

For enhanced or deep work, repeat `--query` within the returned per-round limit. Prefer
`--collection NAME` over `--all` whenever scope is known; `deep_thinking` requires it.

The endpoint performs deterministic retrieval, fusion, reranking, cutoff, and metadata enrichment. It
returns evidence only with `plugin_llm_used=false` and `full_text_used=false`. Codex performs all
planning, assessment, correction, and synthesis.

## 3. Correct only material gaps

Check whether evidence covers the requested entities, relationships, comparison dimensions, time period,
and counterevidence. If a material gap remains and the returned `limits.max_rounds` permits it, issue a
targeted next call with `--round 2` (or the next allowed number) and new queries. Combine prior evidence
in Codex; the endpoint does not generate or remember an answer. Stop at the limit and report unresolved
gaps instead of expanding indefinitely.

Use the low-level `search` command only to troubleshoot retrieval or inspect deterministic raw fusion,
not as the default research path.

## 4. Gate document reading

Do not read a document merely because it is the top hit. Reading is allowed only when:

1. metadata/evidence has anchored one unique paper and a passage or broader argument from that paper is
   necessary; use `--intent anchored`; or
2. the user explicitly asked to read the full text; use `--intent full-text`.

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py read `
  --doc-id DOCUMENT_ID --intent anchored --start 0 --max-chars 12000
```

The server returns only the requested page. Continue from `end` only when `has_more` is true and the
allowed reading intent still requires more text.

### Large reads require explicit consent

`--whole` reads from `--start` to the end of the document. There is no character cap, but any single
read larger than the server's confirmation threshold comes back as a preview instead of text:

```json
{"status": "preview", "total_chars": 183421, "confirm_threshold_chars": 60000,
 "estimated_tokens": 172530, "requires_explicit_confirmation": true, "content_returned": false}
```

Do not retry blindly. Tell the user how large the document is, then rerun with the confirmation flag
only after they agree:

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py read `
  --doc-id DOCUMENT_ID --intent full-text --whole --confirm-large-read
```

Read the threshold from `confirm_threshold_chars` in the response; never hardcode the number — it is
defined once on the server and may change.

The gate is evaluated per call, on the number of characters that call would return. Paging through a
long document in 12 000-character requests therefore never trips it, which is exactly why the reading
discipline above still binds: page only while the anchored reading intent genuinely requires more text.

## 5. Answer from evidence

Cite in Harvard style. Every evidence item returned by `ask-evidence` carries two server-computed
strings; use them verbatim and never hand-roll a citation format:

- `harvard_in_text` — e.g. `Vaswani et al., 2017, p. 3`. Wrap it in parentheses and place it directly
  after the claim it supports: `(Vaswani et al., 2017, p. 3)`. Merge adjacent citations into one pair
  of parentheses separated by `; `.
- `harvard_reference` — e.g. `Vaswani, A. et al. (2017) 'Attention is all you need', NeurIPS. doi: …`.
  Collect the distinct values, sort them alphabetically, and list them under a final `References`
  heading.

Documents with no bibliographic metadata degrade to `Anon.` and `n.d.` — that is correct output, not an
error. Do not substitute the `doc_id`, chunk id, or a bare `[n]` for a citation, and do not repair a
degraded citation by guessing the author or year.

When troubleshooting via the low-level `search` command, hits carry raw `title` / `authors` / `year` /
`doi` / `page` instead of the two rendered strings; assemble the same Harvard forms from those fields.

- Distinguish the source's claim from your inference. Label cross-source synthesis as synthesis.
- Note conflicting evidence and uncertainty.
- Do not invent page numbers, bibliographic fields, or findings.
- Keep quotations short; prefer paraphrase and synthesis.
- If local evidence is insufficient, say what was searched and what evidence is missing. Ask before using
  external web sources unless the user already requested them.
