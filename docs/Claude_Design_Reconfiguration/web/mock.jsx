/* Knowledge Repository · Mock data for the prototype (offline, ?mock-equivalent). */
(function () {
  const COLLECTIONS = {
    zotero: [
      { name: "RAG & Retrieval", key: "z-rag", count: 4 },
      { name: "Agents", key: "z-agent", count: 3 },
      { name: "Foundations", key: "z-found", count: 2 },
    ],
    local: [
      { name: "papers", count: 5 },
      { name: "manuals", count: 2 },
      { name: "default", count: 1 },
    ],
    lightrag: [
      { name: "RAG & Retrieval", built: true, entities: 142, relations: 318 },
      { name: "Agents", built: true, entities: 86, relations: 173 },
    ],
  };

  const DOCS = [
    {
      doc_id: "d-react", title: "ReAct: Synergizing Reasoning and Acting in Language Models",
      authors: "Yao, S.; Zhao, J.; Yu, D.; Du, N.; Shafran, I.; Narasimhan, K.; Cao, Y.",
      year: 2023, venue: "ICLR 2023", type: "Conference paper", doi: "10.48550/arXiv.2210.03629",
      added: "2024-11-03", collection: "Agents", origin: "zotero", lightrag: true,
      tags: ["agent", "reasoning", "tool use", "LLM", "read"], ext: "pdf", size: 2_456_789, chunks: 48,
      abstract: "While large language models (LLMs) have demonstrated impressive capabilities across tasks in language understanding and interactive decision making, their abilities for reasoning and acting have largely been studied as separate topics. In this paper we explore the use of LLMs to generate both reasoning traces and task-specific actions in an interleaved manner.",
    },
    {
      doc_id: "d-lightrag", title: "LightRAG: Simple and Fast Retrieval-Augmented Generation",
      authors: "Guo, Z.; Xia, L.; Yu, Y.; Ao, T.; Huang, C.",
      year: 2024, venue: "arXiv:2410.05779", type: "Preprint", doi: "10.48550/arXiv.2410.05779",
      added: "2024-10-21", collection: "RAG & Retrieval", origin: "zotero", lightrag: true,
      tags: ["rag", "lightrag", "knowledge-graph", "retrieval"], ext: "pdf", size: 1_234_567, chunks: 28,
      abstract: "Retrieval-Augmented Generation (RAG) systems enhance large language models by integrating external knowledge sources. We propose LightRAG, which incorporates graph structures into text indexing and retrieval, employing a dual-level retrieval system that improves comprehensive information retrieval from both low-level and high-level knowledge.",
    },
    {
      doc_id: "d-attn", title: "Attention Is All You Need",
      authors: "Vaswani, A.; Shazeer, N.; Parmar, N.; Uszkoreit, J.; Jones, L.; Gomez, A.; Kaiser, Ł.; Polosukhin, I.",
      year: 2017, venue: "NeurIPS 2017", type: "Conference paper", doi: "10.48550/arXiv.1706.03762",
      added: "2024-09-15", collection: "Foundations", origin: "zotero", lightrag: false,
      tags: ["transformer", "attention", "nlp"], ext: "pdf", size: 2_956_120, chunks: 42,
      abstract: "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.",
    },
    {
      doc_id: "d-graphrag", title: "From Local to Global: A Graph RAG Approach to Query-Focused Summarization",
      authors: "Edge, D.; Trinh, H.; Cheng, N.; Bradley, J.; Chao, A.; Mody, A.; Truitt, S.; Larson, J.",
      year: 2024, venue: "arXiv:2404.16130", type: "Preprint", doi: "10.48550/arXiv.2404.16130",
      added: "2024-10-02", collection: "RAG & Retrieval", origin: "zotero", lightrag: true,
      tags: ["graphrag", "knowledge-graph", "summarization"], ext: "pdf", size: 3_120_000, chunks: 56,
      abstract: "We present a Graph RAG approach to question answering over private text corpora that scales with both the generality of user questions and the quantity of source text to be indexed.",
    },
    {
      doc_id: "d-rrf", title: "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods",
      authors: "Cormack, G. V.; Clarke, C. L. A.; Buettcher, S.",
      year: 2009, venue: "SIGIR 2009", type: "Conference paper", doi: "10.1145/1571941.1572114",
      added: "2024-10-22", collection: "RAG & Retrieval", origin: "zotero", lightrag: true,
      tags: ["rrf", "ranking", "fusion"], ext: "pdf", size: 412_000, chunks: 9,
      abstract: "We demonstrate that Reciprocal Rank Fusion (RRF), a simple method for combining the document rankings from multiple IR systems, consistently yields better results than any individual system.",
    },
    {
      doc_id: "d-manual", title: "AstrBot 知识库插件使用手册.md",
      authors: "", year: 2025, venue: "", type: "Manual", doi: "",
      added: "2025-05-01", collection: "manuals", origin: "local", lightrag: false,
      tags: ["astrbot", "manual"], ext: "md", size: 98_432, chunks: 15,
      abstract: "本手册介绍 AstrBot 知识库插件的安装、配置与日常使用：文档上传、集合管理、检索编排、LightRAG 图谱构建与 Research Agent 问答。",
    },
  ];

  // chunks per doc, with ordinal + text + page
  const CHUNKS = {
    "d-react": [
      { chunk_id: "react-0", ordinal: 0, page: 1, text: "While large language models (LLMs) have demonstrated impressive capabilities across tasks in language understanding and interactive decision making, their abilities for reasoning (e.g., chain-of-thought prompting) and acting (e.g., action plan generation) have largely been studied as separate topics." },
      { chunk_id: "react-3", ordinal: 3, page: 1, text: "ReAct prompts LLMs to generate both verbal reasoning traces and actions pertaining to a task in an interleaved manner, which allows the model to perform dynamic reasoning to create, maintain, and adjust high-level plans for acting (reason to act), while also interacting with external environments to incorporate additional information into reasoning (act to reason)." },
      { chunk_id: "react-9", ordinal: 9, page: 6, text: "On two interactive decision making benchmarks (ALFWorld and WebShop), ReAct outperforms imitation and reinforcement learning methods by an absolute success rate of 34% and 10% respectively, while being prompted with only one or two in-context examples." },
      { chunk_id: "react-12", ordinal: 12, page: 3, text: "The synergy of reasoning and acting allows the model to dynamically adjust its plans and handle exceptions, making it more robust than acting-only baselines that lack a reasoning trace." },
    ],
    "d-lightrag": [
      { chunk_id: "lr-1", ordinal: 1, page: 2, text: "LightRAG incorporates graph structures into text indexing and retrieval, employing a dual-level retrieval system that improves comprehensive information retrieval from both low-level (entity neighborhood) and high-level (cross-document themes) knowledge." },
      { chunk_id: "lr-4", ordinal: 4, page: 4, text: "The dual-level retrieval paradigm couples a keying step that extracts both local and global keys with an incremental update algorithm that ensures the timely integration of new data without rebuilding the entire index." },
      { chunk_id: "lr-7", ordinal: 7, page: 5, text: "By integrating graph-based knowledge structures with vector representations, LightRAG facilitates efficient retrieval of related entities and their relationships, significantly enhancing response coherence." },
    ],
    "d-rrf": [
      { chunk_id: "rrf-2", ordinal: 2, page: 2, text: "Reciprocal Rank Fusion (RRF) sorts the documents according to a naive scoring formula: RRFscore(d) = Σ 1/(k + rank_i(d)), where k is a constant (typically 60) that mitigates the impact of high rankings by outlier systems." },
      { chunk_id: "rrf-5", ordinal: 5, page: 3, text: "Despite its simplicity and the absence of any tuning parameters beyond k, RRF consistently outperforms more complex fusion methods such as CombMNZ and Condorcet across a range of TREC collections." },
    ],
    "d-attn": [
      { chunk_id: "attn-1", ordinal: 1, page: 2, text: "The Transformer relies entirely on self-attention to compute representations of its input and output without using sequence-aligned RNNs or convolution, enabling significantly more parallelization." },
    ],
  };

  // Zotero-style notes / annotations per doc
  const NOTES = {
    "d-react": {
      collection: "Zotero Sync",
      annotations: [
        { id: "a1", color: "purple", page: 1, text: "ReAct prompts LLMs to generate both verbal reasoning traces and actions pertaining to a task in an interleaved manner.", comment: "" },
        { id: "a2", color: "yellow", page: 6, text: "ReAct outperforms imitation and reinforcement learning methods by an absolute success rate of 34% and 10% respectively.", comment: "key result — compare with CoT baseline" },
        { id: "a3", color: "green", page: 3, text: "The synergy of reasoning and acting allows the model to dynamically adjust its plans and handle exceptions.", comment: "" },
      ],
      notes: [
        { id: "n1", body: "核心贡献：交替生成 reasoning trace 和 action，比纯 CoT 或纯 action 都强。", linked: false },
        { id: "n2", body: "与 ToolFormer 的区别在于 ReAct 不需要 finetune，zero-shot 即可。", linked: false },
      ],
    },
  };

  const GRAPH = {
    nodes: [
      { id: "n1", name: "ReAct", type: "Method", degree: 5, x: 0.5, y: 0.32 },
      { id: "n2", name: "Chain-of-Thought", type: "Method", degree: 3, x: 0.24, y: 0.2 },
      { id: "n3", name: "ALFWorld", type: "Dataset", degree: 2, x: 0.78, y: 0.22 },
      { id: "n4", name: "WebShop", type: "Dataset", degree: 2, x: 0.82, y: 0.5 },
      { id: "n5", name: "Tool Use", type: "Concept", degree: 4, x: 0.3, y: 0.62 },
      { id: "n6", name: "LLM", type: "Concept", degree: 6, x: 0.52, y: 0.66 },
    ],
    edges: [
      { source: "n1", target: "n2", relation: "extends" },
      { source: "n1", target: "n3", relation: "evaluated on" },
      { source: "n1", target: "n4", relation: "evaluated on" },
      { source: "n1", target: "n5", relation: "uses" },
      { source: "n1", target: "n6", relation: "built on" },
      { source: "n5", target: "n6", relation: "augments" },
      { source: "n2", target: "n6", relation: "prompts" },
    ],
  };

  window.KRMock = { COLLECTIONS, DOCS, CHUNKS, NOTES, GRAPH };
})();
