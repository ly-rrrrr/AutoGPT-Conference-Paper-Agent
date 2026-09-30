<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { PhArrowRight, PhBooks, PhBrain, PhFlowArrow, PhHeart } from "@phosphor-icons/vue"
import { getDashboard, type Dashboard } from "../api"

const data = ref<Dashboard | null>(null)
const error = ref("")
const loading = ref(true)
const mapped = computed(() => data.value?.mappings.matched ?? 0)
const analyzed = computed(() => data.value?.analyses.SUCCESS ?? 0)
async function load() {
  loading.value = true; error.value = ""
  try { data.value = await getDashboard() } catch (reason) { error.value = reason instanceof Error ? reason.message : "加载失败" }
  finally { loading.value = false }
}
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="hero-row"><div><p class="page-kicker">ACADEMIC RADAR</p><h2>把论文材料，变成<br><em>可追踪的研究资产。</em></h2><p class="lede">这里展示历史累计资产；任务页面会单独呈现每次运行的新增变化。</p></div><RouterLink class="text-link" to="/papers">探索论文 <PhArrowRight /></RouterLink></div>
    <div v-if="loading" class="notice">正在读取本地研究资产…</div>
    <div v-else-if="error" class="notice notice--error">{{ error }} <button @click="load">重试</button></div>
    <template v-else-if="data">
      <div class="metric-grid">
        <article class="metric"><PhBooks /><span>论文资产</span><strong>{{ data.papers_total.toLocaleString() }}</strong><small>{{ Object.keys(data.conferences).length }} 个会议批次</small></article>
        <article class="metric"><PhFlowArrow /><span>可靠映射</span><strong>{{ mapped.toLocaleString() }}</strong><small>{{ data.mappings.needs_review ?? 0 }} 篇待判断</small></article>
        <article class="metric"><PhBrain /><span>完成分析</span><strong>{{ analyzed.toLocaleString() }}</strong><small>{{ data.analyses.FAILED ?? 0 }} 篇失败</small></article>
        <article class="metric metric--accent"><PhHeart /><span>影响力信号</span><strong>{{ data.likes_success.toLocaleString() }}</strong><small>alphaXiv Likes 已采集</small></article>
      </div>
      <div class="dashboard-grid">
        <article class="panel"><div class="panel__heading"><div><p class="page-kicker">ASSET FLOW</p><h3>论文处理漏斗</h3></div><span>历史累计</span></div><div class="funnel"><div><span>官网目录</span><strong>{{ data.papers_total }}</strong></div><i></i><div><span>arXiv 匹配</span><strong>{{ mapped }}</strong></div><i></i><div><span>结构化分析</span><strong>{{ analyzed }}</strong></div></div></article>
        <article class="panel"><div class="panel__heading"><div><p class="page-kicker">CONFERENCES</p><h3>数据版图</h3></div></div><div class="rank-list"><div v-for="(count, name) in data.conferences" :key="name"><span>{{ name }}</span><strong>{{ count }}</strong></div></div></article>
      </div>
      <div class="footer-note">最近同步：{{ data.last_import_at ? new Date(data.last_import_at).toLocaleString() : "尚未同步" }} · 活跃任务 {{ data.active_runs.length }} 个</div>
    </template>
  </section>
</template>
