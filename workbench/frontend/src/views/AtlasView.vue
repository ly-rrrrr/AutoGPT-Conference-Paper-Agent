<script setup lang="ts">
import cytoscape, { type Core } from "cytoscape"
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import {
  PhArchive,
  PhArrowClockwise,
  PhBrain,
  PhCheckCircle,
  PhGitBranch,
  PhPlay,
  PhStopCircle,
  PhWarningCircle,
} from "@phosphor-icons/vue"
import {
  getAtlasGraph,
  getAtlasInsights,
  getAtlasOverview,
  startAtlasSynthesis,
  stopAtlasSynthesis,
  updateMethodInsightStatus,
  type AtlasGraph,
  type AtlasOverview,
  type MethodInsight,
} from "../api"

const overview = ref<AtlasOverview | null>(null)
const insights = ref<MethodInsight[]>([])
const graph = ref<AtlasGraph | null>(null)
const graphElement = ref<HTMLElement | null>(null)
const selectedId = ref("")
const query = ref("")
const domain = ref("")
const maxRounds = ref(1)
const artifactsPerRound = ref(8)
const maxInputChars = ref(100000)
const loading = ref(true)
const starting = ref(false)
const stopping = ref(false)
const error = ref("")
const message = ref("")
let network: Core | null = null
let pollTimer: ReturnType<typeof setInterval> | undefined

const active = computed(function () {
  return ["RUNNING", "STOP_REQUESTED"].includes(overview.value?.latest_run?.status ?? "")
})

const domains = computed(function () {
  return [...new Set(insights.value.flatMap((item) => item.domains))].sort()
})

const filteredInsights = computed(function () {
  const needle = query.value.trim().toLocaleLowerCase()
  return insights.value.filter(function (item) {
    const domainMatch = !domain.value || item.domains.includes(domain.value)
    const text = [item.title, item.claim, item.mechanism, item.problem_pressure].join(" ").toLocaleLowerCase()
    return domainMatch && (!needle || text.includes(needle))
  })
})

const selected = computed(function () {
  return insights.value.find((item) => item.id === selectedId.value) ?? filteredInsights.value[0] ?? null
})

async function load(showLoading = true) {
  if (showLoading) loading.value = true
  error.value = ""
  try {
    const [nextOverview, nextInsights, nextGraph] = await Promise.all([
      getAtlasOverview(),
      getAtlasInsights(),
      getAtlasGraph(),
    ])
    overview.value = nextOverview
    insights.value = nextInsights.items
    graph.value = nextGraph
    if (!selectedId.value && insights.value.length) selectedId.value = insights.value[0].id
    await nextTick()
    renderGraph()
    if (active.value) ensurePolling()
    else clearPolling()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "方法认知图谱加载失败"
  } finally {
    if (showLoading) loading.value = false
  }
}

function renderGraph() {
  network?.destroy()
  if (!graphElement.value || !graph.value?.nodes.length) return
  network = cytoscape({
    container: graphElement.value,
    elements: [
      ...graph.value.nodes.map((node) => ({ data: node })),
      ...graph.value.edges.map((edge) => ({ data: edge })),
    ],
    style: [
      { selector: "node", style: { label: "data(label)", "font-size": "9px", "text-wrap": "ellipsis", "text-max-width": "130px", "text-valign": "bottom", "text-margin-y": 7, width: 30, height: 30, "background-color": "#a8afaa", color: "#172629" } },
      { selector: 'node[kind="insight"]', style: { width: 58, height: 58, "background-color": "#cce66d", "border-color": "#2b6658", "border-width": 2, "font-weight": 700 } },
      { selector: 'node[kind="mechanism"]', style: { "background-color": "#2b6658", color: "#17352e" } },
      { selector: 'node[kind="pressure"]', style: { "background-color": "#d1783f" } },
      { selector: 'node[kind="domain"]', style: { "background-color": "#497b9e" } },
      { selector: 'node[kind="transfer"]', style: { "background-color": "#8764a3" } },
      { selector: "edge", style: { width: 1.5, "line-color": "#b5bdb7", "target-arrow-color": "#b5bdb7", "target-arrow-shape": "triangle", "curve-style": "bezier" } },
      { selector: "node:selected", style: { "border-color": "#172629", "border-width": 4 } },
    ],
    layout: { name: "cose", animate: false, padding: 35, nodeRepulsion: 9000, idealEdgeLength: 95 },
    minZoom: 0.2,
    maxZoom: 2.5,
  })
  network.on("tap", 'node[kind="insight"]', function (event) {
    selectedId.value = String(event.target.data("artifact_id"))
  })
}

function ensurePolling() {
  if (pollTimer) return
  pollTimer = setInterval(function () { void load(false) }, 3500)
}

