export const CURATED_METADATA_KEYS: { key: string; label: string }[] = [
  { key: 'split_strategy', label: 'Split Strategy' },
  { key: 'train_size', label: 'Train Size' },
  { key: 'test_size', label: 'Test Size' },
  { key: 'cv_auc_mean', label: 'CV AUC (mean)' },
  { key: 'cv_auc_std', label: 'CV AUC (std)' },
  { key: 'overfitting_gap', label: 'Overfitting Gap' },
  { key: 'training_time_seconds', label: 'Training Time (s)' },
  { key: 'calibration_method', label: 'Calibration Method' },
]

export interface CuratedMetadataRow {
  key: string
  label: string
  value: unknown
}

export function curateMetadata(meta: Record<string, unknown> | null | undefined): CuratedMetadataRow[] {
  if (!meta) return []
  return CURATED_METADATA_KEYS.filter(({ key }) => meta[key] !== undefined && meta[key] !== null).map(
    ({ key, label }) => ({ key, label, value: meta[key] }),
  )
}

export function formatMetadataValue(value: unknown): string {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(4)
  }
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
