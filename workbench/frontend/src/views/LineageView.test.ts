import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { describe, expect, it, vi } from "vitest"

import LineageView from "./LineageView.vue"


vi.mock("../api", () => ({
  getLineageOverview: vi.fn().mockResolvedValue({
    papers_with_lineage: 0,
    reference_works: 0,
    references: 0,
    evidence: 0,
    relations: {},
    parser: { name: "GROBID", ready: false },
  }),
  getLineagePapers: vi.fn().mockResolvedValue({ items: [] }),
  getPaperLineage: vi.fn(),
  startLineageExtraction: vi.fn(),
}))


describe("LineageView", () => {
  it("explains missing lineage data without pretending extraction succeeded", async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/lineage", component: LineageView }],
    })
    await router.push("/lineage")
    await router.isReady()

    const wrapper = mount(LineageView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain("相关工作谱系")
    expect(wrapper.text()).toContain("解析服务未就绪")
    expect(wrapper.text()).toContain("没有已映射到 arXiv 的论文")
  })
})
