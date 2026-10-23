<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { getStorageOverview, updateStorage, type StorageOverview } from "../api"

const storage = ref<StorageOverview | null>(null)
const assetRoot = ref("")
const saving = ref(false)
const error = ref("")
const message = ref("")

function formatBytes(value: number) {
  if (!value) return "0 GB"
  return `${(value / 1024 ** 3).toFixed(1)} GB`
}

const freePercent = computed(function () {
  if (!storage.value?.total_bytes) return 0
  return Math.max(0, Math.min(100, storage.value.free_bytes / storage.value.total_bytes * 100))
})

async function load() {
  try {
    storage.value = await getStorageOverview()
    assetRoot.value = storage.value.asset_root
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "读取存储配置失败"
  }
}

async function save() {
  if (!assetRoot.value.trim()) return
  saving.value = true
  error.value = ""
  message.value = ""
  try {
    storage.value = await updateStorage(assetRoot.value.trim())
    assetRoot.value = storage.value.asset_root
    message.value = storage.value.message ?? "存储目录已更新"
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "保存失败"
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="page">
    <div class="hero-row">
      <div>
        <p class="page-kicker">STORAGE CONTROL</p>
        <h2>存储配置</h2>
        <p class="lede">控制后续 PDF、GROBID TEI、框架图等大文件写到哪里。数据库与 Milvus 仍由 Docker 管理，不会在这里自动迁移。</p>
      </div>
      <button class="quiet-button" type="button" @click="load">刷新容量</button>
    </div>

    <div v-if="message" class="notice">{{ message }}</div>
    <div v-if="error" class="notice notice--error">{{ error }}</div>

    <div v-if="storage" class="metric-grid metric-grid--compact">
      <article class="metric"><span>磁盘总量</span><strong>{{ formatBytes(storage.total_bytes) }}</strong><small>当前目录所在分区</small></article>
      <article class="metric" :class="{ 'metric--warning': storage.capacity_status === 'LOW' }"><span>可用空间</span><strong>{{ formatBytes(storage.free_bytes) }}</strong><small>{{ storage.capacity_status === "READY" ? "可开始全量建设" : "低于建议的 100 GB" }}</small></article>
      <article class="metric"><span>已登记资产</span><strong>{{ storage.registered_assets }}</strong><small>{{ formatBytes(storage.registered_asset_bytes) }}</small></article>
      <article class="metric"><span>剩余比例</span><strong>{{ freePercent.toFixed(0) }}%</strong><small>建议预留 {{ formatBytes(storage.recommended_free_bytes) }}</small></article>
    </div>

    <article class="panel storage-form">
      <div class="panel__heading">
        <div><span class="eyebrow">ASSET ROOT</span><h3>论文资产根目录</h3></div>
        <span>{{ storage?.source === "saved" ? "网页配置" : "环境变量 / 默认值" }}</span>
      </div>
      <label>
        绝对路径
        <input v-model="assetRoot" type="text" placeholder="E:\ResearchAtlas" spellcheck="false" />
      </label>
      <p class="muted">保存时只创建目录并验证可写性，不会移动或删除已有文件。以后新下载的论文写入 <code>papers/&lt;paper-id&gt;/</code>。</p>
      <button class="primary-button" type="button" :disabled="saving" @click="save">{{ saving ? "正在保存" : "更新存储目录" }}</button>
      <p v-if="storage" class="footer-note mono">配置文件：{{ storage.config_path }}</p>
    </article>
  </section>
</template>
