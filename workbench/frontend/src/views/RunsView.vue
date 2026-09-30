<script setup lang="ts">
import { onMounted, ref } from "vue"
import StatusBadge from "../components/StatusBadge.vue"
import { getRuns, type PipelineRun } from "../api"

const runs = ref<PipelineRun[]>([])
const error = ref("")
async function load() { try { runs.value = (await getRuns()).items } catch (reason) { error.value = reason instanceof Error ? reason.message : "加载失败" } }
onMounted(load)
</script>
<template>
  <section class="page"><div class="hero-row"><div><p class="page-kicker">OBSERVABILITY</p><h2>运行记录</h2><p class="lede">保存从工作台明确发起的映射与分析任务；不展示密钥或容器完整日志。</p></div><button class="quiet-button" @click="load">刷新</button></div><div v-if="error" class="notice notice--error">{{ error }}</div><div class="paper-table-wrap"><table class="paper-table"><thead><tr><th>运行</th><th>类型</th><th>状态</th><th>参数</th><th>开始时间</th></tr></thead><tbody><tr v-if="!runs.length"><td colspan="5">尚无工作台运行记录</td></tr><tr v-for="run in runs" :key="run.id"><td><strong>{{ run.run_key }}</strong><small class="mono">{{ run.external_id || run.id }}</small></td><td>{{ run.pipeline === 'analysis' ? '论文分析' : 'arXiv 映射' }}</td><td><StatusBadge :status="run.status" /></td><td class="mono config-cell">{{ JSON.stringify(run.config) }}</td><td>{{ run.started_at ? new Date(run.started_at).toLocaleString() : '—' }}</td></tr></tbody></table></div></section>
</template>
