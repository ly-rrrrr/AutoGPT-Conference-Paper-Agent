<script setup lang="ts">
import {
  PhArrowRight,
  PhBrain,
  PhCheckCircle,
  PhFlask,
  PhPlus,
  PhPlay,
  PhPencilSimple,
  PhWarningCircle,
} from "@phosphor-icons/vue"
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue"
import {
  createResearchBrief,
  getResearchBrief,
  getResearchBriefs,
  getResearchRuntime,
  startResearchBrief,
  updateResearchBrief,
  type ResearchBrief,
  type ResearchBriefDetail,
  type ResearchRuntimeStatus,
} from "../api"

const briefs = ref<ResearchBrief[]>([])
const selected = ref<ResearchBriefDetail | null>(null)
const runtime = ref<ResearchRuntimeStatus | null>(null)
const loading = ref(true)
const creating = ref(false)
const starting = ref(false)
const editingId = ref("")
const error = ref("")
const message = ref("")
let pollTimer: ReturnType<typeof setInterval> | undefined
const form = reactive({
  title: "",
  objective: "",
  conference: "CVPR",
  year: 2026,
  researchScale: "conference_landscape",
  focus: "",
  mustAnswer: "",
  boundaries: "",
  outputLanguage: "zh-CN",
  maxModelCalls: 40,
  maxPapers: 24,
})

const evidenceCounts = computed(() => {
  const counts = { SUPPORTS: 0, CHALLENGES: 0, CONTEXT: 0 }
  selected.value?.evidence.forEach((item) => { counts[item.stance] += 1 })
  return counts
})

async function loadBriefs(preferredId = "") {
  const result = await getResearchBriefs()
  briefs.value = result.items
  const selectedId = preferredId || selected.value?.id || briefs.value[0]?.id
  selected.value = selectedId ? await getResearchBrief(selectedId) : null
}

async function chooseBrief(id: string) {
  error.value = ""
  try {
    selected.value = await getResearchBrief(id)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "研究任务加载失败"
  }
}

function editSelected() {
  if (!selected.value) return
  editingId.value = selected.value.id
  form.title = selected.value.title
  form.objective = selected.value.objective
  form.conference = String(selected.value.scope.conference ?? "")
  form.year = Number(selected.value.scope.year ?? 2026)
  form.researchScale = String(selected.value.scope.research_scale ?? "conference_landscape")
  form.focus = String(selected.value.scope.focus ?? "")
  form.mustAnswer = Array.isArray(selected.value.output_preferences.must_answer)
    ? selected.value.output_preferences.must_answer.join("\n")
    : ""
  form.boundaries = String(selected.value.output_preferences.boundaries ?? "")
  form.outputLanguage = String(selected.value.output_preferences.language ?? "zh-CN")
  form.maxModelCalls = Number(selected.value.budget.max_model_calls ?? 40)
  form.maxPapers = Number(selected.value.budget.max_papers ?? 24)
  window.scrollTo({ top: 0, behavior: "smooth" })
}

function resetForm() {
  editingId.value = ""
  form.title = ""
  form.objective = ""
  form.conference = "CVPR"
  form.year = 2026
  form.researchScale = "conference_landscape"
  form.focus = ""
  form.mustAnswer = ""
  form.boundaries = ""
}

async function submitBrief() {
  creating.value = true
  error.value = ""
  message.value = ""
  try {
    const payload = {
      title: form.title.trim(),
      objective: form.objective.trim(),
      scope: {
        conference: form.conference.trim().toUpperCase(),
        year: form.year,
        research_scale: form.researchScale,
        focus: form.focus.trim(),
      },
      tool_policy: {
        evidence_research: "paperqa2-adapter",
        semantic_program: "dspy-adapter",
        allow_counterevidence_search: true,
      },
      budget: { max_model_calls: form.maxModelCalls, max_papers: form.maxPapers },
      output_preferences: {
        language: form.outputLanguage,
        mode: "interactive_atlas",
        must_answer: form.mustAnswer.split("\n").map((item) => item.trim()).filter(Boolean),
        boundaries: form.boundaries.trim(),
      },
    }
    const saved = editingId.value
      ? await updateResearchBrief(editingId.value, payload)
      : await createResearchBrief(payload)
    const wasEditing = Boolean(editingId.value)
    resetForm()
    message.value = wasEditing ? "研究任务已更新，语料覆盖已经重新计算。" : "研究任务草案已保存。"
    await loadBriefs(saved.id)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "研究任务创建失败"
  } finally {
    creating.value = false
  }
}

async function startResearch() {
  if (!selected.value) return
  starting.value = true
  error.value = ""
  message.value = ""
  try {
    const result = await startResearchBrief(selected.value.id)
    message.value = `${result.message}；页面会自动刷新产物。`
    await loadBriefs(selected.value.id)
    clearInterval(pollTimer)
    pollTimer = setInterval(async () => {
      if (!selected.value) return
      await loadBriefs(selected.value.id)
      if (selected.value.status !== "RUNNING") clearInterval(pollTimer)
    }, 3000)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "主动研究启动失败"
  } finally {
    starting.value = false
  }
}

