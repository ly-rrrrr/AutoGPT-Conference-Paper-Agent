<script setup lang="ts">
import { onMounted, ref } from "vue"
import { PhArrowClockwise, PhPlay, PhStop } from "@phosphor-icons/vue"
import StatusBadge from "../components/StatusBadge.vue"
import { getDashboard, getPipelineStatus, startMapping, stopMapping, type Dashboard, type PipelineStatus } from "../api"

const state = ref<PipelineStatus | null>(null)
const dashboard = ref<Dashboard | null>(null)
const retryUnresolved = ref(false)
const busy = ref(false)
const message = ref("")
const error = ref("")
async function refresh() {
  error.value = ""
  try { [state.value, dashboard.value] = await Promise.all([getPipelineStatus(), getDashboard()]) }
  catch (reason) { error.value = reason instanceof Error ? reason.message : "状态读取失败" }
}
async function start() {
  if (!confirm("映射会访问 ECCV 与 arXiv，但不会调用付费模型。是否继续？")) return
  busy.value = true
  try { const result = await startMapping(retryUnresolved.value); message.value = result.message; await refresh() }
  catch (reason) { error.value = reason instanceof Error ? reason.message : "启动失败" }
  finally { busy.value = false }
}
async function stop() { busy.value = true; try { message.value = (await stopMapping()).message; await refresh() } catch (reason) { error.value = reason instanceof Error ? reason.message : "停止失败" } finally { busy.value = false } }
onMounted(refresh)
</script>
<template>
  <section class="page">
    <div class="hero-row"><div><p class="page-kicker">DATA PIPELINE</p><h2>arXiv 映射</h2><p class="lede">以官网标题与作者为证据，保守映射 arXiv 记录；不确定的结果不会伪装成成功。</p></div><StatusBadge :status="state?.mapping.status || 'IDLE'" /></div>
    <div v-if="message" class="notice">{{ message }}</div><div v-if="error" class="notice notice--error">{{ error }}</div>
    <div class="metric-grid metric-grid--compact"><article class="metric"><span>已匹配</span><strong>{{ dashboard?.mappings.matched ?? '—' }}</strong><small>可进入分析</small></article><article class="metric"><span>待判断</span><strong>{{ dashboard?.mappings.needs_review ?? '—' }}</strong><small>证据不足</small></article><article class="metric"><span>未找到</span><strong>{{ dashboard?.mappings.not_found ?? '—' }}</strong><small>当前检索无候选</small></article><article class="metric"><span>错误</span><strong>{{ dashboard?.mappings.error ?? '—' }}</strong><small>网络或服务错误</small></article></div>
    <article class="panel mapping-control"><div><p class="page-kicker">CONTROL</p><h3>批量映射控制</h3><p class="muted">断点会持续保存；停止后可从原位置继续。</p><label class="check-row"><input v-model="retryUnresolved" type="checkbox" /> 同时重试未找到与待判断记录</label></div><div class="button-stack"><button class="primary-button" :disabled="busy" @click="start"><PhPlay weight="fill" /> 启动 / 继续映射</button><button class="danger-button" :disabled="busy" @click="stop"><PhStop weight="fill" /> 停止</button><button class="quiet-button" @click="refresh"><PhArrowClockwise /> 刷新状态</button></div></article>
  </section>
</template>
