<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"
import {
  PhArrowClockwise,
  PhBrain,
  PhCheckCircle,
  PhDatabase,
  PhFlowArrow,
  PhGitBranch,
  PhPlay,
  PhStopCircle,
  PhWarningCircle,
} from "@phosphor-icons/vue"
import {
  getCognitionOverview,
  prepareCognitionHarness,
  startCognitionDiscovery,
  stopCognitionDiscovery,
  type CognitionOverview,
} from "../api"

const data = ref<CognitionOverview | null>(null)
const loading = ref(true)
const preparing = ref(false)
const startingDiscovery = ref(false)
const stoppingDiscovery = ref(false)
const error = ref("")
const message = ref("")
const maxModelCalls = ref(1)
const papersPerBatch = ref(12)
const maxInputChars = ref(60000)
let pollTimer: ReturnType<typeof setInterval> | undefined

const discoveryActive = computed(function () {
  return ["RUNNING", "STOP_REQUESTED"].includes(data.value?.discovery_run?.status ?? "")
})

const estimatedPapers = computed(function () {
  return maxModelCalls.value * papersPerBatch.value
})

const discoveryStage = computed(function () {
  return data.value?.stages.find((stage) => stage.id === "corpus_discovery")
})

async function load(showLoading = true) {
  if (showLoading) loading.value = true
  error.value = ""
  try {
    data.value = await getCognitionOverview("CVPR", 2026)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "认知运行状态加载失败"
  } finally {
    if (showLoading) loading.value = false
  }
  if (discoveryActive.value) ensurePolling()
  else clearPolling()
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

function ensurePolling() {
  if (pollTimer) return
  pollTimer = setInterval(function () {
    void load(false)
  }, 3000)
}

function clearPolling() {
  if (!pollTimer) return
  clearInterval(pollTimer)
  pollTimer = undefined
}

async function startDiscovery() {
  const confirmed = window.confirm(
    `这会真实调用默认模型，最多 ${maxModelCalls.value} 次，预计覆盖不超过 ${estimatedPapers.value} 篇论文。是否继续？`,
  )
  if (!confirmed) return
  startingDiscovery.value = true
  error.value = ""
  message.value = ""
  try {
    const result = await startCognitionDiscovery({
      conference: "CVPR",
      year: 2026,
      max_model_calls: maxModelCalls.value,
      papers_per_batch: papersPerBatch.value,
      max_input_chars: maxInputChars.value,
    })
    message.value = result.message
    await load(false)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "发现试运行启动失败"
  } finally {
    startingDiscovery.value = false
  }
}

async function stopDiscovery() {
  const runId = data.value?.discovery_run?.id
  if (!runId) return
  stoppingDiscovery.value = true
  error.value = ""
  try {
    const result = await stopCognitionDiscovery(runId)
    message.value = result.message
    await load(false)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "停止请求失败"
  } finally {
    stoppingDiscovery.value = false
  }
}

onMounted(load)
onUnmounted(clearPolling)
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

      <article class="panel cognition-discovery">
        <div class="panel__heading">
          <div><p class="page-kicker">DISCOVERY BATCH</p><h3>启动第一轮自主发现</h3></div>
          <span>{{ discoveryStage?.ready.toLocaleString() ?? 0 }} / {{ discoveryStage?.total.toLocaleString() ?? 0 }} 篇已覆盖</span>
        </div>
        <p class="panel-intro">系统从尚未覆盖的论文记忆中取下一批，让 AI 自主提出“值得扩大调查的现象”，不会要求你先写研究问题，也不会把单批观察冒充年度结论。</p>

        <div class="discovery-control">
          <label>本轮最多调用模型
            <input v-model.number="maxModelCalls" type="number" min="1" max="500" />
            <small>预算硬上限；建议第一次保持 1 次。</small>
          </label>
          <label>每批论文数
            <input v-model.number="papersPerBatch" type="number" min="4" max="30" />
            <small>不是抽样结论，而是全量覆盖的一个分片。</small>
          </label>
          <label>每批输入字符上限
            <input v-model.number="maxInputChars" type="number" min="20000" max="200000" step="5000" />
            <small>控制上下文与 token 消耗，默认 60,000。</small>
          </label>
          <div class="discovery-action">
            <button
              v-if="!discoveryActive"
              class="primary-button"
              type="button"
              :disabled="startingDiscovery || !data.model_ready || !data.coverage.paper_memories || discoveryStage?.ready === discoveryStage?.total"
              @click="startDiscovery"
            >
              <PhPlay /> {{ startingDiscovery ? "正在启动" : `试运行：最多 ${estimatedPapers} 篇` }}
            </button>
            <button v-else class="danger-button" type="button" :disabled="stoppingDiscovery" @click="stopDiscovery">
              <PhStopCircle /> {{ stoppingDiscovery ? "正在请求停止" : "完成当前调用后停止" }}
            </button>
            <span v-if="data.discovery_run">{{ data.discovery_run.status }} · {{ data.discovery_run.counters.model_calls ?? 0 }} 次调用 · {{ data.discovery_run.counters.total_tokens ?? 0 }} tokens</span>
          </div>
        </div>

        <div v-if="!data.model_ready" class="cognition-warning">
          <PhWarningCircle />
          <span>默认模型尚未就绪。先到 <RouterLink to="/settings/models">系统设置 → 模型配置</RouterLink> 保存密钥；工作台不会把密钥写进仓库。</span>
        </div>

        <div v-if="data.discovery_events.length" class="discovery-trace">
          <div v-for="event in data.discovery_events" :key="event.id">
            <i></i><span><strong>{{ event.message }}</strong><small>{{ event.event_type }} · {{ new Date(event.created_at).toLocaleString() }}</small></span>
          </div>
        </div>
      </article>

      <article class="panel cognition-results">
        <div class="panel__heading">
          <div><p class="page-kicker">EMERGENT OBSERVATIONS</p><h3>AI 自主提出的候选观察</h3></div>
          <span>{{ data.artifacts.length }} 个批次产物</span>
        </div>
        <div v-if="!data.artifacts.length" class="artifact-empty">
          <PhBrain :size="28" />
          <strong>尚未运行付费发现批次</strong>
          <span>初始化 Harness 不会生成洞见。保存模型密钥后，用上方默认的一次调用先检查输出质量，再逐步扩大到整届语料。</span>
        </div>
        <div v-else class="discovery-results">
          <section v-for="artifact in data.artifacts" :key="artifact.id" class="discovery-artifact">
            <header><span>{{ artifact.status }}</span><time>{{ new Date(artifact.created_at).toLocaleString() }}</time><code>{{ artifact.model }}</code></header>
            <h4>{{ artifact.content.batch_summary ?? artifact.narrative }}</h4>
            <article v-for="observation in artifact.content.observations ?? []" :key="observation.title">
              <h5>{{ observation.title }}</h5>
              <p>{{ observation.statement }}</p>
              <small v-if="observation.why_investigate">为什么继续追查：{{ observation.why_investigate }}</small>
            </article>
            <details>
              <summary>查看本批次 {{ artifact.sources.length }} 篇来源论文</summary>
              <div class="artifact-sources">
                <RouterLink v-for="source in artifact.sources" :key="source.paper_id" :to="`/papers/${source.paper_id}`">{{ source.title }}</RouterLink>
              </div>
            </details>
          </section>
        </div>
        <RouterLink v-if="data.artifacts.length" class="atlas-entry" to="/atlas">进入方法认知图谱，执行跨批次综合、反驳与发布 →</RouterLink>
      </article>

      <article v-if="data.events.length" class="panel cognition-events">
        <div class="panel__heading"><div><p class="page-kicker">RUN TRACE</p><h3>最近一次控制面记录</h3></div><span>{{ data.events.length }}</span></div>
        <div v-for="event in data.events" :key="event.id"><i></i><p><strong>{{ event.message }}</strong><small>{{ event.event_type }} · {{ new Date(event.created_at).toLocaleString() }}</small></p></div>
      </article>
    </template>
  </section>
</template>
