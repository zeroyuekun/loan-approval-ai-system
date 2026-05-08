/**
 * Anchor numbers used by the model-metrics dashboard.
 *
 * Sourced from:
 *   - `mrm_dossier._performance_section`        → AUC_REGULATOR_FLOOR / KS_REGULATOR_FLOOR
 *   - `drift_monitor` + `mrm_dossier`           → PSI_STABLE / PSI_DRIFT
 */

/** Regulator-floor AUC for retail credit scoring (mrm_dossier). */
export const AUC_REGULATOR_FLOOR = 0.75

/** KS-statistic floor consistent with industry convention (mrm_dossier). */
export const KS_REGULATOR_FLOOR = 0.3

/** Population Stability Index — below this is "stable". */
export const PSI_STABLE = 0.1

/** Population Stability Index — at/above this is significant drift. */
export const PSI_DRIFT = 0.25
