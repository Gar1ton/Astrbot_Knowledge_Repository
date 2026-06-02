"use client";

import { createContext, useContext } from "react";

export type Lang = "zh" | "en";

const zh = {
  // 导航
  nav_ask: "Research Agent",
  nav_knowledge: "知识库",
  nav_documents: "文档",
  nav_search: "知识库检索",
  nav_graph: "知识图谱",
  nav_ops: "运维",
  nav_sync: "同步 / 备份",
  nav_quota: "配额",
  nav_settings: "设置",
  nav_logout: "退出登录",

  // 认证
  login_title: "Knowledge Repository",
  login_subtitle: "控制台登录",
  login_username: "用户名",
  login_password: "密码",
  login_btn: "登录",
  login_error: "用户名或密码错误",

  // 通用动作
  btn_upload: "上传文档",
  btn_new_collection: "新建集合",
  btn_delete: "删除",
  btn_cancel: "取消",
  btn_confirm: "确认",
  btn_save: "保存",
  btn_close: "关闭",
  btn_retry: "重试",

  // 文档工作台
  docs_all: "全部文档",
  docs_collection: "集合",
  docs_tags: "标签",
  docs_size: "大小",
  docs_updated: "更新时间",
  docs_chunks: "分块数",
  docs_no_docs: "暂无文档",
  docs_inspector_title: "文档详情",
  docs_move_collection: "移动到集合",
  docs_edit_tags: "编辑标签",
  docs_add_tag: "添加标签",
  docs_download: "下载原件",
  docs_batch_bar: "{n} 项已选中",
  docs_batch_move: "移动集合",
  docs_batch_tag: "批量打标签",
  docs_batch_delete: "批量删除",
  docs_upload_hint: "拖放文件到此处，或点击上传",
  docs_upload_collection_label: "目标集合",
  docs_upload_tags_label: "标签（逗号分隔）",
  docs_uncategorized: "未归档",
  docs_delete_collection_title: "删除集合",
  docs_delete_collection_warn: "此集合包含 {n} 个文档，删除后将自动移入「未归档」",
  docs_delete_collection_confirm_hint: "输入集合名称以确认删除",
  docs_delete_collection_btn: "确认删除",
  docs_index_mode_auto: "自动索引",
  docs_index_mode_paused: "索引暂停",
  docs_rebuild_index: "重建索引",
  docs_pending_reindex: "{n} 待索引",

  // 检索
  search_placeholder: "输入关键词检索知识库...",
  search_collection: "集合",
  search_top_k: "Top-K",
  search_btn: "检索",
  search_no_results: "未找到匹配片段",
  search_chunk_title: "片段 #{ordinal}",

  // Research Agent
  ask_placeholder: "向知识库提问...",
  ask_send: "发送",
  ask_sources: "引用来源",
  ask_open_doc: "在文档中打开",
  ask_thinking: "正在检索知识库...",
  ask_empty: "开始一段对话",
  ask_empty_title: "开始与 Research Agent 对话",
  ask_empty_sub: "您可以提问任何关于当前知识库中存储文档的问题，支持混合检索与智能生成。",
  ask_collection_all: "全部集合",
  ask_persona_toggle: "启用 Persona 角色设定",

  // 图谱
  graph_build: "构建 / 增量更新",
  graph_query: "图谱查询",
  graph_query_placeholder: "输入查询词...",
  graph_reserved: "即将上线",
  graph_nodes: "实体",
  graph_edges: "关系",
  graph_debug: "召回诊断",

  // 同步 / 备份
  sync_notion_init: "初始化 Notion 数据库",
  sync_notion_pull: "从 Notion 拉取元数据",
  sync_r2: "同步到 R2",
  sync_backup: "立即备份",
  sync_restore: "恢复备份",
  sync_reserved: "即将上线",

  // 配额
  quota_used: "已用",
  quota_limit: "上限",
  quota_ratio: "使用率",
  quota_r2: "R2 对象存储",
  quota_notion: "Notion 同步",

  // 设置
  settings_appearance: "外观",
  settings_theme: "主题",
  settings_theme_light: "浅色",
  settings_theme_dark: "深色",
  settings_theme_system: "跟随系统",
  settings_lang: "语言",
  settings_palette: "色系",
  settings_palette_default: "暖橙（默认）",
  settings_palette_moirai: "Moirai",
  settings_palette_forest: "森林",
  settings_palette_graphite: "石墨",
  settings_hue: "色相",
  settings_saturation: "饱和度",
  settings_lightness: "明度",
  settings_accent_hint: "调节滑杆自定义您的强调色。数值变动将实时级联渲染全站，并在本地持久化存储。",
  settings_config_title: "后端有效配置（只读）",
  settings_config_source: "源库",
  settings_config_r2: "R2 同步",
  settings_config_notion: "Notion 镜像",
  settings_config_web: "Web 控制台",
  settings_config_graph: "知识图谱",
  settings_config_ask: "Research Agent",
  settings_config_vector_db: "向量数据库与检索后端",

  // 配置修改
  settings_edit_title: "核心参数配置",
  settings_vector_backend: "向量数据库后端",
  settings_embed_provider: "Embedding 提供商",
  settings_embed_model: "Embedding 模型名称",
  settings_api_key: "API 密钥",
  settings_base_url: "API 接口地址",
  settings_ask_mode: "对话增强模式",
  settings_save: "保存配置",
  settings_saving: "正在保存...",
  settings_local_guide: "💡 本地离线 Embedding 部署指引",
  settings_local_guide_text: "您已选择本地模型。为支持本地离线运行（如 BAAI 检索），请确保已在 Python 终端中执行：",

  // 状态
  reserved_prefix: "即将上线",
  error_generic: "请求失败，请重试",
  loading: "加载中...",
} as const;

