/**
 * Anchor numbers and external evidence references for the ModelCard panel.
 *
 * Why a constants module: the ModelCard surface is a compliance/portfolio
 * receipt — every claim ("AUC X is consistent with regulator floor Y", "trained
 * on AU-calibrated synthetic data anchored to ABS/APRA/RBA") needs to be
 * traceable to a number that a senior reviewer can audit, not buried in JSX.
 *
 * Sourced from:
 *   - `mrm_dossier._performance_section`        → AUC_REGULATOR_FLOOR / KS_REGULATOR_FLOOR
 *   - `model_selector.MAX_ECE_THRESHOLD`        → ECE_CEILING
 *   - `drift_monitor` + `mrm_dossier`           → PSI_STABLE / PSI_DRIFT
 *   - `trainer.py` overfitting trigger          → GAP_CEILING
 *   - APRA CPS 230 + APP 1-13                   → FAIRNESS_RATIO (4/5ths rule)
 *   - `backend/docs/CALIBRATION_SOURCES.md`     → AU_CALIBRATION_SOURCES (10 anchors)
 *   - PR #141 (GMSC external benchmark)         → GMSC_AUC + reference link
 */

/** Regulator-floor AUC for retail credit scoring (mrm_dossier). */
export const AUC_REGULATOR_FLOOR = 0.75

/** KS-statistic floor consistent with industry convention (mrm_dossier). */
export const KS_REGULATOR_FLOOR = 0.3

/** Maximum tolerable Expected Calibration Error (model_selector). */
export const ECE_CEILING = 0.03

/** Population Stability Index — below this is "stable". */
export const PSI_STABLE = 0.1

/** Population Stability Index — at/above this is significant drift. */
export const PSI_DRIFT = 0.25

/** Train/test AUC gap ceiling — above this trips overfitting warning. */
export const GAP_CEILING = 0.05

/** 4/5ths rule — the disparate-impact ratio threshold. */
export const FAIRNESS_RATIO = 0.8

/**
 * GMSC (Give Me Some Credit) external benchmark result. Re-landed in PR #141.
 * Concrete external-data evidence the synthetic-trained model generalises to
 * a real Kaggle-grade borrower distribution.
 */
export const GMSC_AUC = 0.866
export const GMSC_DATASET_LABEL = 'Give Me Some Credit (n = 150,000)'
export const GMSC_REFERENCE_URL =
  'https://github.com/zeroyuekun/loan-approval-ai-system/blob/master/backend/docs/benchmark.md'

/**
 * AU calibration anchors documented in `backend/docs/CALIBRATION_SOURCES.md`.
 * Each entry is a public regulator/government statistical release that
 * `DataGenerator` calibrates a feature distribution against. The Card lists
 * these to anchor the "trained on Australian-calibrated data" claim.
 */
export const AU_CALIBRATION_SOURCES: ReadonlyArray<{
  short: string
  full: string
}> = [
  { short: 'ABS', full: 'Australian Bureau of Statistics — household income, employment, geography' },
  { short: 'APRA', full: 'Australian Prudential Regulation Authority — lending volumes, arrears' },
  { short: 'RBA', full: 'Reserve Bank of Australia — cash rate, household leverage' },
  { short: 'ATO', full: 'Australian Taxation Office — taxable income distributions' },
  { short: 'Equifax', full: 'Equifax Quarterly Consumer Credit Demand Index' },
  { short: 'Melbourne Institute', full: 'HILDA Survey — household financial wellbeing' },
] as const

/**
 * Public link to the calibration manifest. Pinned to master so the link is
 * stable for CV / portfolio readers; will 404 until PR #180 lands.
 */
export const CALIBRATION_SOURCES_URL =
  'https://github.com/zeroyuekun/loan-approval-ai-system/blob/master/backend/docs/CALIBRATION_SOURCES.md'

/**
 * Out-of-scope segments — populations the model should NOT be used on.
 * Sourced from the ModelCard "intended_use.out_of_scope" + risk register.
 */
export const NOT_VALIDATED_FOR: ReadonlyArray<string> = [
  'Commercial / business lending',
  'Borrowers outside Australia',
  'Non-PAYG income types not represented in training data',
  'Loans below $1,000 or above $1,000,000',
  'Mortgages requiring serviceability assessment beyond DSR',
] as const
