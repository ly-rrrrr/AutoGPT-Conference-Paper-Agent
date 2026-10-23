import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, expect, it, vi } from "vitest"

import { getModelConfigs, updateModelConfig } from "../api"
import ModelConfigView from "./ModelConfigView.vue"

vi.mock("../api", () => ({
  createModelConfig: vi.fn(),
  getModelConfigs: vi.fn(),
  updateModelConfig: vi.fn(),
}))

const config = {
  id: "config-1",
  name: "AIHubMix GPT-6 Sol",
  provider: "AIHubMix",
  base_url: "https://aihubmix.com/v1",
  model_name: "gpt-6-sol",
  is_default: true,
  status: "ACTIVE",
  has_api_key: false,
  api_key_mask: null,
  created_at: "2026-10-23T00:00:00Z",
  updated_at: "2026-10-23T00:00:00Z",
}

beforeEach(() => {
  vi.mocked(getModelConfigs).mockResolvedValue({ items: [config], total: 1 })
  vi.mocked(updateModelConfig).mockResolvedValue({ ...config, has_api_key: true, api_key_mask: "••••••••" })
})

it("updates provider settings without reading a saved secret back", async () => {
  const wrapper = mount(ModelConfigView)
  await flushPromises()
  const password = wrapper.get('input[type="password"]')
  expect(password.element.getAttribute("value") ?? "").toBe("")
  await password.setValue("new-secret")
  await wrapper.get("form").trigger("submit")
  await flushPromises()

  expect(updateModelConfig).toHaveBeenCalledWith("config-1", expect.objectContaining({
    base_url: "https://aihubmix.com/v1",
    model_name: "gpt-6-sol",
    api_key: "new-secret",
  }))
  expect(wrapper.get('input[type="password"]').element.getAttribute("value") ?? "").toBe("")
})
