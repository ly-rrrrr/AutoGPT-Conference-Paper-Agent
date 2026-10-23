<script setup lang="ts">
import { onMounted, ref } from "vue"
import {
  PhArrowClockwise,
  PhBrain,
  PhCheckCircle,
  PhDatabase,
  PhFlowArrow,
  PhGitBranch,
  PhWarningCircle,
} from "@phosphor-icons/vue"
import {
  getCognitionOverview,
  prepareCognitionHarness,
  type CognitionOverview,
} from "../api"

const data = ref<CognitionOverview | null>(null)
const loading = ref(true)
const preparing = ref(false)
const error = ref("")
const message = ref("")

async function load() {
  loading.value = true
  error.value = ""
  try {
    data.value = await getCognitionOverview("CVPR", 2026)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "认知运行状态加载失败"
  } finally {
    loading.value = false
  }
}

async function prepare() {
  preparing.value = true
  error.value = ""
  message.value = ""
  try {
    const result = await prepareCognitionHarness("CVPR", 2026)
    message.value = result.message
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Harness 初始化失败"
  } finally {
    preparing.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="page cognition-page">
    <div class="hero-row">
      <div>
        <p class="page-kicker">CORPUS COGNITION HARNESS</p>
        <h2>让系统持续理解整届 CVPR 2026</h2>
        <p class="lede">不要求你先提出问题。Harness 负责全量覆盖、缓存、调度、证据和反例回路；AI 负责自主发现值得研究的方法现象。</p>
      </div>
      <button class="primary-button" type="button" :disabled="preparing" @click="prepare">
        <PhArrowClockwise /> {{ preparing ? "正在建立快照" : "初始化 / 刷新 Harness" }}
      </button>
    </div>

    <div v-if="message" class="notice">{{ message }}</div>
    <div v-if="error" class="notice notice--error">{{ error }}</div>
    <div v-if="loading" class="notice">正在核对 CVPR 2026 全量材料…</div>

    <template v-else-if="data">
      <div class="corpus-banner">
        <div><span>当前语料</span><strong>{{ data.scope.conference }} {{ data.scope.year }}</strong></div>
        <div><span>Harness</span><strong>{{ data.harness_version }}</strong></div>
        <div><span>材料指纹</span><code>{{ data.material_fingerprint.slice(0, 16) }}</code></div>
        <div><span>控制面状态</span><strong>{{ data.latest_run?.status ?? "未初始化" }}</strong></div>
      </div>

      <div class="metric-grid cognition-metrics">
        <article class="metric"><PhDatabase /><span>论文全集</span><strong>{{ data.coverage.papers.toLocaleString() }}</strong><small>本轮认知的真实分母</small></article>
        <article class="metric"><PhFlowArrow /><span>arXiv 原文</span><strong>{{ data.coverage.arxiv_links.toLocaleString() }}</strong><small>缺少 {{ data.gaps.missing_arxiv }}</small></article>
        <article class="metric"><PhBrain /><span>已有 AI 初读</span><strong>{{ data.coverage.paper_analyses.toLocaleString() }}</strong><small>缺少 {{ data.gaps.missing_analysis }}</small></article>
        <article class="metric metric--accent"><PhCheckCircle /><span>Likes 信号</span><strong>{{ data.coverage.likes.toLocaleString() }}</strong><small>仅作影响力信号，不作为真理排序</small></article>
      </div>

      <div class="cognition-grid">
        <article class="panel">
          <div class="panel__heading"><div><p class="page-kicker">CONTROL STAGES</p><h3>Harness 运行层</h3></div><PhGitBranch :size="22" /></div>
          <p class="panel-intro">这些是工程控制阶段，不是预设的方法分类。语义主题由 AI 在运行中产生、修订或放弃。</p>
          <div class="harness-stages">
            <div v-for="(stage, index) in data.stages" :key="stage.id" class="harness-stage">
              <span>{{ index + 1 }}</span>
              <div><strong>{{ stage.name }}</strong><p>{{ stage.detail }}</p></div>
              <code :data-status="stage.status">{{ stage.status }}</code>
            </div>
          </div>
        </article>

        <article class="panel">
          <div class="panel__heading"><div><p class="page-kicker">AGENT TOPOLOGY</p><h3>不是所有环节都用多 Agent</h3></div><PhBrain :size="22" /></div>
          <div class="agent-roles">
            <div v-for="role in data.roles" :key="role.name"><strong>{{ role.name }}</strong><span>{{ role.mode }}</span><p>{{ role.purpose }}</p></div>
          </div>
        </article>
      </div>

      <article class="panel cognition-cache">
        <div class="panel__heading"><div><p class="page-kicker">TOKEN ECONOMY</p><h3>已有结果只读一次，后续按指纹复用</h3></div><PhCheckCircle :size="22" /></div>
        <div class="cache-explanation">
          <p><strong>{{ data.coverage.paper_memories.toLocaleString() }} 篇</strong><span>现有逐篇 AI 问答已登记为版本化论文记忆，不重新生成。</span></p>
          <p><strong>0 次</strong><span>“初始化 / 刷新 Harness”只建立语料快照和缓存计划，不调用模型。</span></p>
          <p><strong>按变化失效</strong><span>只有论文材料、分析版本或认知程序版本变化时，相关结果才重新计算。</span></p>
        </div>
        <div v-if="data.gaps.missing_local_document" class="cognition-warning"><PhWarningCircle /><span>{{ data.gaps.missing_local_document.toLocaleString() }} 篇尚无本地全文；第一轮可复用问答，但实验与页码级复核仍需后续全文层。</span></div>
      </article>

      <article v-if="data.events.length" class="panel cognition-events">
        <div class="panel__heading"><div><p class="page-kicker">RUN TRACE</p><h3>最近一次控制面记录</h3></div><span>{{ data.events.length }}</span></div>
        <div v-for="event in data.events" :key="event.id"><i></i><p><strong>{{ event.message }}</strong><small>{{ event.event_type }} · {{ new Date(event.created_at).toLocaleString() }}</small></p></div>
      </article>
    </template>
  </section>
</template>
