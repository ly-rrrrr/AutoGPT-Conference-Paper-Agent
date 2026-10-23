<script setup lang="ts">
import { PhCheckCircle, PhKey, PhPlus, PhShieldCheck } from "@phosphor-icons/vue"
import { onMounted, reactive, ref } from "vue"
import {
  createModelConfig,
  getModelConfigs,
  updateModelConfig,
  type ModelProviderConfig,
} from "../api"

const configs = ref<ModelProviderConfig[]>([])
const selectedId = ref("")
const saving = ref(false)
const error = ref("")
const message = ref("")
const form = reactive({
  name: "AIHubMix GPT-6 Sol",
  provider: "AIHubMix",
  base_url: "https://aihubmix.com/v1",
  model_name: "gpt-6-sol",
  api_key: "",
  is_default: true,
})

function selectConfig(config: ModelProviderConfig) {
  selectedId.value = config.id
  form.name = config.name
  form.provider = config.provider
  form.base_url = config.base_url
  form.model_name = config.model_name
  form.api_key = ""
  form.is_default = config.is_default
}

function newConfig() {
  selectedId.value = ""
  form.name = "新模型配置"
  form.provider = "OpenAI Compatible"
  form.base_url = "https://api.openai.com/v1"
  form.model_name = ""
  form.api_key = ""
  form.is_default = false
}

async function loadConfigs(preferredId = "") {
  const result = await getModelConfigs()
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
      ...(form.api_key ? { api_key: form.api_key } : {}),
      is_default: form.is_default,
    }
    const saved = selectedId.value
      ? await updateModelConfig(selectedId.value, payload)
      : await createModelConfig(payload)
    form.api_key = ""
    message.value = "模型配置已更新；密钥已写入本机系统凭据库，不会从接口回显。"
    await loadConfigs(saved.id)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "模型配置更新失败"
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    await loadConfigs()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "模型配置加载失败"
  }
})
</script>

<template>
  <section class="page model-config-page">
    <div class="hero-row">
      <div><p class="page-kicker">MODEL PROVIDERS</p><h2>模型配置</h2><p class="lede">统一维护供应商、兼容接口地址、模型名称和默认配置。密钥只写入本机凭据库，页面和 API 均不会读回明文。</p></div>
      <div class="parser-state" :data-ready="configs.some((item) => item.is_default && item.has_api_key)"><span></span><div><strong>默认模型</strong><small>{{ configs.some((item) => item.is_default && item.has_api_key) ? "已配置密钥" : "等待保存密钥" }}</small></div></div>
    </div>
    <div v-if="message" class="notice">{{ message }}</div>
    <div v-if="error" class="notice notice--error">{{ error }}</div>
    <div class="model-config-grid">
      <aside class="panel provider-list">
        <div class="panel__heading"><div><p class="page-kicker">PROVIDERS</p><h3>配置列表</h3></div><button class="quiet-button" type="button" @click="newConfig"><PhPlus /> 新建</button></div>
        <button v-for="config in configs" :key="config.id" class="provider-card" :class="{ 'provider-card--active': selectedId === config.id }" @click="selectConfig(config)">
          <span :data-ready="config.has_api_key"></span><div><strong>{{ config.name }}</strong><small>{{ config.provider }} · {{ config.model_name }}</small></div><em v-if="config.is_default">DEFAULT</em>
        </button>
      </aside>
      <article class="panel">
        <div class="panel__heading"><div><p class="page-kicker">CONNECTION</p><h3>{{ selectedId ? "更新配置" : "新建配置" }}</h3></div><PhKey :size="22" /></div>
        <form class="research-form" @submit.prevent="save">
          <div class="form-pair"><label><span>配置名称</span><input v-model="form.name" required maxlength="120" /></label><label><span>供应商</span><input v-model="form.provider" required maxlength="80" /></label></div>
          <label><span>Base URL</span><input v-model="form.base_url" required type="url" placeholder="https://provider.example/v1" /></label>
          <label><span>模型名称</span><input v-model="form.model_name" required maxlength="160" /></label>
          <label><span>API Key</span><input v-model="form.api_key" type="password" autocomplete="new-password" :placeholder="selectedId && configs.find((item) => item.id === selectedId)?.has_api_key ? '已配置；留空表示保持原密钥' : '粘贴密钥'" /><small>更新其他字段时可以留空；工作台永远不会把已保存密钥填回浏览器。</small></label>
          <label class="model-default-check"><input v-model="form.is_default" type="checkbox" /> 设为主动研究默认模型</label>
          <button class="primary-button" type="submit" :disabled="saving"><PhShieldCheck /> {{ saving ? "正在更新" : "更新配置" }}</button>
        </form>
      </article>
    </div>
    <div class="security-note"><PhCheckCircle /><span><strong>密钥边界</strong> 数据库只保存凭据引用；密钥由当前 Windows 用户的系统凭据库托管。Git、前端状态、API 响应和运行记录都不包含密钥。</span></div>
  </section>
</template>