function clearPolling() {
  if (!pollTimer) return
  clearInterval(pollTimer)
  pollTimer = undefined
}

async function start() {
  const calls = maxRounds.value * 3
  if (!window.confirm(`每轮由 Cartographer、Challenger、Curator 各调用一次模型。本次最多 ${calls} 次调用，是否继续？`)) return
  starting.value = true
  error.value = ""
  try {
    const result = await startAtlasSynthesis({
      conference: "CVPR",
      year: 2026,
      max_rounds: maxRounds.value,
      artifacts_per_round: artifactsPerRound.value,
      max_input_chars: maxInputChars.value,
    })
    message.value = result.message
    await load(false)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "方法综合启动失败"
  } finally {
    starting.value = false
  }
}

async function stop() {
  const runId = overview.value?.latest_run?.id
  if (!runId) return
  stopping.value = true
  try {
    const result = await stopAtlasSynthesis(runId)
    message.value = result.message
    await load(false)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "停止请求失败"
  } finally {
    stopping.value = false
  }
}

async function changeStatus(item: MethodInsight, status: string) {
  try {
    await updateMethodInsightStatus(item.id, status)
    message.value = status === "PUBLISHED" ? "已发布为稳定认知制品" : "已归档该认知制品"
    await load(false)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "状态更新失败"
  }
}

watch([query, domain], function () {
  if (!filteredInsights.value.some((item) => item.id === selectedId.value)) {
    selectedId.value = filteredInsights.value[0]?.id ?? ""
  }
})

onMounted(load)
onBeforeUnmount(function () {
  network?.destroy()
  clearPolling()
})
</script>

