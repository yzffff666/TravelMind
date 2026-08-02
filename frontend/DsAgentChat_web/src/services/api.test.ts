import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiService } from './api'

describe('ApiService.travelQueryStream locale contract', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('always sends the selected UI locale', async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.close()
      },
    })
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body,
      headers: new Headers(),
      status: 200,
    })
    vi.stubGlobal('fetch', fetchMock)

    await ApiService.travelQueryStream(
      { query: 'Plan a trip', userId: '1', uiLocale: 'en' },
      {},
    )

    const request = fetchMock.mock.calls[0]?.[1]
    const formData = request?.body as FormData
    expect(formData.get('ui_locale')).toBe('en')
  })
})
