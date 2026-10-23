import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, expect, it, vi } from "vitest"

import { createResearchBrief, getResearchBrief, getResearchBriefs, getResearchRuntime } from "../api"
import ResearchView from "./ResearchView.vue"

vi.mock("../api", () => ({
  createResearchBrief: vi.fn(),
  getResearchBrief: vi.fn(),
  getResearchBriefs: vi.fn(),
  getResearchRuntime: vi.fn(),
  startResearchBrief: vi.fn(),
  updateResearchBrief: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(getResearchBriefs).mockResolvedValue({ items: [], total: 0 })
  vi.mocked(getResearchRuntime).mockResolvedValue({
    ready: false,
    control_plane: { name: "AutoGPT", status: "AVAILABLE", detail: "可用" },
    components: [{ id: "artifact-store", name: "Research Artifact Store", status: "READY", detail: "可用" }],
  })
})

it("saves a goal-driven research brief without starting a fake workflow", async () => {
  const createdBrief = {
    id: "brief-1",
    title: "方法迁移地图",
    objective: "理解同一思想如何跨领域迁移",
    scope: { conference: "CVPR", year: 2025 },
    tool_policy: {},
    budget: {},
    output_preferences: {},
    status: "DRAFT",
    created_at: "2026-10-23T00:00:00Z",
    updated_at: "2026-10-23T00:00:00Z",
  }
  vi.mocked(createResearchBrief).mockResolvedValue(createdBrief)
  vi.mocked(getResearchBriefs)
    .mockResolvedValueOnce({ items: [], total: 0 })
    .mockResolvedValueOnce({ items: [createdBrief], total: 1 })
  vi.mocked(getResearchBrief).mockResolvedValue({
    ...createdBrief,
    artifacts: [], evidence: [], insights: [], dependencies: [], runs: [], events: [],
    coverage: {
      paper_count: 1,
      analysis_count: 1,
      document_count: 0,
      status: "LIMITED",
      blockers: [],
      warnings: ["尚无可下钻的本地全文。"],
    },
  })

  const wrapper = mount(ResearchView)
  await flushPromises()
  await wrapper.get('input[placeholder="例如：CVPR 2025 方法思想迁移地图"]').setValue("方法迁移地图")
  await wrapper.get("textarea").setValue("理解同一思想如何跨领域迁移")
  await wrapper.get("form").trigger("submit")
  await flushPromises()

  expect(createResearchBrief).toHaveBeenCalledWith(expect.objectContaining({
    objective: "理解同一思想如何跨领域迁移",
    tool_policy: expect.objectContaining({ allow_counterevidence_search: true }),
  }))
  expect(wrapper.text()).toContain("AI 运行时待接入")
})
