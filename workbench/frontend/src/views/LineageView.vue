<script setup lang="ts">
import cytoscape, { type Core } from "cytoscape"
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute } from "vue-router"
import { PhArrowClockwise, PhGitBranch, PhMagnifyingGlass, PhPlay } from "@phosphor-icons/vue"
import {
  getLineageOverview,
  getLineagePapers,
  getPaperLineage,
  startLineageExtraction,
  type LineageEdge,
  type LineageGraph,
  type LineageOverview,
  type LineagePaper,
} from "../api"

const relationOptions = [
  { value: "extends", label: "继承扩展", color: "#4f7f73" },
  { value: "improves", label: "性能改进", color: "#218f68" },
  { value: "addresses_gap_of", label: "问题缺口", color: "#d1783f" },
  { value: "differs_from", label: "方法差异", color: "#8764a3" },
  { value: "compares_with", label: "实验比较", color: "#497b9e" },
  { value: "uses", label: "采用方法", color: "#9a7b36" },
  { value: "cites", label: "一般引用", color: "#a8afaa" },
]
const relationLabels = Object.fromEntries(relationOptions.map((item) => [item.value, item.label]))
const relationColors = Object.fromEntries(relationOptions.map((item) => [item.value, item.color]))

const overview = ref<LineageOverview | null>(null)
const route = useRoute()
const papers = ref<LineagePaper[]>([])
const selectedPaperId = ref("")
const graph = ref<LineageGraph | null>(null)
const graphElement = ref<HTMLElement | null>(null)
const selectedEdge = ref<LineageEdge | null>(null)
const query = ref("")
const loading = ref(false)
const extracting = ref(false)
const error = ref("")
const message = ref("")
const enabled = ref<Record<string, boolean>>(Object.fromEntries(relationOptions.map((item) => [item.value, true])))
let network: Core | null = null
let searchTimer: ReturnType<typeof setTimeout> | undefined
let refreshTimer: ReturnType<typeof setInterval> | undefined

const selectedPaper = computed(() => papers.value.find((paper) => paper.id === selectedPaperId.value) ?? null)
const enabledRelations = computed(() => relationOptions.filter((item) => enabled.value[item.value]).map((item) => item.value))

async function loadPapers() {
  const data = await getLineagePapers(query.value)
  papers.value = data.items
  const requestedPaper = typeof route.query.paper === "string" ? route.query.paper : ""
  if (requestedPaper && !selectedPaperId.value && papers.value.some((paper) => paper.id === requestedPaper)) selectedPaperId.value = requestedPaper
  if (!papers.value.some((paper) => paper.id === selectedPaperId.value)) {
    selectedPaperId.value = papers.value.find((paper) => paper.reference_count > 0)?.id ?? papers.value[0]?.id ?? ""
  }
}

async function loadOverview() {
  overview.value = await getLineageOverview()
}

async function loadGraph() {
  if (!selectedPaperId.value) {
    graph.value = null
    network?.destroy()
    network = null
    return
  }
  if (!enabledRelations.value.length) {
    graph.value = { center_paper_id: selectedPaperId.value, nodes: [], edges: [], truncated: false }
    selectedEdge.value = null
    network?.destroy()
    network = null
    return
  }
  loading.value = true
  error.value = ""
  try {
    graph.value = await getPaperLineage(selectedPaperId.value, enabledRelations.value)
    selectedEdge.value = graph.value.edges[0] ?? null
    await nextTick()
    renderGraph()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "谱系加载失败"
  } finally {
    loading.value = false
  }
}

