import { mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { describe, expect, it } from "vitest"

import WorkbenchLayout from "./WorkbenchLayout.vue"

describe("WorkbenchLayout", () => {
  it("groups secondary pages under first-level modules", async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/", component: { template: "<p>页面</p>" } }],
    })
    await router.push("/")
    await router.isReady()
    const wrapper = mount(WorkbenchLayout, {
      global: { plugins: [router] },
      slots: { default: "页面" },
    })

    expect(wrapper.text()).toContain("工作台")
    expect(wrapper.text()).toContain("论文资产")
    expect(wrapper.text()).toContain("采集与分析")
    expect(wrapper.text()).toContain("知识库")
    expect(wrapper.text()).toContain("个性化")
  })
})