<template>
  <section class="page atlas-page">
    <div class="hero-row">
      <div>
        <p class="page-kicker">METHOD COGNITION ATLAS</p>
        <h2>方法认知图谱</h2>
        <p class="lede">把跨论文、跨批次浮现的方法思想组织成可反驳、可追溯、可继续迁移探索的认知制品，而不是静态论文分类。</p>
      </div>
      <button class="quiet-button" type="button" :disabled="loading" @click="load()"><PhArrowClockwise /> 刷新图谱</button>
    </div>

    <div v-if="message" class="notice">{{ message }}</div>
    <div v-if="error" class="notice notice--error">{{ error }}</div>
    <div v-if="loading" class="notice">正在装载方法认知空间…</div>

    <template v-else-if="overview">
      <div class="metric-grid atlas-metrics">
        <article class="metric"><PhGitBranch /><span>批次观察</span><strong>{{ overview.discovery_artifacts }}</strong><small>剩余 {{ overview.remaining_discovery_artifacts }} 个待综合</small></article>
        <article class="metric"><PhBrain /><span>方法认知</span><strong>{{ overview.insights }}</strong><small>{{ overview.challenged }} 个已完成独立反驳</small></article>
        <article class="metric"><PhCheckCircle /><span>人工发布</span><strong>{{ overview.published }}</strong><small>明确确认后的稳定制品</small></article>
        <article class="metric metric--accent"><PhGitBranch /><span>浮现坐标</span><strong>{{ overview.mechanisms + overview.domains }}</strong><small>{{ overview.mechanisms }} 个机制 · {{ overview.domains }} 个领域</small></article>
      </div>

      <article class="panel atlas-runner">
        <div class="panel__heading"><div><p class="page-kicker">MULTI-AGENT REVIEW LOOP</p><h3>跨批次综合、反驳与修订</h3></div><span>每轮固定 3 次模型调用</span></div>
        <p class="panel-intro">Cartographer 提出跨批次方法现象，独立 Challenger 尽力推翻，Curator 只保留修订后仍成立的认知。多 Agent 只用在确有独立反驳价值的环节。</p>
        <div class="atlas-run-controls">
          <label>最多轮数<input v-model.number="maxRounds" type="number" min="1" max="50" /><small>1 轮默认最多消费 8 个观察批次。</small></label>
          <label>每轮观察批次<input v-model.number="artifactsPerRound" type="number" min="3" max="30" /><small>扩大可发现跨批次重复或冲突。</small></label>
          <label>输入字符上限<input v-model.number="maxInputChars" type="number" min="30000" max="300000" step="10000" /><small>默认 100,000，控制上下文成本。</small></label>
          <div class="discovery-action">
            <button v-if="!active" class="primary-button" :disabled="starting || !overview.model_ready || !overview.remaining_discovery_artifacts" @click="start"><PhPlay /> {{ starting ? "正在启动" : `启动 ${maxRounds * 3} 次调用上限` }}</button>
            <button v-else class="danger-button" :disabled="stopping" @click="stop"><PhStopCircle /> {{ stopping ? "正在请求" : "本轮结束后停止" }}</button>
            <span v-if="overview.latest_run">{{ overview.latest_run.status }} · {{ overview.latest_run.counters.model_calls ?? 0 }} 次调用 · {{ overview.latest_run.counters.total_tokens ?? 0 }} tokens</span>
          </div>
        </div>
        <div v-if="!overview.discovery_artifacts" class="cognition-warning"><PhWarningCircle /><span>还没有批次观察。先到“认知运行”执行自主发现，随后这里才能跨批次综合。</span></div>
        <div v-if="overview.events.length" class="discovery-trace"><div v-for="event in overview.events" :key="event.id"><i></i><span><strong>{{ event.message }}</strong><small>{{ event.event_type }} · {{ new Date(event.created_at).toLocaleString() }}</small></span></div></div>
      </article>

      <div class="atlas-toolbar panel">
        <input v-model="query" placeholder="搜索主张、机制或问题压力" />
        <select v-model="domain"><option value="">全部浮现领域</option><option v-for="item in domains" :key="item" :value="item">{{ item }}</option></select>
        <span>{{ filteredInsights.length }} / {{ insights.length }} 个认知制品</span>
      </div>

      <div class="atlas-workspace">
        <article class="panel atlas-graph-panel">
          <div class="panel__heading"><div><p class="page-kicker">EMERGENT COORDINATES</p><h3>问题压力 × 方法机制 × 领域 × 迁移方向</h3></div><span>{{ graph?.nodes.length ?? 0 }} 个节点</span></div>
          <div v-if="!graph?.nodes.length" class="artifact-empty"><PhGitBranch :size="30" /><strong>等待第一批方法认知制品</strong><span>这里不会使用固定分类轴；节点与坐标均来自 AI 经反驳后保留的认知内容。</span></div>
          <div ref="graphElement" class="atlas-canvas" :class="{ 'atlas-canvas--empty': !graph?.nodes.length }"></div>
        </article>

        <aside class="panel atlas-detail">
          <div class="panel__heading"><div><p class="page-kicker">COGNITION ARTIFACT</p><h3>{{ selected?.title ?? "选择一个认知节点" }}</h3></div><span v-if="selected">{{ Math.round(selected.confidence * 100) }}%</span></div>
          <template v-if="selected">
            <div class="atlas-status"><span :data-status="selected.status">{{ selected.status }}</span><code>{{ selected.model }}</code></div>
            <p class="atlas-claim">{{ selected.claim }}</p>
            <dl class="atlas-axes">
              <div><dt>问题压力</dt><dd>{{ selected.problem_pressure || "未形成" }}</dd></div>
              <div><dt>方法机制</dt><dd>{{ selected.mechanism || "未形成" }}</dd></div>
              <div><dt>思想来源</dt><dd>{{ selected.borrowed_idea || "证据不足" }}</dd></div>
              <div><dt>关键改造</dt><dd>{{ selected.adaptation || "未形成" }}</dd></div>
              <div><dt>迁移方向</dt><dd>{{ selected.transfer_targets.join("；") || "尚未提出" }}</dd></div>
            </dl>
            <section class="atlas-counter"><strong>最强反方解释</strong><p>{{ selected.counterargument || "Challenger 未留下有效反方解释" }}</p></section>
            <section class="atlas-boundary"><strong>证据边界</strong><p>{{ selected.evidence_boundary || "尚未声明" }}</p></section>
            <details open><summary>来源论文（{{ selected.sources.length }}）</summary><div class="artifact-sources"><RouterLink v-for="source in selected.sources" :key="`${source.paper_id}-${source.stance}`" :to="`/papers/${source.paper_id}`"><span>{{ source.stance }}</span>{{ source.title }}</RouterLink></div></details>
            <div class="atlas-actions"><button class="primary-button" :disabled="selected.status === 'PUBLISHED'" @click="changeStatus(selected, 'PUBLISHED')"><PhCheckCircle /> 发布认知</button><button class="quiet-button" @click="changeStatus(selected, 'ARCHIVED')"><PhArchive /> 归档</button></div>
          </template>
          <div v-else class="empty-state">图谱中尚无可查看的认知制品。</div>
        </aside>
      </div>

      <article v-if="filteredInsights.length" class="panel atlas-list">
        <div class="panel__heading"><div><p class="page-kicker">ARTIFACT LIBRARY</p><h3>认知制品库</h3></div></div>
        <button v-for="item in filteredInsights" :key="item.id" :class="{ 'atlas-card--active': item.id === selected?.id }" @click="selectedId = item.id"><span>{{ item.status }}</span><strong>{{ item.title }}</strong><p>{{ item.claim }}</p><small>{{ item.domains.join(" · ") }}</small></button>
      </article>
    </template>
  </section>
</template>
