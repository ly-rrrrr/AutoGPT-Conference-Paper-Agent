import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, expect, it, vi } from "vitest"

import AnalysisView from "./AnalysisView.vue"
import { getPipelineStatus, startAnalysis } from "../api"

vi.mock("../api", () => ({ getPipelineStatus: vi.fn(), startAnalysis: vi.fn(), stopAnalysis: vi.fn() }))

beforeEach(() => {
  vi.mocked(getPipelineStatus).mockResolvedValue({ analysis_runs: [], mapping: { status: "IDLE", exit_code: null } })
  vi.mocked(startAnalysis).mockResolvedValue({ status: "QUEUED", message: "任务已提交" })
  vi.stubGlobal("confirm", vi.fn(() => true))
})

it("does not start analysis until the user submits", async () => {
  const wrapper = mount(AnalysisView)
  await flushPromises()
  expect(startAnalysis).not.toHaveBeenCalled()

  await wrapper.get("form").trigger("submit")
  await flushPromises()

  expect(startAnalysis).toHaveBeenCalledTimes(1)
})
