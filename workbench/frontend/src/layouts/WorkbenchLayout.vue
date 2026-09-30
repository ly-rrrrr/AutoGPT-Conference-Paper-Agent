<script setup lang="ts">
import {
  PhBooks,
  PhBrain,
  PhCaretDown,
  PhChartDonut,
  PhDatabase,
  PhFlowArrow,
  PhFlask,
  PhHeart,
  PhList,
  PhMagnifyingGlass,
  PhPulse,
  PhSparkle,
} from "@phosphor-icons/vue"
import { computed, ref } from "vue"
import { useRoute } from "vue-router"

const route = useRoute()
const mobileOpen = ref(false)

const sections = [
  {
    label: "工作台",
    icon: PhChartDonut,
    items: [{ label: "研究总览", to: "/", icon: PhPulse }],
  },
  {
    label: "论文资产",
    icon: PhBooks,
    items: [
      { label: "论文目录", to: "/papers", icon: PhMagnifyingGlass },
      { label: "运行记录", to: "/runs", icon: PhList },
    ],
  },
  {
    label: "采集与分析",
    icon: PhFlask,
    items: [
      { label: "arXiv 映射", to: "/pipelines/mapping", icon: PhFlowArrow },
      { label: "论文分析", to: "/pipelines/analysis", icon: PhBrain },
    ],
  },
  {
    label: "知识库",
    icon: PhDatabase,
    items: [{ label: "文档资产", to: "/knowledge", icon: PhDatabase }],
  },
  {
    label: "个性化",
    icon: PhHeart,
    items: [{ label: "研究偏好", to: "/preferences", icon: PhSparkle }],
  },
]

const pageTitle = computed(() => String(route.meta.title ?? "科研工作台"))
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar" :class="{ 'sidebar--open': mobileOpen }">
      <div class="brand">
        <div class="brand__mark"><PhFlask :size="22" weight="fill" /></div>
        <div>
          <strong>Research Atlas</strong>
          <span>科研工作台</span>
        </div>
      </div>
      <nav aria-label="主导航" class="navigation">
        <section v-for="section in sections" :key="section.label" class="nav-section">
          <div class="nav-section__title">
            <component :is="section.icon" :size="16" />
            <span>{{ section.label }}</span>
            <PhCaretDown :size="12" />
          </div>
          <RouterLink
            v-for="item in section.items"
            :key="item.to"
            :to="item.to"
            class="nav-link"
            @click="mobileOpen = false"
          >
            <component :is="item.icon" :size="17" />
            {{ item.label }}
          </RouterLink>
        </section>
      </nav>
      <div class="system-state">
        <span class="system-state__dot"></span>
        <div><strong>本机工作台</strong><span>数据留在本地</span></div>
      </div>
    </aside>

    <main class="workspace">
      <header class="topbar">
        <button class="mobile-menu" type="button" aria-label="打开导航" @click="mobileOpen = !mobileOpen">
          <PhList :size="22" />
        </button>
        <div>
          <span class="eyebrow">RESEARCH OPERATIONS</span>
          <h1>{{ pageTitle }}</h1>
        </div>
        <div class="topbar__status"><span></span> LOCAL</div>
      </header>
      <div class="page-container"><slot /></div>
    </main>
  </div>
</template>
