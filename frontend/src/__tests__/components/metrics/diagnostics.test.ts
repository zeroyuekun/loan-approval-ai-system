import { curateMetadata, CURATED_METADATA_KEYS } from '@/components/metrics/diagnostics'

describe('curateMetadata', () => {
  it('returns only the curated keys that are present, in canonical order', () => {
    const meta = {
      split_strategy: 'temporal',
      train_size: 8000,
      test_size: 2000,
      cv_auc_mean: 0.87,
      irrelevant_key: 'ignore me',
      reference_probabilities: [0.1, 0.2],
    }
    const result = curateMetadata(meta)
    expect(result.map((r) => r.key)).toEqual(['split_strategy', 'train_size', 'test_size', 'cv_auc_mean'])
    expect(result[0]).toEqual({ key: 'split_strategy', label: 'Split Strategy', value: 'temporal' })
  })

  it('returns an empty array for null/undefined metadata', () => {
    expect(curateMetadata(null)).toEqual([])
    expect(curateMetadata(undefined)).toEqual([])
  })

  it('never exposes more than the curated allow-list', () => {
    const everything: Record<string, number> = {}
    for (const { key } of CURATED_METADATA_KEYS) everything[key] = 1
    everything.secret = 1
    expect(curateMetadata(everything).length).toBe(CURATED_METADATA_KEYS.length)
  })
})
