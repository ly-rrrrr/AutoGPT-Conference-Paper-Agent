import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, expect, it, vi } from "vitest"

import { getCognitionOverview, startCognitionDiscovery } from "../api"
import CognitionView from "./CognitionView.vue"

vi.mock("../api", () => ({
  getCognitionOverview: vi.fn(),
  prepareCognitionHarness: vi.fn(),
  startCognitionDiscovery: vi.fn(),
  stopCognitionDiscovery: vi.fn(),
}))

const overview = {
  scope: { conference: "CVPR", year: 2026 },
  harness_version: "corpus-cognition-v2",
  material_fingerprint: "1234567890abcdef",
  coverage: {
    papers: 2672,
    arxiv_links: 2672,
    paper_analyses: 2664,
    likes: 2672,
    local_documents: 0,
    paper_memories: 2664,
    cognition_artifacts: 0,
  },
  gaps: { missing_arxiv: 0, missing_analysis: 8, missing_local_document: 2672 },
  latest_run: null,
  discovery_run: null,
  model_ready: true,
  events: [],
  discovery_events: [],
  artifacts: [],
  stages: [
    { id: "paper_memory", name: "论文认知缓存", status: "CACHED", ready: 2664, total: 2672, detail: "缓存" },
    { id: "corpus_discovery", name: "全语料自主发现", status: "READY", ready: 0, total: 2672, detail: "发现" },
  ],
  roles: [],
}

beforeEach(() => {
  vi.mocked(getCognitionOverview).mockResolvedValue(overview)
  vi.mocked(startCognitionDiscovery).mockResolvedValue({
    status: "RUNNING",
    run_id: "run-1",
    message: "已启动发现试运行",
  })
  vi.stubGlobal("confirm", vi.fn(() => true))
})

it("starts only an explicitly confirmed bounded discovery batch", async () => {
  const wrapper = mount(CognitionView, {
    global: { stubs: { RouterLink: { template: "<a><slot /></a>" } } },
  })
  await flushPromises()

  const startButton = wrapper.findAll("button").find((button) => button.text().includes("试运行"))
  expect(startButton).toBeDefined()
  await startButton!.trigger("click")
  await flushPromises()

  expect(window.confirm).toHaveBeenCalledOnce()
  expect(startCognitionDiscovery).toHaveBeenCalledWith({
    conference: "CVPR",
    year: 2026,
    max_model_calls: 1,
    papers_per_batch: 12,
    max_input_chars: 60000,
  })
})
