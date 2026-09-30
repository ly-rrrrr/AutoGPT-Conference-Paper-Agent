import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, expect, it, vi } from "vitest"

import PapersView from "./PapersView.vue"
import { getPapers } from "../api"

vi.mock("../api", () => ({ getPapers: vi.fn() }))

beforeEach(() => {
  vi.mocked(getPapers).mockResolvedValue({
    total: 0,
    page: 1,
    page_size: 25,
    items: [],
  })
})

it("loads papers with the selected mapping status", async () => {
  const wrapper = mount(PapersView, {
    global: { stubs: { RouterLink: { template: "<a><slot /></a>" } } },
  })
  await flushPromises()

  await wrapper.get("select[name=mapping_status]").setValue("matched")
  await flushPromises()

  expect(getPapers).toHaveBeenLastCalledWith(
    expect.objectContaining({ mapping_status: "matched" }),
  )
})