function renderGraph() {
  network?.destroy()
  if (!graphElement.value || !graph.value) return
  const edgesById = new Map(graph.value.edges.map((edge) => [edge.id, edge]))
  network = cytoscape({
    container: graphElement.value,
    elements: [
      ...graph.value.nodes.map((node) => ({ data: { ...node, label: node.title } })),
      ...graph.value.edges.map((edge) => ({
        data: { ...edge, label: relationLabels[edge.relation_type] ?? edge.relation_type, color: relationColors[edge.relation_type] },
      })),
    ],
    style: [
      { selector: "node", style: { "background-color": "#f8f7f1", "border-color": "#54746c", "border-width": 1.5, color: "#172629", label: "data(label)", "font-size": "10px", "text-wrap": "ellipsis", "text-max-width": "145px", width: 42, height: 42, "text-valign": "bottom", "text-margin-y": 8 } },
      { selector: "node[?is_center]", style: { "background-color": "#cce66d", "border-color": "#2b6658", "border-width": 3, width: 62, height: 62, "font-weight": 700 } },
      { selector: "edge", style: { width: 2, "line-color": "data(color)", "target-arrow-color": "data(color)", "target-arrow-shape": "triangle", "curve-style": "bezier", label: "data(label)", "font-size": "8px", color: "#697776", "text-background-color": "#fbfaf6", "text-background-opacity": 0.9, "text-background-padding": "2px" } },
      { selector: "edge:selected", style: { width: 5, "overlay-color": "#cce66d", "overlay-opacity": 0.25, "overlay-padding": 6 } },
    ],
    layout: { name: "breadthfirst", roots: [`paper:${selectedPaperId.value}`], directed: true, spacingFactor: 1.35, padding: 35, animate: false },
    minZoom: 0.25,
    maxZoom: 2.5,
  })
  network.on("tap", "edge", (event) => {
    selectedEdge.value = edgesById.get(event.target.id()) ?? null
  })
}

async function startExtraction() {
  if (!selectedPaperId.value) return
  extracting.value = true
  error.value = ""
  try {
    const result = await startLineageExtraction(selectedPaperId.value)
    message.value = `${result.message}；完成后页面会自动刷新。`
    let attempts = 0
    clearInterval(refreshTimer)
    refreshTimer = setInterval(async () => {
      attempts += 1
      await Promise.all([loadOverview(), loadPapers(), loadGraph()])
      if ((graph.value?.edges.length ?? 0) > 0 || attempts >= 30) clearInterval(refreshTimer)
    }, 4000)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "任务启动失败"
  } finally {
    extracting.value = false
  }
}

watch(selectedPaperId, loadGraph)
watch(enabled, loadGraph, { deep: true })
watch(query, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(loadPapers, 260)
})

onMounted(async () => {
  try {
    await Promise.all([loadOverview(), loadPapers()])
    await loadGraph()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "相关工作谱系加载失败"
  }
})
onBeforeUnmount(() => {
  network?.destroy()
  clearTimeout(searchTimer)
  clearInterval(refreshTimer)
})
</script>

