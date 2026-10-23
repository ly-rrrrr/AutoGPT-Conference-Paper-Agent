<script setup lang="ts">
import { onMounted, ref } from "vue"
import StatusBadge from "../components/StatusBadge.vue"
import {
  getDocuments,
  getInfrastructureOverview,
  startVectorIndex,
  type DocumentRecord,
  type InfrastructureOverview,
} from "../api"

const items = ref<DocumentRecord[]>([])
const summary = ref<Record<string, number>>({})
const total = ref(0)
const infrastructure = ref<InfrastructureOverview | null>(null)
const error = ref("")
const message = ref("")
const indexing = ref(false)

async function load() {
  try {
    const [documents, foundation] = await Promise.all([
      getDocuments(),
      getInfrastructureOverview(),
    ])
    items.value = documents.items
    summary.value = documents.summary
    total.value = documents.total
    infrastructure.value = foundation
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "加载失败"
  }
}

onMounted(load)

async function startIndexing() {
  if (!window.confirm("将调用默认 Embedding 模型，最多索引 500 个尚未索引的正文块。是否继续？")) return
  indexing.value = true
  error.value = ""
  try {
    const result = await startVectorIndex()
    message.value = `${result.message}（运行 ${result.run_id.slice(0, 8)}）`
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "索引启动失败"
  } finally {
    indexing.value = false
  }
}
</script>

<template>
  <section class="page">
    <div class="hero-row">
      <div>
        <p class="page-kicker">KNOWLEDGE INFRASTRUCTURE</p>
        <h2>知识资产底座</h2>
        <p class="lede">PDF 是原始资产，GROBID 负责结构化，PostgreSQL 保存事实与版本，Milvus 保存可重建的检索索引。</p>
      </div>
      <div class="detail-actions">
        <RouterLink to="/knowledge/build">批量资产建设</RouterLink>
        <RouterLink to="/settings/embeddings">配置 Embedding</RouterLink>
        <button class="quiet-button" type="button" @click="load">刷新状态</button>
        <button class="primary-button" type="button" :disabled="!infrastructure?.vectors.embedding_ready || indexing" @click="startIndexing">{{ indexing ? "正在排队" : "增量建立索引" }}</button>
      </div>
    </div>

    <div v-if="message" class="notice">{{ message }}</div>
    <div v-if="error" class="notice notice--error">{{ error }}</div>

    <div v-if="infrastructure" class="metric-grid metric-grid--compact">
      <article class="metric"><span>资产版本</span><strong>{{ infrastructure.assets.revisions }}</strong><small>按内容哈希去重，可追溯</small></article>
      <article class="metric"><span>正文块</span><strong>{{ infrastructure.assets.chunks }}</strong><small>保留章节、页码与原文定位</small></article>
      <article class="metric"><span>向量记录</span><strong>{{ infrastructure.vectors.records }}</strong><small>{{ infrastructure.vectors.embedding_model ? `${infrastructure.vectors.embedding_model} · ${infrastructure.vectors.embedding_dimension} 维` : "尚未配置 Embedding" }}</small></article>
      <article class="metric"><span>排队任务</span><strong>{{ infrastructure.jobs.by_status.QUEUED ?? 0 }}</strong><small>Worker 可恢复执行</small></article>
    </div>

    <div v-if="infrastructure" class="panel-grid panel-grid--two">
      <article class="panel">
        <div class="panel__heading"><div><span class="eyebrow">SERVICES</span><h3>基础服务</h3></div></div>
        <div class="status-list">
          <div v-for="(state, service) in infrastructure.services" :key="service" class="status-row">
            <strong>{{ service }}</strong><StatusBadge :status="state" />
          </div>
        </div>
      </article>
      <article class="panel">
        <div class="panel__heading"><div><span class="eyebrow">PIPELINE</span><h3>实际数据流</h3></div></div>
        <p class="lede">PDF → GROBID TEI → 可定位正文块 → embedding → Milvus。AI 精读和综述将引用正文块，而不是只依赖预生成摘要。</p>
      </article>
    </div>

    <div class="metric-grid metric-grid--compact">
      <article class="metric"><span>论文总量</span><strong>{{ total }}</strong><small>可建设知识资产</small></article>
      <article class="metric"><span>原文可用</span><strong>{{ summary.AVAILABLE ?? 0 }}</strong><small>已有本地 PDF</small></article>
      <article class="metric"><span>已解析</span><strong>{{ summary.PARSED ?? 0 }}</strong><small>已生成结构化 TEI</small></article>
      <article class="metric"><span>待建设</span><strong>{{ summary.MISSING ?? 0 }}</strong><small>尚无文档资产</small></article>
    </div>

    <div class="paper-table-wrap">
      <table class="paper-table">
        <thead><tr><th>论文</th><th>状态</th><th>类型</th><th>解析器</th><th>路径 / 错误</th></tr></thead>
        <tbody>
          <tr v-for="item in items" :key="`${item.paper_id}-${item.kind}`">
            <td><RouterLink :to="`/papers/${item.paper_id}`">{{ item.title }}</RouterLink></td>
            <td><StatusBadge :status="item.status" /></td>
            <td>{{ item.kind }}</td>
            <td>{{ item.parser ? `${item.parser} ${item.parser_version || ''}` : "—" }}</td>
            <td class="mono config-cell">{{ item.last_error || item.path || "—" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="footer-note">列表仅展示最近 100 篇，顶部统计覆盖全部论文。</p>
  </section>
</template>
