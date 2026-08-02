import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const activeRuntimeFiles = [
  'src/views/TravelPlanner.vue',
  'src/views/Login.vue',
  'src/components/chat/InputBar.vue',
  'src/components/chat/PhaseIndicator.vue',
  'src/components/chat/DiffCard.vue',
  'src/components/itinerary/EmptyState.vue',
  'src/components/itinerary/ErrorState.vue',
  'src/components/itinerary/TripOverview.vue',
  'src/components/itinerary/BudgetCard.vue',
  'src/components/itinerary/ItineraryTimeline.vue',
  'src/components/itinerary/MapPanel.vue',
]

const nonUiChineseFragments = new Map([
  ['src/views/TravelPlanner.vue', ['（可选，不填也能先出草案）']],
  ['src/components/itinerary/MapPanel.vue', [
    '上午', '下午', '晚上',
    '普吉', '泰国', '东京', '大阪', '京都', '首尔', '新加坡',
  ]],
])

function stripComments(source) {
  return source
    .replace(/<!--[^]*?-->/g, '')
    .replace(/\/\*[^]*?\*\//g, '')
    .split('\n')
    .map((line) => line.replace(/\/\/.*$/, ''))
    .join('\n')
}

const violations = []

for (const relativePath of activeRuntimeFiles) {
  const source = stripComments(readFileSync(resolve(relativePath), 'utf8'))
  const allowed = nonUiChineseFragments.get(relativePath) ?? []

  source.split('\n').forEach((originalLine, index) => {
    const line = allowed.reduce(
      (current, fragment) => current.replaceAll(fragment, ''),
      originalLine,
    )
    if (/\p{Script=Han}/u.test(line)) {
      violations.push(`${relativePath}:${index + 1}: ${originalLine.trim()}`)
    }
  })
}

if (violations.length > 0) {
  console.error('Uncatalogued Chinese found in active runtime UI files:')
  violations.forEach((violation) => console.error(`- ${violation}`))
  process.exit(1)
}

console.log(`i18n visible-string inventory passed (${activeRuntimeFiles.length} active files)`)
