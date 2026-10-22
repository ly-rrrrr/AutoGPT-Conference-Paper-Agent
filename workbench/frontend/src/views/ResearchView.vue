<script setup lang="ts">
import {
  PhArrowRight,
  PhBrain,
  PhCheckCircle,
  PhFlask,
  PhPlus,
  PhWarningCircle,
} from "@phosphor-icons/vue"
import { computed, onMounted, reactive, ref } from "vue"
import {
  createResearchBrief,
  getResearchBrief,
  getResearchBriefs,
  getResearchRuntime,
  type ResearchBrief,
  type ResearchBriefDetail,
  type ResearchRuntimeStatus,
} from "../api"

const briefs = ref<ResearchBrief[]>([])
const selected = ref<ResearchBriefDetail | null>(null)
const runtime = ref<ResearchRuntimeStatus | null>(null)
const loading = ref(true)
const creating = ref(false)
const error = ref("")
const message = ref("")
const form = reactive({
  title: "",
  objective: "",
  conference: "CVPR",
  year: 2025,
  outputLanguage: "zh-CN",
  maxModelCalls: 40,
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

async function createBrief() {
  creating.value = true
  error.value = ""
  message.value = ""
  try {
    const created = await createResearchBrief({
      title: form.title.trim(),
      objective: form.objective.trim(),
      scope: { conference: form.conference.trim().toUpperCase(), year: form.year },
      tool_policy: {
        evidence_research: "paperqa2-adapter",
        semantic_program: "dspy-adapter",
        allow_counterevidence_search: true,
      },
      budget: { max_model_calls: form.maxModelCalls },
      output_preferences: { language: form.outputLanguage, mode: "interactive_atlas" },
    })
    form.title = ""
    form.objective = ""
    message.value = "研究任务草案已保存。AI 研究运行时接入后，这份目标将直接成为执行输入。"
    await loadBriefs(created.id)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "研究任务创建失败"
  } finally {
    creating.value = false
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
          <div><p class="page-kicker">RESEARCH BRIEF</p><h3>创建研究任务</h3></div>
          <PhPlus :size="21" />
        </div>
        <form class="research-form" @submit.prevent="createBrief">
          <label><span>任务名称</span><input v-model="form.title" required maxlength="300" placeholder="例如：CVPR 2025 方法思想迁移地图" /></label>
          <label><span>真正想回答的问题</span><textarea v-model="form.objective" required maxlength="10000" rows="6" placeholder="不要写固定分类规则；描述你希望系统主动发现、比较和解释什么。" /></label>
          <div class="form-pair">
            <label><span>会议</span><input v-model="form.conference" required maxlength="40" /></label>
            <label><span>年份</span><input v-model.number="form.year" required type="number" min="1900" max="2100" /></label>
          </div>
          <div class="form-pair">
            <label><span>输出语言</span><select v-model="form.outputLanguage"><option value="zh-CN">中文</option><option value="en">English</option></select></label>
            <label><span>模型调用预算</span><input v-model.number="form.maxModelCalls" type="number" min="1" max="10000" /></label>
          </div>
          <button class="primary-button" type="submit" :disabled="creating"><PhPlus /> {{ creating ? "正在保存" : "保存任务草案" }}</button>
        </form>
      </article>

      <article class="panel research-contract">
        <div class="panel__heading"><div><p class="page-kicker">ACTIVE RESEARCH LOOP</p><h3>未来执行语义</h3></div><PhBrain :size="21" /></div>
        <ol>
          <li><strong>理解目标</strong><span>确定问题、范围、已有材料与未知部分。</span></li>
          <li><strong>提出候选认识</strong><span>由模型主动提出值得调查的现象，而非套用预置类别。</span></li>
          <li><strong>调用研究工具</strong><span>按需阅读论文、搜索相邻工作、寻找支持与反证。</span></li>
          <li><strong>修订与表达</strong><span>保留不确定性、反方证据和来源，形成可交互产物。</span></li>
        </ol>
        <p class="runtime-note"><PhFlask /> PaperQA2 负责证据研究，DSPy 负责可优化的语义程序；AutoGPT 保留外层任务调度。</p>
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
          <div class="artifact-metrics">
            <div><strong>{{ selected.artifacts.length }}</strong><span>版本化认知产物</span></div>
            <div><strong>{{ selected.insights.length }}</strong><span>候选洞察</span></div>
            <div><strong>{{ evidenceCounts.SUPPORTS }}</strong><span>支持证据</span></div>
            <div><strong>{{ evidenceCounts.CHALLENGES }}</strong><span>反方证据</span></div>
          </div>
          <section v-if="selected.insights.length" class="insight-list">
            <article v-for="insight in selected.insights" :key="insight.id">
              <div><span>{{ insight.epistemic_status }}</span><span>{{ insight.status }}</span></div>
              <h4>{{ insight.title }}</h4>
              <p>{{ insight.statement }}</p>
              <strong>为什么重要</strong><p>{{ insight.why_it_matters }}</p>
              <details v-if="insight.counterarguments.length || insight.open_questions.length"><summary>反方观点与开放问题</summary><pre>{{ JSON.stringify({ counterarguments: insight.counterarguments, open_questions: insight.open_questions }, null, 2) }}</pre></details>
            </article>
          </section>
          <div v-else class="artifact-empty"><PhCheckCircle :size="28" /><strong>任务目标已被可靠保存</strong><span>当前尚无 AI 产物。接入研究运行时后，这里将呈现带证据、反证、版本和不确定性的主动洞察。</span></div>
        </template>
        <div v-else class="empty-state">选择一个研究任务查看产物。</div>
      </article>
    </div>
  </section>
</template>
