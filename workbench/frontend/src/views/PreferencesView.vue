<script setup lang="ts">
import { onMounted, ref } from "vue"
import { PhPlus, PhTrash } from "@phosphor-icons/vue"
import { addInterest, deleteInterest, getPreferences, updateWeights, type Preferences } from "../api"

const data = ref<Preferences | null>(null)
const value = ref("")
const kind = ref<"interest" | "keyword">("interest")
const message = ref("")
const error = ref("")
async function load() { try { data.value = await getPreferences() } catch (reason) { error.value = reason instanceof Error ? reason.message : "加载失败" } }
async function add() { if (!value.value.trim()) return; try { await addInterest(kind.value, value.value.trim()); value.value = ""; await load() } catch (reason) { error.value = reason instanceof Error ? reason.message : "保存失败" } }
async function remove(id: string) { await deleteInterest(id); await load() }
async function saveWeights() { if (!data.value) return; try { await updateWeights(data.value.weights); message.value = "权重已保存" } catch (reason) { error.value = reason instanceof Error ? reason.message : "保存失败" } }
const labels: Record<string, string> = { recent_work: "近期工作相似度", interest: "研究方向", keyword: "关键词", impact: "影响力", freshness: "新鲜度" }
onMounted(load)
</script>
<template>
  <section class="page"><div class="hero-row"><div><p class="page-kicker">PERSONAL SIGNALS</p><h2>研究偏好</h2><p class="lede">用可解释的信号影响未来排序：每个分数组成都能追溯，而不是黑盒“猜你喜欢”。</p></div></div><div v-if="message" class="notice">{{ message }}</div><div v-if="error" class="notice notice--error">{{ error }}</div>
    <div v-if="data" class="preferences-grid"><article class="panel"><div class="panel__heading"><div><p class="page-kicker">INTEREST GRAPH</p><h3>兴趣与关键词</h3></div></div><form class="inline-form" @submit.prevent="add"><select v-model="kind"><option value="interest">研究方向</option><option value="keyword">关键词</option></select><input v-model="value" placeholder="例如：3D reconstruction" /><button class="primary-button" type="submit"><PhPlus /> 添加</button></form><div class="chip-group"><div v-for="item in [...data.interests, ...data.keywords]" :key="item.id" class="interest-chip"><small>{{ item.kind === 'interest' ? '方向' : '关键词' }}</small><span>{{ item.value }}</span><button aria-label="删除" @click="remove(item.id)"><PhTrash /></button></div><p v-if="!data.interests.length && !data.keywords.length" class="muted">尚未添加个性化信号。</p></div></article>
      <article class="panel"><div class="panel__heading"><div><p class="page-kicker">EXPLAINABLE WEIGHTS</p><h3>评分坐标</h3></div></div><label v-for="(weight, name) in data.weights" :key="name" class="weight-row"><span>{{ labels[String(name)] }}</span><input v-model.number="data.weights[name]" type="range" min="0" max="1" step="0.05" /><strong class="mono">{{ Number(weight).toFixed(2) }}</strong></label><button class="primary-button" @click="saveWeights">保存评分权重</button></article>
    </div>
    <article v-if="data" class="panel recent-panel"><div class="panel__heading"><div><p class="page-kicker">RECENT WORK</p><h3>近期工作锚点</h3></div><span>用于未来相似度排序</span></div><div v-if="data.recent_works.length" class="rank-list"><div v-for="work in data.recent_works" :key="work.id"><span>{{ work.title }}</span><strong>{{ work.arxiv_id || '自定义' }}</strong></div></div><p v-else class="muted">尚未添加近期工作。V1 API 已预留，下一阶段可从论文详情一键加入。</p></article>
  </section>
</template>