function displayValue(value: unknown) {
  if (typeof value === "string" || typeof value === "number") return String(value)
  return JSON.stringify(value)
}

onMounted(async () => {
  try {
    const [, runtimeStatus] = await Promise.all([loadBriefs(), getResearchRuntime()])
    runtime.value = runtimeStatus
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "研究任务加载失败"
  } finally {
    loading.value = false
  }
})
onBeforeUnmount(() => clearInterval(pollTimer))
</script>

<template>
  <section class="page research-page">
    <div class="hero-row">
      <div>
        <p class="page-kicker">METHOD COGNITION</p>
        <h2>从问题出发，而不是从固定标签出发</h2>
        <p class="lede">把年度趋势、方法迁移或论文深挖写成一个研究目标。系统后续将围绕目标主动提出候选洞察、寻找支持与反证，并发布可追溯的交互认知产物。</p>
      </div>
      <div class="research-runtime">
        <PhCheckCircle v-if="runtime?.ready" :size="22" />
        <PhWarningCircle v-else :size="22" />
        <div><strong>{{ runtime?.ready ? "AI 运行时已就绪" : "AI 运行时待接入" }}</strong><small>任务契约与产物仓库已可用</small></div>
      </div>
    </div>

    <div v-if="message" class="notice">{{ message }}</div>
    <div v-if="error" class="notice notice--error">{{ error }}</div>

    <div class="research-create-grid">
      <article class="panel">
        <div class="panel__heading">
          <div><p class="page-kicker">RESEARCH BRIEF</p><h3>{{ editingId ? "编辑研究任务" : "创建研究任务" }}</h3></div>
          <PhPlus :size="21" />
        </div>
        <form class="research-form" @submit.prevent="submitBrief">
          <label><span>任务名称</span><input v-model="form.title" required maxlength="300" placeholder="例如：CVPR 2025 方法思想迁移地图" /></label>
          <label><span>真正想回答的问题</span><textarea v-model="form.objective" required maxlength="10000" rows="5" placeholder="描述希望系统主动发现、比较和解释什么；不要预先规定结论。" /></label>
          <div class="form-pair">
            <label><span>会议</span><input v-model="form.conference" required maxlength="40" /></label>
            <label><span>年份</span><input v-model.number="form.year" required type="number" min="1900" max="2100" /></label>
          </div>
          <div class="form-pair">
            <label><span>研究尺度</span><select v-model="form.researchScale"><option value="conference_landscape">会议年度全景</option><option value="method_family">方法家族比较</option><option value="paper_deep_dive">论文深挖</option><option value="open_discovery">开放问题探索</option></select></label>
            <label><span>领域 / 方法焦点</span><input v-model="form.focus" maxlength="500" placeholder="例如：多模态学习、长尾与噪声鲁棒性" /></label>
          </div>
          <label><span>必须回答的问题（每行一个）</span><textarea v-model="form.mustAnswer" maxlength="5000" rows="4" placeholder="哪些困难被多数方法回避？&#10;泛化性与效率如何权衡？" /></label>
          <label><span>研究边界与排除项</span><textarea v-model="form.boundaries" maxlength="3000" rows="3" placeholder="例如：只基于已有论文材料；证据不足时明确无法回答。" /></label>
          <div class="form-pair">
            <label><span>输出语言</span><select v-model="form.outputLanguage"><option value="zh-CN">中文</option><option value="en">English</option></select></label>
            <label><span>模型调用预算</span><input v-model.number="form.maxModelCalls" type="number" min="1" max="40" /></label>
          </div>
          <div class="form-pair">
            <label><span>最多深读论文数</span><input v-model.number="form.maxPapers" type="number" min="1" max="200" /></label>
          </div>
          <div class="form-actions"><button class="primary-button" type="submit" :disabled="creating"><PhPlus /> {{ creating ? "正在保存" : editingId ? "更新任务草案" : "保存任务草案" }}</button><button v-if="editingId" class="quiet-button" type="button" @click="resetForm">取消编辑</button></div>
        </form>
      </article>

      <article class="panel research-contract">
        <div class="panel__heading"><div><p class="page-kicker">ACTIVE RESEARCH LOOP</p><h3>实际执行链路</h3></div><PhBrain :size="21" /></div>
        <ol>
          <li><strong>理解目标</strong><span>确定问题、范围、已有材料与未知部分。</span></li>
          <li><strong>提出候选认识</strong><span>由模型主动提出值得调查的现象，而非套用预置类别。</span></li>
          <li><strong>调用研究工具</strong><span>按需阅读论文、搜索相邻工作、寻找支持与反证。</span></li>
          <li><strong>修订与表达</strong><span>保留不确定性、反方证据和来源，形成可交互产物。</span></li>
        </ol>
        <p class="runtime-note"><PhFlask /> 当前由 OpenAI-compatible 主动研究适配器选择目录检索与结构化分析工具；PaperQA2 全文证据和 DSPy 可优化语义程序仍是待接入能力。</p>
        <div v-if="runtime" class="runtime-components">
          <div v-for="component in runtime.components" :key="component.id">
            <span :data-status="component.status"></span>
            <p><strong>{{ component.name }}</strong><small>{{ component.detail }}</small></p>
            <code>{{ component.status }}</code>
          </div>
        </div>
      </article>
    </div>

    <div class="research-browser">
      <aside class="panel brief-list">
        <div class="panel__heading"><div><p class="page-kicker">SAVED BRIEFS</p><h3>研究任务</h3></div><span>{{ briefs.length }}</span></div>
        <p v-if="loading" class="empty-state">正在加载…</p>
        <p v-else-if="!briefs.length" class="empty-state">还没有任务。先把一个真实研究问题保存下来。</p>
        <button v-for="brief in briefs" :key="brief.id" class="brief-card" :class="{ 'brief-card--active': selected?.id === brief.id }" @click="chooseBrief(brief.id)">
          <span>{{ brief.status }}</span><strong>{{ brief.title }}</strong><small>{{ brief.objective }}</small><PhArrowRight :size="16" />
        </button>
      </aside>

      <article class="panel brief-detail">
        <template v-if="selected">
          <div class="panel__heading"><div><p class="page-kicker">RESEARCH ARTIFACTS</p><h3>{{ selected.title }}</h3></div><span>{{ selected.status }}</span></div>
          <p class="brief-objective">{{ selected.objective }}</p>
          <dl class="brief-meta">
            <div v-for="(value, key) in selected.scope" :key="key"><dt>{{ key }}</dt><dd>{{ displayValue(value) }}</dd></div>
          </dl>
          <div class="coverage-strip" :data-status="selected.coverage.status">
            <strong>{{ selected.coverage.status }} · 范围内 {{ selected.coverage.paper_count }} 篇论文</strong>
            <span>{{ selected.coverage.analysis_count }} 篇有结构化分析，{{ selected.coverage.document_count }} 篇有本地文档。系统只基于实际可用材料形成认识。</span>
            <ul v-if="selected.coverage.blockers.length || selected.coverage.warnings.length">
              <li v-for="item in [...selected.coverage.blockers, ...selected.coverage.warnings]" :key="item">{{ item }}</li>
            </ul>
          </div>
          <div class="artifact-metrics">
            <div><strong>{{ selected.artifacts.length }}</strong><span>版本化认知产物</span></div>
            <div><strong>{{ selected.insights.length }}</strong><span>候选洞察</span></div>
            <div><strong>{{ evidenceCounts.SUPPORTS }}</strong><span>支持证据</span></div>
            <div><strong>{{ evidenceCounts.CHALLENGES }}</strong><span>反方证据</span></div>
          </div>
          <div class="research-actions">
            <button class="primary-button" type="button" :disabled="starting || selected.status === 'RUNNING' || !runtime?.ready || selected.coverage.status === 'BLOCKED'" @click="startResearch"><PhPlay weight="fill" /> {{ selected.status === "RUNNING" ? "研究进行中" : starting ? "正在启动" : "启动主动研究" }}</button>
            <button class="quiet-button" type="button" :disabled="selected.status === 'RUNNING'" @click="editSelected"><PhPencilSimple /> 编辑任务</button>
            <span v-if="!runtime?.ready">请先到“系统设置 → 模型配置”保存默认模型密钥。</span>
            <span v-else>将调用默认模型，并按任务预算自主读取本地论文材料。</span>
          </div>
          <div v-if="selected.runs.length" class="research-run-state"><strong>最近运行：{{ selected.runs[0].status }}</strong><code>{{ JSON.stringify(selected.runs[0].counters) }}</code></div>
          <section v-if="selected.events.length" class="research-timeline">
            <div class="panel__heading"><div><p class="page-kicker">TRACE</p><h4>研究轨迹</h4></div><span>{{ selected.events.length }}</span></div>
            <ol>
              <li v-for="event in selected.events" :key="event.id"><i></i><div><strong>{{ event.message }}</strong><small>{{ event.event_type }} · {{ new Date(event.created_at).toLocaleString() }}</small></div></li>
            </ol>
          </section>
          <section v-if="selected.insights.length" class="insight-list">
            <article v-for="insight in selected.insights" :key="insight.id">
              <div><span>{{ insight.epistemic_status }}</span><span>{{ insight.status }}</span></div>
              <h4>{{ insight.title }}</h4>
              <p>{{ insight.statement }}</p>
              <strong>为什么重要</strong><p>{{ insight.why_it_matters }}</p>
              <details v-if="insight.counterarguments.length || insight.open_questions.length"><summary>反方观点与开放问题</summary><pre>{{ JSON.stringify({ counterarguments: insight.counterarguments, open_questions: insight.open_questions }, null, 2) }}</pre></details>
            </article>
          </section>
          <div v-else class="artifact-empty"><PhCheckCircle :size="28" /><strong>任务目标已被可靠保存</strong><span>配置默认模型后点击“启动主动研究”，这里将呈现带证据、反证、版本和不确定性的候选洞察。</span></div>
        </template>
        <div v-else class="empty-state">选择一个研究任务查看产物。</div>
      </article>
    </div>
  </section>
</template>
