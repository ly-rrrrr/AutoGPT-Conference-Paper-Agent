<script setup lang="ts">
import { onMounted, reactive, ref, watch } from "vue"
import { PhArrowLeft, PhArrowRight, PhMagnifyingGlass } from "@phosphor-icons/vue"
import StatusBadge from "../components/StatusBadge.vue"
import { getPapers, type PaginatedPapers, type PaperFilters } from "../api"

const result = ref<PaginatedPapers>({ total: 0, page: 1, page_size: 25, items: [] })
const loading = ref(false)
const error = ref("")
const filters = reactive<PaperFilters>({ query: "", conference: "", mapping_status: "", analysis_status: "", sort: "updated_at", page: 1, page_size: 25 })
let searchTimer: ReturnType<typeof setTimeout> | undefined
async function load() {
  loading.value = true; error.value = ""
  try { result.value = await getPapers({ ...filters }) } catch (reason) { error.value = reason instanceof Error ? reason.message : "加载失败" }
  finally { loading.value = false }
}
function changePage(delta: number) { filters.page = Math.max(1, (filters.page ?? 1) + delta) }
watch(() => [filters.conference, filters.mapping_status, filters.analysis_status, filters.sort, filters.page], load)
watch(() => filters.query, () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { filters.page = 1; load() }, 280) })
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="hero-row"><div><p class="page-kicker">PAPER ASSETS</p><h2>论文目录</h2><p class="lede">按会议、映射与分析状态检索 {{ result.total.toLocaleString() }} 篇论文。</p></div></div>
    <div class="filters">
      <label class="search-field"><PhMagnifyingGlass /><input v-model="filters.query" name="query" placeholder="搜索论文标题" /></label>
      <select v-model="filters.conference" name="conference"><option value="">全部会议</option><option>ECCV</option><option>CVPR</option></select>
      <select v-model="filters.mapping_status" name="mapping_status"><option value="">全部映射</option><option value="matched">已匹配</option><option value="needs_review">待判断</option><option value="not_found">未找到</option><option value="error">错误</option></select>
      <select v-model="filters.analysis_status" name="analysis_status"><option value="">全部分析</option><option value="SUCCESS">已完成</option><option value="FAILED">失败</option></select>
      <select v-model="filters.sort" name="sort"><option value="updated_at">最近更新</option><option value="likes">Likes 排序</option><option value="title">标题排序</option></select>
    </div>
    <div v-if="error" class="notice notice--error">{{ error }} <button @click="load">重试</button></div>
    <div class="paper-table-wrap"><table class="paper-table"><thead><tr><th>论文</th><th>会议</th><th>映射</th><th>分析</th><th>Likes</th></tr></thead><tbody>
      <tr v-if="loading"><td colspan="5">正在加载…</td></tr><tr v-else-if="!result.items.length"><td colspan="5">没有符合条件的论文</td></tr>
      <tr v-for="paper in result.items" :key="paper.id"><td><RouterLink :to="`/papers/${paper.id}`">{{ paper.title }}</RouterLink><small>{{ paper.authors.slice(0, 3).join(" · ") || "作者信息待补" }}</small></td><td><strong>{{ paper.conference }} {{ paper.year }}</strong><small>{{ paper.topic }}</small></td><td><StatusBadge :status="paper.mapping_status" /></td><td><StatusBadge :status="paper.analysis_status" /></td><td class="mono">{{ paper.likes ?? "—" }}</td></tr>
    </tbody></table></div>
    <div class="pagination"><button :disabled="result.page <= 1" @click="changePage(-1)"><PhArrowLeft /> 上一页</button><span>第 {{ result.page }} 页 · 共 {{ Math.ceil(result.total / result.page_size) || 1 }} 页</span><button :disabled="result.page * result.page_size >= result.total" @click="changePage(1)">下一页 <PhArrowRight /></button></div>
  </section>
</template>
