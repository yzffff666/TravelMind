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

  it('exposes response_language on the typed intent event', async () => {
    const frame = [
      'event: intent_routed',
      `data: ${JSON.stringify({
        request_id: 'req-1',
        conversation_id: 'conv-1',
        revision_id: null,
        timestamp: '2026-08-03T00:00:00Z',
        payload: {
          intent: 'create',
          intent_detail: 'new_trip',
          response_language: 'zh-CN',
        },
      })}`,
      '',
      '',
    ].join('\n')
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(frame))
        controller.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      body,
      headers: new Headers(),
      status: 200,
    }))
    let responseLanguage: 'en' | 'zh-CN' | undefined

    await ApiService.travelQueryStream(
      { query: '规划一次旅行', userId: '1', uiLocale: 'en' },
      {
        onIntentRouted: (envelope) => {
          responseLanguage = envelope.payload.response_language
        },
      },
    )

    expect(responseLanguage).toBe('zh-CN')
  })
})
