<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRoute } from "vue-router"
import { PhArrowLeft, PhArrowSquareOut, PhHeart } from "@phosphor-icons/vue"
import StatusBadge from "../components/StatusBadge.vue"
import { getPaper, type PaperDetail } from "../api"

const route = useRoute()
const paper = ref<PaperDetail | null>(null)
const error = ref("")
async function load() { try { paper.value = await getPaper(String(route.params.id)) } catch (reason) { error.value = reason instanceof Error ? reason.message : "加载失败" } }
onMounted(load)
</script>
<template>
  <section class="page detail-page">
    <RouterLink class="back-link" to="/papers"><PhArrowLeft /> 返回论文目录</RouterLink>
    <div v-if="error" class="notice notice--error">{{ error }} <button @click="load">重试</button></div><div v-else-if="!paper" class="notice">正在读取论文…</div>
    <template v-else>
      <div class="detail-hero"><div><p class="page-kicker">{{ paper.conference }} {{ paper.year }} · {{ paper.topic }}</p><h2>{{ paper.title }}</h2><p class="lede">{{ paper.authors.join(" · ") }}</p></div><div class="detail-actions"><a v-if="paper.arxiv_url" :href="paper.arxiv_url" target="_blank">arXiv <PhArrowSquareOut /></a><span><PhHeart /> {{ paper.likes ?? "—" }}</span></div></div>
      <div class="detail-grid"><article class="panel"><div class="panel__heading"><h3>元数据与映射</h3><StatusBadge :status="String(paper.mapping?.status ?? '')" /></div><dl class="data-list"><div><dt>arXiv ID</dt><dd>{{ paper.arxiv_id || "未映射" }}</dd></div><div><dt>匹配原因</dt><dd>{{ paper.mapping?.reason || "—" }}</dd></div><div><dt>匹配器版本</dt><dd>{{ paper.mapping?.matcher_version || "—" }}</dd></div><div><dt>来源文件</dt><dd class="mono">{{ paper.mapping?.source_path || "—" }}</dd></div></dl></article><article class="panel"><div class="panel__heading"><h3>文档资产</h3><StatusBadge :status="String(paper.document?.status ?? 'MISSING')" /></div><p class="muted">{{ paper.document ? paper.document.path : "PDF 尚未纳入本地知识库；V1 只观察状态，不自动下载。" }}</p></article></div>
      <article class="panel analysis-panel"><div class="panel__heading"><div><p class="page-kicker">MACHINE ANALYSIS</p><h3>结构化论文分析</h3></div><StatusBadge :status="paper.analysis?.status" /></div><div v-if="paper.analysis?.payload" class="analysis-content"><section v-for="(value, key) in paper.analysis.payload" :key="key"><h4>{{ String(key).replaceAll('_', ' ') }}</h4><p>{{ value }}</p></section></div><p v-else class="muted">{{ paper.analysis?.error_detail || "尚无分析结果" }}</p><div v-if="paper.analysis?.answers.length" class="answers"><section v-for="item in paper.analysis.answers" :key="item.question"><h4>{{ item.question }}</h4><p>{{ item.answer }}</p></section></div></article>
    </template>
  </section>
</template>