<template>
  <section class="page lineage-page">
    <div class="hero-row">
      <div>
        <p class="page-kicker">RELATED WORK LINEAGE</p>
        <h2>相关工作谱系</h2>
        <p class="lede">查看论文从哪里来、如何评价前置工作，以及每条关系对应的正文证据。图中的机器判断不会覆盖原始引用。</p>
      </div>
      <div class="parser-state" :data-ready="overview?.parser.ready">
        <span></span><div><strong>{{ overview?.parser.name ?? "GROBID" }}</strong><small>{{ overview?.parser.ready ? "解析服务就绪" : "解析服务未就绪" }}</small></div>
      </div>
    </div>

    <div v-if="overview" class="metric-grid metric-grid--compact lineage-metrics">
      <article class="metric"><PhGitBranch :size="20" /><span>已有谱系论文</span><strong>{{ overview.papers_with_lineage }}</strong><small>完成至少一个参考条目</small></article>
      <article class="metric"><PhGitBranch :size="20" /><span>参考工作</span><strong>{{ overview.reference_works }}</strong><small>消歧后的外部工作</small></article>
      <article class="metric"><PhGitBranch :size="20" /><span>关系证据</span><strong>{{ overview.evidence }}</strong><small>带引用语境的机器断言</small></article>
    </div>

    <div v-if="message" class="notice">{{ message }}</div>
    <div v-if="error" class="notice notice--error">{{ error }}</div>

    <div class="lineage-toolbar panel">
      <label class="search-field"><PhMagnifyingGlass /><input v-model="query" placeholder="搜索可生成谱系的论文" /></label>
      <select v-model="selectedPaperId">
        <option v-if="!papers.length" value="">暂无可用论文</option>
        <option v-for="paper in papers" :key="paper.id" :value="paper.id">{{ paper.conference }} {{ paper.year }} · {{ paper.title }} ({{ paper.reference_count }})</option>
      </select>
      <button class="primary-button lineage-action" :disabled="!selectedPaperId || extracting" @click="startExtraction"><PhPlay /> {{ extracting ? "正在启动" : "生成 / 更新谱系" }}</button>
      <button class="quiet-button" :disabled="!selectedPaperId || loading" @click="loadGraph"><PhArrowClockwise /> 刷新</button>
    </div>

    <div class="relation-filters">
      <label v-for="item in relationOptions" :key="item.value"><input v-model="enabled[item.value]" type="checkbox" /><i :style="{ background: item.color }"></i>{{ item.label }}<small>{{ overview?.relations[item.value] ?? 0 }}</small></label>
    </div>

    <div class="lineage-workspace">
      <article class="panel graph-panel">
        <div class="panel__heading"><div><p class="page-kicker">EVIDENCE GRAPH</p><h3>{{ selectedPaper?.title ?? "选择一篇论文" }}</h3></div><span>{{ graph?.edges.length ?? 0 }} 条关系</span></div>
        <div v-if="loading" class="empty-state">正在构建谱系视图…</div>
        <div v-else-if="!selectedPaperId" class="empty-state">没有已映射到 arXiv 的论文。</div>
        <div v-else-if="!enabledRelations.length" class="lineage-empty"><PhGitBranch :size="34" /><strong>没有启用关系类型</strong><span>在上方至少勾选一种关系后，图谱才会显示对应证据。</span></div>
        <div v-else-if="graph && !graph.edges.length" class="lineage-empty"><PhGitBranch :size="34" /><strong>这篇论文还没有谱系证据</strong><span>点击“生成 / 更新谱系”，工作台会获取 PDF 并调用 GROBID 解析相关工作和参考文献。</span></div>
        <div ref="graphElement" class="lineage-canvas" :class="{ 'lineage-canvas--hidden': !graph?.edges.length }"></div>
      </article>

      <aside class="panel evidence-panel">
        <div class="panel__heading"><div><p class="page-kicker">SOURCE EVIDENCE</p><h3>关系证据</h3></div><span v-if="selectedEdge">{{ relationLabels[selectedEdge.relation_type] }}</span></div>
        <template v-if="selectedEdge">
          <div class="evidence-score"><strong>{{ Math.round(selectedEdge.confidence * 100) }}%</strong><span>机器置信度 · {{ selectedEdge.status }}</span></div>
          <dl class="data-list"><div><dt>章节</dt><dd>{{ selectedEdge.evidence.section || "未识别" }}</dd></div><div><dt>页码</dt><dd>{{ selectedEdge.evidence.page || "—" }}</dd></div><div><dt>分类器</dt><dd>{{ selectedEdge.evidence.classifier }} / {{ selectedEdge.evidence.classifier_version }}</dd></div></dl>
          <blockquote>{{ selectedEdge.evidence.context }}</blockquote>
          <details><summary>来源与原始参考文献</summary><p>{{ selectedEdge.evidence.raw_reference || "原始参考文献文本未提供" }}</p><code>{{ selectedEdge.evidence.source_path }}</code><code>sha256: {{ selectedEdge.evidence.source_sha256 }}</code></details>
        </template>
        <div v-else class="empty-state">点击图中的关系边查看原文证据。</div>
      </aside>
    </div>
  </section>
</template>
