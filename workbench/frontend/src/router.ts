import { createRouter, createWebHistory } from "vue-router"

import AnalysisView from "./views/AnalysisView.vue"
import DashboardView from "./views/DashboardView.vue"
import KnowledgeView from "./views/KnowledgeView.vue"
import MappingView from "./views/MappingView.vue"
import PaperDetailView from "./views/PaperDetailView.vue"
import PapersView from "./views/PapersView.vue"
import PreferencesView from "./views/PreferencesView.vue"
import RunsView from "./views/RunsView.vue"

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: DashboardView, meta: { title: "研究总览" } },
    { path: "/papers", component: PapersView, meta: { title: "论文目录" } },
    { path: "/papers/:id", component: PaperDetailView, meta: { title: "论文详情" } },
    { path: "/pipelines/mapping", component: MappingView, meta: { title: "arXiv 映射" } },
    { path: "/pipelines/analysis", component: AnalysisView, meta: { title: "论文分析" } },
    { path: "/runs", component: RunsView, meta: { title: "运行记录" } },
    { path: "/knowledge", component: KnowledgeView, meta: { title: "知识库" } },
    { path: "/preferences", component: PreferencesView, meta: { title: "研究偏好" } },
  ],
})
