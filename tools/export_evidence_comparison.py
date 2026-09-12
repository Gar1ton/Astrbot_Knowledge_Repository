"""把保存的 Ask JSON 响应导出为无正文的单条评测 JSONL；不调用模型或真实实例。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("response", type=Path)
    parser.add_argument("--question-id", required=True)
    parser.add_argument("--code-version", required=True)
    parser.add_argument("--corpus-version", required=True)
    parser.add_argument("--config-version", required=True)
    parser.add_argument("--latency-ms", type=int)
    args = parser.parse_args()
    response = json.loads(args.response.read_text(encoding="utf-8"))
    thinking = response.get("thinking_trace") or {}
    trace = thinking.get("evidence_trace") or {}
    usage = trace.get("usage") or {}
    calls = usage.get("calls", [])
    selection = (trace.get("selections") or [{}])[-1]
    row = {
        "question_id": args.question_id,
        "mode": response.get("requested_retrieval_mode"),
        "code_version": args.code_version,
        "corpus_version": args.corpus_version,
        "config_version": args.config_version,
        "latency_ms": args.latency_ms,
        "models": sorted({c.get("model", "") for c in calls}),
        "call_count": usage.get("call_count"),
        "tokens_by_measurement": {
            kind: sum((c.get("input_tokens") or 0) + (c.get("output_tokens") or 0)
                      for c in calls if c.get("measurement") == kind)
            for kind in ("actual", "estimated")
        },
        "unknown_calls": usage.get("unknown_calls"),
        "usage_available": bool(calls),
        "evidence": [{"chunk_id": s.get("chunk_id"), "doc_id": s.get("doc_id")}
                     for s in response.get("sources", [])],
        "uncovered_aspects": selection.get("uncovered_aspect_ids", []),
        "fallback_reason": response.get("fallback_reason"),
    }
    print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