const en: Record<keyof typeof zh, string> = {
  nav_ask: "Research Agent",
  nav_knowledge: "Knowledge",
  nav_documents: "Documents",
  nav_search: "KB Search",
  nav_graph: "Knowledge Graph",
  nav_ops: "Operations",
  nav_sync: "Sync / Backup",
  nav_quota: "Quota",
  nav_settings: "Settings",
  nav_logout: "Logout",

  login_title: "Knowledge Repository",
  login_subtitle: "Console Login",
  login_username: "Username",
  login_password: "Password",
  login_btn: "Login",
  login_error: "Invalid credentials",

  btn_upload: "Upload",
  btn_new_collection: "New Collection",
  btn_delete: "Delete",
  btn_cancel: "Cancel",
  btn_confirm: "Confirm",
  btn_save: "Save",
  btn_close: "Close",
  btn_retry: "Retry",

  docs_all: "All Documents",
  docs_collection: "Collection",
  docs_tags: "Tags",
  docs_size: "Size",
  docs_updated: "Updated",
  docs_chunks: "Chunks",
  docs_no_docs: "No documents",
  docs_inspector_title: "Document Details",
  docs_move_collection: "Move to Collection",
  docs_edit_tags: "Edit Tags",
  docs_add_tag: "Add Tag",
  docs_download: "Download original",
  docs_batch_bar: "{n} selected",
  docs_batch_move: "Move Collection",
  docs_batch_tag: "Batch Tag",
  docs_batch_delete: "Delete",
  docs_upload_hint: "Drop files here, or click to upload",
  docs_upload_collection_label: "Target Collection",
  docs_upload_tags_label: "Tags (comma-separated)",
  docs_uncategorized: "Unfiled",
  docs_delete_collection_title: "Delete Collection",
  docs_delete_collection_warn: "This collection has {n} document(s). They will be moved to Unfiled.",
  docs_delete_collection_confirm_hint: "Type the collection name to confirm",
  docs_delete_collection_btn: "Confirm Delete",
  docs_index_mode_auto: "Auto Index",
  docs_index_mode_paused: "Index Paused",
  docs_rebuild_index: "Rebuild Index",
  docs_pending_reindex: "{n} pending",

  search_placeholder: "Search knowledge base...",
  search_collection: "Collection",
  search_top_k: "Top-K",
  search_btn: "Search",
  search_no_results: "No matching chunks found",
  search_chunk_title: "Chunk #{ordinal}",

  ask_placeholder: "Ask a question about your knowledge base...",
  ask_send: "Send",
  ask_sources: "Sources",
  ask_open_doc: "Open in Documents",
  ask_thinking: "Searching knowledge base...",
  ask_empty: "Start a conversation",
  ask_empty_title: "Start a conversation with Research Agent",
  ask_empty_sub: "Ask any question about the documents in the knowledge base. Powered by hybrid search and generation.",
  ask_collection_all: "All Collections",
  ask_persona_toggle: "Enable Persona constraints",

  graph_build: "Build / Incremental Update",
  graph_query: "Graph Query",
  graph_query_placeholder: "Enter query...",
  graph_reserved: "Coming Soon",
  graph_nodes: "Entities",
  graph_edges: "Relations",
  graph_debug: "Recall Debug",

  sync_notion_init: "Init Notion Database",
  sync_notion_pull: "Pull from Notion",
  sync_r2: "Sync to R2",
  sync_backup: "Backup Now",
  sync_restore: "Restore Backup",
  sync_reserved: "Coming Soon",

  quota_used: "Used",
  quota_limit: "Limit",
  quota_ratio: "Usage",
  quota_r2: "R2 Object Storage",
  quota_notion: "Notion Sync",

  settings_appearance: "Appearance",
  settings_theme: "Theme",
  settings_theme_light: "Light",
  settings_theme_dark: "Dark",
  settings_theme_system: "System",
  settings_lang: "Language",
  settings_palette: "Color Palette",
  settings_palette_default: "Warm Orange (Default)",
  settings_palette_moirai: "Moirai",
  settings_palette_forest: "Forest",
  settings_palette_graphite: "Graphite",
  settings_hue: "Hue",
  settings_saturation: "Saturation",
  settings_lightness: "Lightness",
  settings_accent_hint: "Adjust sliders to customize your accent color. Values will cascade render sitewide in real time and persist locally.",
  settings_config_title: "Effective Config (read-only)",
  settings_config_source: "Source Store",
  settings_config_r2: "R2 Sync",
  settings_config_notion: "Notion Mirror",
  settings_config_web: "Web Console",
  settings_config_graph: "Knowledge Graph",
  settings_config_ask: "Research Agent",
  settings_config_vector_db: "Vector Database & Backend",

  settings_edit_title: "Core Parameters Configuration",
  settings_vector_backend: "Vector DB Backend",
  settings_embed_provider: "Embedding Provider",
  settings_embed_model: "Embedding Model Name",
  settings_api_key: "API Key",
  settings_base_url: "API Base URL",
  settings_ask_mode: "Conversation Enhancement Mode",
  settings_save: "Save Config",
  settings_saving: "Saving...",
  settings_local_guide: "💡 Local Offline Embedding Guide",
  settings_local_guide_text: "You have selected a local model. To support local offline running (e.g. BAAI retrieval), please ensure you run in your Python console:",

  reserved_prefix: "Coming in",
  error_generic: "Request failed, please retry",
  loading: "Loading...",
};

export type I18nKey = keyof typeof zh;

const TRANSLATIONS: Record<Lang, Record<I18nKey, string>> = { zh, en };

export interface I18nContextValue {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: I18nKey, vars?: Record<string, string | number>) => string;
}

export const I18nContext = createContext<I18nContextValue>({
  lang: "zh",
  setLang: () => {},
  t: (key) => zh[key] ?? key,
});

export function useI18n() {
  return useContext(I18nContext);
}

export function makeT(lang: Lang) {
  return (key: I18nKey, vars?: Record<string, string | number>): string => {
    let str = TRANSLATIONS[lang][key] ?? zh[key] ?? key;
    if (vars) {
      for (const [k, v] of Object.entries(vars)) {
        str = str.replace(`{${k}}`, String(v));
      }
    }
    return str;
  };
}
