import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, expect, it, vi } from "vitest"

import { getAtlasGraph, getAtlasInsights, getAtlasOverview } from "../api"
import AtlasView from "./AtlasView.vue"

vi.mock("cytoscape", () => ({ default: vi.fn(() => ({ on: vi.fn(), destroy: vi.fn() })) }))
vi.mock("../api", () => ({
  getAtlasGraph: vi.fn(),
  getAtlasInsights: vi.fn(),
  getAtlasOverview: vi.fn(),
  startAtlasSynthesis: vi.fn(),
  stopAtlasSynthesis: vi.fn(),
  updateMethodInsightStatus: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(getAtlasOverview).mockResolvedValue({
    scope: { conference: "CVPR", year: 2026 },
    model_ready: true,
    discovery_artifacts: 0,
    consumed_discovery_artifacts: 0,
    remaining_discovery_artifacts: 0,
    insights: 0,
    challenged: 0,
    published: 0,
    domains: 0,
    mechanisms: 0,
    latest_run: null,
    events: [],
  })
  vi.mocked(getAtlasInsights).mockResolvedValue({ items: [], total: 0 })
  vi.mocked(getAtlasGraph).mockResolvedValue({ nodes: [], edges: [], insights: 0 })
})

it("explains the product path when discovery has not produced inputs", async () => {
  const wrapper = mount(AtlasView, {
    global: { stubs: { RouterLink: { template: "<a><slot /></a>" } } },
  })
  await flushPromises()

  expect(wrapper.text()).toContain("方法认知图谱")
  expect(wrapper.text()).toContain("Cartographer")
  expect(wrapper.text()).toContain("先到“认知运行”执行自主发现")
  const startButton = wrapper.findAll("button").find((item) => item.text().includes("启动 3 次调用上限"))
  expect(startButton?.attributes("disabled")).toBeDefined()
})
