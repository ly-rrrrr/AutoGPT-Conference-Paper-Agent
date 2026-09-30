<script setup lang="ts">
import { onMounted, ref } from "vue"
import StatusBadge from "../components/StatusBadge.vue"
import { getDocuments, type DocumentRecord } from "../api"

const items = ref<DocumentRecord[]>([])
const summary = ref<Record<string, number>>({})
const total = ref(0)
const error = ref("")
async function load() { try { const result = await getDocuments(); items.value = result.items; summary.value = result.summary; total.value = result.total } catch (reason) { error.value = reason instanceof Error ? reason.message : "加载失败" } }
onMounted(load)
</script>
<template>
  <section class="page"><div class="hero-row"><div><p class="page-kicker">KNOWLEDGE LAYER</p><h2>文档资产</h2><p class="lede">观察 PDF 是否可用、是否解析以及解析器版本。V1 不会静默下载或嵌入文档。</p></div></div><div v-if="error" class="notice notice--error">{{ error }}</div><div class="metric-grid metric-grid--compact"><article class="metric"><span>论文总量</span><strong>{{ total }}</strong><small>可建设知识资产</small></article><article class="metric"><span>原文可用</span><strong>{{ summary.AVAILABLE ?? 0 }}</strong><small>已有本地 PDF</small></article><article class="metric"><span>已解析</span><strong>{{ summary.PARSED ?? 0 }}</strong><small>可进入检索</small></article><article class="metric"><span>待建设</span><strong>{{ summary.MISSING ?? 0 }}</strong><small>尚无文档资产</small></article></div><div class="paper-table-wrap"><table class="paper-table"><thead><tr><th>论文</th><th>状态</th><th>类型</th><th>解析器</th><th>路径 / 错误</th></tr></thead><tbody><tr v-for="item in items" :key="item.paper_id"><td><RouterLink :to="`/papers/${item.paper_id}`">{{ item.title }}</RouterLink></td><td><StatusBadge :status="item.status" /></td><td>{{ item.kind }}</td><td>{{ item.parser ? `${item.parser} ${item.parser_version || ''}` : '—' }}</td><td class="mono config-cell">{{ item.last_error || item.path || '—' }}</td></tr></tbody></table></div><p class="footer-note">列表仅展示最近 100 篇，顶部统计覆盖全部论文。</p></section>
</template>
