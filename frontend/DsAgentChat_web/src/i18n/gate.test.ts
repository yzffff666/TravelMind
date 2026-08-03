import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import zhCN from './messages/zh-CN'

describe('bilingual product gate coverage', () => {
  it('runs the complete frontend test suite', () => {
    const packageJson = JSON.parse(readFileSync('package.json', 'utf8'))
    expect(packageJson.scripts['test:i18n']).toBe('vitest run')
  })

  it('keeps Chinese UI chrome free from known English leftovers', () => {
    const mapSource = readFileSync('src/components/itinerary/MapPanel.vue', 'utf8')

    expect(zhCN.diff.subtitle).not.toContain('itinerary')
    expect(zhCN.map.switchDay).not.toContain('Day')
    expect(zhCN.map.transit).toBe('交通')
    expect(zhCN.map.leafletScriptLoadFailed).toBe('海外地图组件加载失败')
    expect(mapSource).not.toContain('Transit:')
    expect(mapSource).not.toContain('Leaflet script load failed')
  })
})
