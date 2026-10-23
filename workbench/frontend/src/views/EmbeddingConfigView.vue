<script setup lang="ts">
import { PhCheckCircle, PhKey, PhPlus, PhShieldCheck } from "@phosphor-icons/vue"
import { onMounted, reactive, ref } from "vue"
import {
  createEmbeddingConfig,
  getEmbeddingConfigs,
  updateEmbeddingConfig,
  type EmbeddingProviderConfig,
} from "../api"

const configs = ref<EmbeddingProviderConfig[]>([])
const selectedId = ref("")
const saving = ref(false)
const error = ref("")
const message = ref("")
const form = reactive({
  name: "Embedding 模型",
  provider: "OpenAI Compatible",
  base_url: "https://api.openai.com/v1",
  model_name: "",
  dimension: 1536,
  api_key: "",
  is_default: true,
})

function selectConfig(config: EmbeddingProviderConfig) {
  selectedId.value = config.id
  form.name = config.name
  form.provider = config.provider
  form.base_url = config.base_url
  form.model_name = config.model_name
  form.dimension = config.dimension
  form.api_key = ""
  form.is_default = config.is_default
}

function newConfig() {
  selectedId.value = ""
  form.name = "Embedding 模型"
  form.provider = "OpenAI Compatible"
  form.base_url = "https://api.openai.com/v1"
  form.model_name = ""
  form.dimension = 1536
  form.api_key = ""
  form.is_default = false
}

async function loadConfigs(preferredId = "") {
  const result = await getEmbeddingConfigs()
  configs.value = result.items
  const target = configs.value.find((item) => item.id === preferredId)
    ?? configs.value.find((item) => item.is_default)
    ?? configs.value[0]
  if (target) selectConfig(target)
}

async function save() {
  saving.value = true
  error.value = ""
  message.value = ""
  try {
    const payload = {
      name: form.name.trim(),
      provider: form.provider.trim(),
      base_url: form.base_url.trim(),
      model_name: form.model_name.trim(),
      dimension: form.dimension,
      ...(form.api_key ? { api_key: form.api_key } : {}),
      is_default: form.is_default,
    }
    const saved = selectedId.value
      ? await updateEmbeddingConfig(selectedId.value, payload)
      : await createEmbeddingConfig(payload)
    form.api_key = ""
    message.value = "Embedding 配置已更新。返回知识资产页即可启动增量索引。"
    await loadConfigs(saved.id)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Embedding 配置更新失败"
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    await loadConfigs()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Embedding 配置加载失败"
  }
})
</script>

<template>
  <section class="page model-config-page">
    <div class="hero-row">
      <div><p class="page-kicker">VECTOR EMBEDDINGS</p><h2>Embedding 配置</h2><p class="lede">Embedding 与聊天模型是两种不同能力。这里单独配置 OpenAI 兼容的向量接口、模型和维度，避免误用 GPT 对话模型。</p></div>
      <div class="parser-state" :data-ready="configs.some((item) => item.is_default && item.has_api_key)"><span></span><div><strong>默认 Embedding</strong><small>{{ configs.some((item) => item.is_default && item.has_api_key) ? "已配置密钥" : "等待配置" }}</small></div></div>
    </div>
    <div v-if="message" class="notice">{{ message }}</div>
    <div v-if="error" class="notice notice--error">{{ error }}</div>
    <div class="model-config-grid">
      <aside class="panel provider-list">
        <div class="panel__heading"><div><p class="page-kicker">EMBEDDERS</p><h3>配置列表</h3></div><button class="quiet-button" type="button" @click="newConfig"><PhPlus /> 新建</button></div>
        <button v-for="config in configs" :key="config.id" class="provider-card" :class="{ 'provider-card--active': selectedId === config.id }" @click="selectConfig(config)">
          <span :data-ready="config.has_api_key"></span><div><strong>{{ config.name }}</strong><small>{{ config.model_name }} · {{ config.dimension }} 维</small></div><em v-if="config.is_default">DEFAULT</em>
        </button>
      </aside>
      <article class="panel">
        <div class="panel__heading"><div><p class="page-kicker">CONNECTION</p><h3>{{ selectedId ? "更新配置" : "新建配置" }}</h3></div><PhKey :size="22" /></div>
        <form class="research-form" @submit.prevent="save">
          <div class="form-pair"><label><span>配置名称</span><input v-model="form.name" required maxlength="120" /></label><label><span>供应商</span><input v-model="form.provider" required maxlength="80" /></label></div>
          <label><span>Base URL</span><input v-model="form.base_url" required type="url" placeholder="https://provider.example/v1" /></label>
          <div class="form-pair"><label><span>Embedding 模型名称</span><input v-model="form.model_name" required maxlength="160" /></label><label><span>向量维度</span><input v-model.number="form.dimension" required type="number" min="1" max="65536" /></label></div>
          <label><span>API Key</span><input v-model="form.api_key" type="password" autocomplete="new-password" :placeholder="selectedId && configs.find((item) => item.id === selectedId)?.has_api_key ? '已配置；留空表示保持原密钥' : '粘贴密钥'" /></label>
          <label class="model-default-check"><input v-model="form.is_default" type="checkbox" /> 设为默认 Embedding 模型</label>
          <button class="primary-button" type="submit" :disabled="saving"><PhShieldCheck /> {{ saving ? "正在更新" : "更新配置" }}</button>
        </form>
      </article>
    </div>
    <div class="security-note"><PhCheckCircle /><span><strong>索引兼容边界</strong> 模型名称或维度变化会进入新的 Milvus collection。旧向量不会被当成新模型结果，正文和内容哈希仍保存在 PostgreSQL，可随时重建。</span></div>
  </section>
</template>
