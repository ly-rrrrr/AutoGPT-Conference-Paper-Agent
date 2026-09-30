<script setup lang="ts">
import { onMounted, reactive, ref } from "vue"
import { PhPlay, PhStop } from "@phosphor-icons/vue"
import StatusBadge from "../components/StatusBadge.vue"
import { getPipelineStatus, startAnalysis, stopAnalysis, type AnalysisConfig, type PipelineStatus } from "../api"

const config = reactive<AnalysisConfig>({ run_id: "eccv-2026-luna-full-01", analysis_concurrency: 1, analysis_request_interval_seconds: 4, max_new_analyses_per_run: 20 })
const status = ref<PipelineStatus | null>(null)
const busy = ref(false)
const message = ref("")
const error = ref("")
async function refresh() {
  try { status.value = await getPipelineStatus() } catch (reason) { error.value = reason instanceof Error ? reason.message : "状态读取失败" }
}
async function submit() {
  if (!confirm(`即将启动最多 ${config.max_new_analyses_per_run} 篇新论文分析，可能产生模型调用费用。是否继续？`)) return
  busy.value = true; error.value = ""
  try { const result = await startAnalysis({ ...config }); message.value = result.message; await refresh() }
  catch (reason) { error.value = reason instanceof Error ? reason.message : "启动失败" }
  finally { busy.value = false }
}
async function stop() {
  busy.value = true
  try { const result = await stopAnalysis(); message.value = result.message; await refresh() }
  catch (reason) { error.value = reason instanceof Error ? reason.message : "停止失败" }
  finally { busy.value = false }
}
onMounted(refresh)
</script>
<template>
  <section class="page">
    <div class="hero-row"><div><p class="page-kicker">AI PIPELINE</p><h2>论文分析</h2><p class="lede">显式启动 AutoGPT 批量分析。进入页面、刷新状态和查看记录均不会触发模型调用。</p></div><StatusBadge :status="status?.analysis_runs[0]?.status || 'IDLE'" /></div>
    <div v-if="message" class="notice">{{ message }}</div><div v-if="error" class="notice notice--error">{{ error }}</div>
    <div class="operations-grid">
      <form class="panel operation-form" @submit.prevent="submit">
        <div class="panel__heading"><div><p class="page-kicker">RUN CONFIGURATION</p><h3>新一轮分析</h3></div><span>只有提交后才启动</span></div>
        <label><span>运行名称</span><input v-model="config.run_id" required pattern="[A-Za-z0-9_-]+" /></label>
        <div class="form-pair"><label><span>并发数</span><input v-model.number="config.analysis_concurrency" type="number" min="1" max="3" /></label><label><span>请求间隔（秒）</span><input v-model.number="config.analysis_request_interval_seconds" type="number" min="0" max="300" /></label></div>
        <label><span>本轮最多新增分析</span><input v-model.number="config.max_new_analyses_per_run" type="number" min="0" max="10000" /><small>设为 0 时只处理已有断点和 Likes，不新增论文分析。</small></label>
        <button class="primary-button" type="submit" :disabled="busy"><PhPlay weight="fill" /> {{ busy ? "处理中…" : "确认并启动分析" }}</button>
      </form>
      <article class="panel"><div class="panel__heading"><div><p class="page-kicker">CURRENT STATE</p><h3>AutoGPT 执行状态</h3></div><button class="quiet-button" @click="refresh">刷新</button></div><div v-if="status?.analysis_runs.length" class="run-stack"><div v-for="run in status.analysis_runs" :key="run.id"><span class="mono">{{ run.id }}</span><StatusBadge :status="run.status" /></div></div><p v-else class="empty-state">当前没有执行记录，或 AutoGPT 服务尚未启动。</p><button class="danger-button" type="button" :disabled="busy" @click="stop"><PhStop weight="fill" /> 停止活动任务</button></article>
    </div>
  </section>
</template>
