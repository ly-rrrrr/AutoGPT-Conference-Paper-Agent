<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import {
  getCorpusStatus,
  getStorageOverview,
  pauseCorpusBuild,
  resumeCorpusBuild,
  startCorpusBuild,
  type CorpusStatus,
  type StorageOverview,
} from "../api"

const conference = ref("CVPR")
const year = ref(2026)
const maxPapers = ref(2672)
const corpus = ref<CorpusStatus | null>(null)
const storage = ref<StorageOverview | null>(null)
const busy = ref(false)
const error = ref("")
const message = ref("")
let refreshTimer: number | undefined

const requiredFreeBytes = computed(function () {
  return Math.min(100 * 1024 ** 3, maxPapers.value * 40 * 1024 ** 2)
})

const hasEnoughSpace = computed(function () {
  return Boolean(storage.value && storage.value.free_bytes >= requiredFreeBytes.value)
})

function formatBytes(value: number) {
  return `${(value / 1024 ** 3).toFixed(1)} GB`
}

async function load() {
  try {
    const [corpusResult, storageResult] = await Promise.all([
      getCorpusStatus(conference.value, year.value),
      getStorageOverview(),
    ])
    corpus.value = corpusResult
    storage.value = storageResult
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "加载失败"
  }
}

async function act(action: "start" | "pause" | "resume") {
  if (action === "start") {
    if (!hasEnoughSpace.value) {
      error.value = `当前目录空间不足，本批次建议至少预留 ${formatBytes(requiredFreeBytes.value)}。请缩小批次或更新存储目录。`
      return
    }
    const text = `将为 ${conference.value} ${year.value} 最多 ${maxPapers.value} 篇论文排队。已解析内容会跳过，是否开始？`
    if (!window.confirm(text)) return
  }
  busy.value = true
  error.value = ""
  message.value = ""
  try {
    const result = action === "start"
      ? await startCorpusBuild(conference.value, year.value, maxPapers.value)
      : action === "pause"
        ? await pauseCorpusBuild(conference.value, year.value)
        : await resumeCorpusBuild(conference.value, year.value)
    message.value = result.message
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "操作失败"
  } finally {
    busy.value = false
  }
}

onMounted(function () {
  load()
  refreshTimer = window.setInterval(load, 5000)
})
onBeforeUnmount(function () { if (refreshTimer) window.clearInterval(refreshTimer) })
</script>

<template>
  <section class="page">
    <div class="hero-row">
      <div>
        <p class="page-kicker">CORPUS MATERIALIZATION</p>
        <h2>批量资产建设</h2>
        <p class="lede">把会议论文目录真正变成可精读、可检索的全文资产：下载 PDF，交给 GROBID 解析，再按需建立向量索引。</p>
      </div>
      <div class="detail-actions"><RouterLink to="/settings/storage">存储配置</RouterLink><button class="quiet-button" type="button" @click="load">刷新</button></div>
    </div>

    <div v-if="message" class="notice">{{ message }}</div>
    <div v-if="error" class="notice notice--error">{{ error }}</div>
    <div v-if="storage && !hasEnoughSpace" class="notice notice--error">当前目录剩余 {{ formatBytes(storage.free_bytes) }}，本批次建议预留 {{ formatBytes(requiredFreeBytes) }}。可以缩小试运行批次，完整 CVPR 2026 建议使用 100 GB 以上可用空间。</div>

    <article class="panel corpus-control">
      <div class="panel__heading"><div><span class="eyebrow">BUILD TARGET</span><h3>建设范围</h3></div><span>每 5 秒刷新</span></div>
      <div class="corpus-fields">
        <label>会议<input v-model.trim="conference" type="text" /></label>
        <label>年份<input v-model.number="year" type="number" min="2000" max="2100" /></label>
        <label>本次最多排队<input v-model.number="maxPapers" type="number" min="1" max="5000" /></label>
      </div>
      <div class="form-actions">
        <button class="primary-button" type="button" :disabled="busy" @click="act('start')">开始 / 补齐</button>
        <button class="quiet-button" type="button" :disabled="busy" @click="act('pause')">暂停待执行项</button>
        <button class="quiet-button" type="button" :disabled="busy" @click="act('resume')">恢复</button>
      </div>
    </article>

    <div v-if="corpus" class="metric-grid metric-grid--compact">
      <article class="metric"><span>论文全集</span><strong>{{ corpus.total }}</strong><small>{{ corpus.conference }} {{ corpus.year }}</small></article>
      <article class="metric"><span>有原文来源</span><strong>{{ corpus.source_ready }}</strong><small>可下载 PDF</small></article>
      <article class="metric"><span>PDF 已落盘</span><strong>{{ corpus.pdf_available }}</strong><small>内容哈希已登记</small></article>
      <article class="metric"><span>全文已解析</span><strong>{{ corpus.parsed }}</strong><small>可定位章节与段落</small></article>
      <article class="metric"><span>已向量化论文</span><strong>{{ corpus.vectorized }}</strong><small>至少一个正文块已索引</small></article>
      <article class="metric"><span>等待</span><strong>{{ corpus.jobs.QUEUED ?? 0 }}</strong><small>Worker 将继续处理</small></article>
      <article class="metric"><span>暂停</span><strong>{{ corpus.jobs.PAUSED ?? 0 }}</strong><small>恢复后继续</small></article>
      <article class="metric"><span>失败</span><strong>{{ corpus.jobs.FAILED ?? corpus.failed }}</strong><small>保留直接错误原因</small></article>
    </div>

    <article class="panel">
      <div class="panel__heading"><div><span class="eyebrow">ACTUAL FLOW</span><h3>后台实际做什么</h3></div></div>
      <div class="pipeline-steps">
        <div><strong>1. PDF</strong><span>从论文自身 PDF URL 或 arXiv 下载，计算 SHA-256；相同文件不重复下载。</span></div>
        <div><strong>2. GROBID</strong><span>提取章节、段落、参考文献和原文坐标，保存 TEI 与不可变版本。</span></div>
        <div><strong>3. Embedding</strong><span>不在本页自动花费模型额度；到“文档资产”显式执行增量索引。</span></div>
        <div><strong>4. 精读</strong><span>后续 AI 可同时读取已有问答、全文段落和框架图，并把回答定位回原文。</span></div>
      </div>
    </article>
  </section>
</template>
