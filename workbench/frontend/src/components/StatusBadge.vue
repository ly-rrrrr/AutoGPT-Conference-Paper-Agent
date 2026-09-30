<script setup lang="ts">
import { computed } from "vue"
const props = defineProps<{ status?: string | null }>()
const tone = computed(() => {
  const value = props.status?.toUpperCase()
  if (["SUCCESS", "COMPLETED", "MATCHED", "PARSED"].includes(value ?? "")) return "success"
  if (["FAILED", "ERROR"].includes(value ?? "")) return "danger"
  if (["RUNNING", "QUEUED"].includes(value ?? "")) return "active"
  if (["NEEDS_REVIEW", "NOT_FOUND", "MISSING"].includes(value ?? "")) return "muted"
  return "neutral"
})
</script>
<template><span class="status-badge" :data-tone="tone">{{ status || "暂无" }}</span></template>
