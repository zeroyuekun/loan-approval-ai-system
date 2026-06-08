# Codex Adversarial Review — v1.10.7 Response

**Date:** 2026-05-07
**Status:** Approved design, pending implementation plan
**Scope:** All four findings from the 2026-05-07 whole-project Codex adversarial review
**Codex verdict:** `needs-attention` — diff vs root commit `096110e6`
**Predecessor:** v1.10.6 release (master `1d98ef8`)

## Context

After v1.10.6 shipped, a project-wide Codex adversarial review surfaced four findings:

| # | Finding | File | Codex severity | My severity | Disposition |
|---|---|---|---|---|---|
| 1 | `ModelActivateView` deactivates **every** active segment, then turns one back on — silently breaks scoring for other segments | `backend/apps/ml_engine/views.py:370-377` | high | **high** | In scope |
| 2 | Training path promotes `is_active=True` without consulting `ModelValidationReport`; governance metadata is documentation-only | `backend/apps/ml_engine/tasks.py:119-143` | high | **medium** | In scope (warn-mode default) |
| 3 | `StaffCustomerListView` / `StaffCustomerProfileView` / `StaffCustomerActivityView` accept any `user_id`, including staff — officers can enumerate admin/officer accounts and auto-create `CustomerProfile` rows for them | `backend/apps/accounts/views.py:272-309` | medium | **high** (PII) | In scope |
| 4 | `rotate_encryption_key` re-encrypts opaque ciphertext as if it were plaintext when `from_db_value` falls back on `InvalidToken` — irreversible double-encryption | `backend/apps/accounts/management/commands/rotate_encryption_key.py:38-46` | medium | **medium** | In scope |

**My critical assessment of Codex's review.** All four findings were verified against the actual code (read into context before writing this spec). Codex's recommendations are sound. I'm reordering severity to put the staff endpoint privilege escalation as **high** (it's a live PII trust-boundary leak today, not a future-state outage path) and Finding 2 as **medium** (existing fairness/promotion gates from PRs #163-#165 already block on poor metrics; the validation-report layer is governance maturity, not safety). I'm taking 4/4 of Codex's recommendations with the following adjustments:

- **#1**: Take the segment-scoped fix as written. Add the "refuse if it leaves a previously-served segment uncovered with no `unified` fallback" guard — Codex called this out and it's right.
- **#2**: Take the gate enforcement. Default to `warn` mode (Codex didn't specify; precedent from PRs #163-#165 is `warn` first, flip to `block` after operator readiness). Add a `force=true` break-glass on manual activate with audit log.
- **#3**: Take filtering. Add stronger guard: officers cannot fetch OTHER officer/admin profiles either, only customers. Codex implied this; I'm making it explicit.
- **#4**: Take the explicit-decrypt fix. **Make `--dry-run` the default** and require `--apply` to write — go further than Codex's "preferably with a dry-run mode". Better ergonomics for an irreversible operation.

Packaging rationale: four atomic PRs stacked on master under a new `v1.10.7 — Codex adversarial response` CHANGELOG section, plus a release PR. Mirrors v1.9.3 / v1.9.4 / v1.10.3 patterns. Each fix has a distinct file surface and test surface; bundling would muddy revert boundaries and break the retarget-before-delete-merge discipline.

## PR #A — Segment-safe manual model activation (Finding 1, high)

**Problem.** `ModelActivateView.post()` runs `ModelVersion.objects.filter(is_active=True).update(is_active=False, traffic_percentage=0)` with no segment filter, then activates the requested model. In a deployment with separate `personal` / `home` / `unified` champions, activating a `personal` challenger silently drops the `home` and `unified` champions to `is_active=False`. Subsequent scoring for those segments hits `No active model version found for segment ...` until an operator manually repairs traffic.

The training path at `tasks.py:119-122` already filters by segment when deactivating during a fresh model creation. Manual activation should mirror that invariant.

**Chosen approach.** Filter the deactivation step by `version.segment`. Add a defensive guard: if activating this version would leave a previously-served segment with no active model and no `unified` fallback, refuse with HTTP 409 and a structured error explaining what's missing. Allow first-activation of a brand-new segment (no previously-active model in that segment is the legitimate path).

**Design.**

Edit `backend/apps/ml_engine/views.py`:

```python
class ModelActivateView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        try:
            version = ModelVersion.objects.get(pk=pk)
        except ModelVersion.DoesNotExist:
            return Response({"error": "Model not found"}, status=status.HTTP_404_NOT_FOUND)

        # Coverage guard: enumerate segments that currently have an active model.
        # If activating `version` (a non-unified model) would leave a previously-served
        # non-unified segment with no active model AND no unified fallback, refuse.
        active_segments = set(
            ModelVersion.objects.filter(is_active=True)
            .values_list("segment", flat=True)
        )
        unified_active = "unified" in active_segments
        target_segment = version.segment

        if target_segment != "unified":
            # Segments that would lose coverage: every non-unified active segment
            # except this one's own segment, IF that segment had only this model
            # (impossible since version is currently inactive) — really we just
            # need to not touch other segments. Filter scopes that.
            pass  # Coverage is preserved by segment-scoped filter below.

        with transaction.atomic():
            ModelVersion.objects.filter(
                is_active=True,
                segment=target_segment,
            ).update(is_active=False, traffic_percentage=0)
            version.is_active = True
            version.traffic_percentage = 100
            version.save()

            AuditLog.objects.create(
                user=request.user,
                action="model_activate",
                resource_type="ModelVersion",
                resource_id=str(version.id),
                details={
                    "version": version.version,
                    "segment": target_segment,
                    "previous_active_segments": sorted(active_segments),
                },
                ip_address=request.META.get("REMOTE_ADDR"),
            )

        return Response({
            "message": f"Model {version.version} activated as champion for segment '{target_segment}'",
            "model_id": str(version.id),
            "segment": target_segment,
        })
```

The "coverage guard" branch above is deliberately a no-op in the simple form — the segment-scoped filter alone preserves coverage by construction (we only deactivate same-segment models). The explanatory comment captures intent so future readers understand why no extra logic is needed.

**Behavior change risk.** Existing callers expecting "activate this and nothing else changes" get exactly that. Existing callers (if any) relying on the side effect of clearing other segments will break — but that side effect is the bug.

**Tests** in `backend/apps/ml_engine/tests/test_model_activate.py` (new file or extend existing):

- `test_manual_activate_does_not_touch_other_segments` — fixture: active `personal` + `home` + `unified`. Activate a new `personal` challenger. Assert `home` and `unified` remain `is_active=True` and `traffic_percentage=100`.
- `test_manual_activate_first_time_for_segment` — fixture: only `unified` active. Activate first `home` model. Assert `home` activates, `unified` stays untouched.
- `test_manual_activate_writes_audit_log` — assert `AuditLog` row with action `model_activate` and the previous-active-segments snapshot.

## PR #B — Validation sign-off gate on promotion (Finding 2, medium → enforced as warn)

**Problem.** The `validate_model` management command and `ModelValidationReport` model define a governance sign-off layer (a validator approves a candidate model with `signed_off=True, outcome="approved"`). The training path in `tasks.py` and the manual `ModelActivateView` both promote `is_active=True` without consulting that artifact. Under operational pressure, an admin can ship an unvalidated model directly to production. The existing fairness gate (PR #163) and promotion gate (PRs #164–#165) check **performance metrics**; this layer is the missing **governance** check.

**Chosen approach.** Add a third gate, `evaluate_validation_signoff_gate(candidate, mode)`, that mirrors the `warn|block|off` dispatch pattern from PRs #163–#165. Apply it in both promotion paths. Default mode is `warn` so the demo flow keeps working — operators flip to `block` once they've established a sign-off cadence. Manual activation accepts a `force=true` query param that bypasses the gate with a dedicated audit log entry (break-glass).

**Design.**

New service module `backend/apps/ml_engine/services/validation_gate.py`:

```python
"""Validation sign-off gate. Mirrors the warn|block|off pattern from
the fairness gate (PR #163) and promotion gate (PRs #164-#165)."""

from typing import Optional

from apps.ml_engine.models import ModelValidationReport


class ValidationSignoffBlocked(Exception):
    """Raised when validation gate is in `block` mode and signoff is missing."""

    def __init__(self, reason: str, payload: dict):
        super().__init__(reason)
        self.payload = payload


def evaluate_validation_signoff_gate(
    candidate,
    mode: str = "warn",
    bypass: bool = False,
) -> dict:
    """Check that the candidate model has an approved, signed-off
    ModelValidationReport. Returns a structured decision dict.

    `mode`:
        - `block`: raise ValidationSignoffBlocked on missing/unapproved signoff
        - `warn`: log + return decision but allow activation
        - `off`: skip the check entirely

    `bypass`: caller has provided an audited break-glass override.
    """

    if mode == "off" or bypass:
        return {
            "mode": mode,
            "bypass": bypass,
            "result": "skipped",
            "reason": "gate disabled" if mode == "off" else "break-glass override",
        }

    report = (
        ModelValidationReport.objects
        .filter(version_str=candidate.version, segment=candidate.segment)
        .order_by("-created_at")
        .first()
    )

    if report is None:
        decision = {
            "mode": mode,
            "result": "blocked",
            "reason": "no_validation_report",
            "candidate_version": candidate.version,
            "segment": candidate.segment,
        }
    elif not report.signed_off or report.outcome != "approved":
        decision = {
            "mode": mode,
            "result": "blocked",
            "reason": "report_not_approved",
            "report_id": str(report.id),
            "outcome": report.outcome,
            "signed_off": report.signed_off,
        }
    else:
        decision = {
            "mode": mode,
            "result": "passed",
            "report_id": str(report.id),
        }

    if decision["result"] == "blocked" and mode == "block":
        raise ValidationSignoffBlocked(decision["reason"], decision)

    return decision
```

Apply in `backend/apps/ml_engine/tasks.py` immediately after the existing `promotion_gate_decision` line:

```python
from apps.ml_engine.services.validation_gate import evaluate_validation_signoff_gate

validation_mode = getattr(settings, "ML_VALIDATION_SIGNOFF_GATE_MODE", "warn")
validation_decision = evaluate_validation_signoff_gate(candidate_stub, validation_mode)
```

Persist the decision into `mv.training_metadata` alongside the existing `fairness_gate_mode` and `promotion_gate_mode` keys.

Apply in `ModelActivateView` (PR #A's edit):

```python
def post(self, request, pk):
    # ... existing 404 check ...
    force = request.query_params.get("force", "").lower() == "true"
    validation_mode = getattr(settings, "ML_VALIDATION_SIGNOFF_GATE_MODE", "warn")
    try:
        validation_decision = evaluate_validation_signoff_gate(
            version, validation_mode, bypass=force,
        )
    except ValidationSignoffBlocked as exc:
        return Response(
            {"error": "validation_signoff_required", "details": exc.payload},
            status=status.HTTP_409_CONFLICT,
        )

    # ... existing activation block ...

    AuditLog.objects.create(
        user=request.user,
        action="model_activate_force" if force else "model_activate",
        # ...
        details={
            # ...
            "validation_decision": validation_decision,
        },
    )
```

**Settings.** Add to `backend/config/settings.py`:

```python
ML_VALIDATION_SIGNOFF_GATE_MODE = os.getenv("ML_VALIDATION_SIGNOFF_GATE_MODE", "warn")
# 'warn' (default) | 'block' | 'off'
```

**Tests** in `backend/apps/ml_engine/tests/test_validation_gate.py` (new):

- `test_no_report_blocks_in_block_mode` — mode `block`, no report → `ValidationSignoffBlocked`.
- `test_no_report_warns_in_warn_mode` — mode `warn`, no report → returns `{result: blocked}` without raising.
- `test_off_mode_skips_check` — mode `off` → returns `{result: skipped}` regardless of report state.
- `test_unapproved_report_blocks` — report with `signed_off=False` or `outcome="conditional"` → blocked.
- `test_approved_report_passes` — report with `signed_off=True, outcome="approved"` → passed.
- `test_force_bypasses_gate_and_audits` — manual activate with `?force=true` → 200, audit log action is `model_activate_force` and details include the bypass marker.

## PR #C — Customer-only filter on staff endpoints (Finding 3, high)

**Problem.** The three "Staff Customer" endpoints accept any `CustomUser` regardless of role:

- `StaffCustomerListView.get_queryset` returns `CustomUser.objects.all()` with no `role="customer"` filter.
- `StaffCustomerProfileView.get_object` runs `get_object_or_404(CustomUser, pk=user_id)` (no role check) then `CustomerProfile.objects.get_or_create(user_id=user_id)` — creating a `CustomerProfile` row attached to admin/officer accounts.
- `StaffCustomerActivityView.get` accepts any `user_id` and serves their applications/emails/agent runs.

An officer can enumerate admin emails via `/customers/?search=`, fetch admin profile data via `/customers/<admin_id>/`, and pollute the database with phantom `CustomerProfile` rows attached to staff accounts. This is a trust-boundary leak: the route contract says "customer surface" but the implementation exposes the entire user table.

**Chosen approach.** Three small edits, one PR. Filter by `role="customer"` at every read site. For the profile endpoint, the role check has to happen before the `get_or_create` so we never create a `CustomerProfile` for a non-customer user.

**Design.**

Edit `backend/apps/accounts/views.py`:

```python
class StaffCustomerListView(generics.ListAPIView):
    serializer_class = UserSerializer
    permission_classes = (IsAdminOrOfficer,)

    def get_queryset(self):
        qs = (
            CustomUser.objects
            .filter(role="customer")
            .select_related("profile")
            .order_by("-created_at")
        )
        # ...search filter unchanged...
        return qs


class StaffCustomerProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = (IsAdminOrOfficer,)
    lookup_field = "user_id"
    lookup_url_kwarg = "user_id"

    def get_object(self):
        user_id = self.kwargs["user_id"]
        user = get_object_or_404(CustomUser, pk=user_id, role="customer")
        profile, _ = (
            CustomerProfile.objects
            .select_related("user")
            .get_or_create(user=user)
        )
        return profile


class StaffCustomerActivityView(generics.GenericAPIView):
    permission_classes = (IsAdminOrOfficer,)

    def get(self, request, user_id):
        try:
            customer = CustomUser.objects.get(pk=user_id, role="customer")
        except CustomUser.DoesNotExist:
            return Response(
                {"error": "Customer not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        # ...rest unchanged...
```

**Behavior change risk.** Officers attempting to access non-customer rows now receive 404 instead of 200 with admin/officer data. This is the intended change. The list endpoint will return fewer rows (customers only); existing UI consumers should already expect this — if any UI code paginated through "all users" via `/customers/`, that was a latent bug.

**Tests** in `backend/apps/accounts/tests/test_staff_customer_endpoints.py` (new or extend existing):

- `test_list_excludes_admin_and_officer_rows` — fixture: 1 admin, 1 officer, 2 customers. Officer hits `/customers/`, asserts response has 2 rows, none with `role` admin/officer.
- `test_list_search_does_not_leak_admin_email` — admin with email `admin@example.com`, officer searches `?search=admin`, asserts admin row not returned.
- `test_profile_404_for_admin_target` — officer hits `/customers/<admin_id>/`, asserts 404.
- `test_profile_404_for_officer_target` — officer hits `/customers/<other_officer_id>/`, asserts 404.
- `test_profile_does_not_create_phantom_row_for_admin` — before request, no `CustomerProfile` for admin. Officer hits `/customers/<admin_id>/`, asserts response is 404 AND `CustomerProfile.objects.filter(user_id=admin_id).count() == 0`.
- `test_activity_404_for_non_customer_target` — officer hits `/customers/<admin_id>/activity/`, asserts 404.
- `test_customer_target_still_works` — officer hits `/customers/<customer_id>/`, asserts 200 with profile data.

## PR #D — Safe key rotation with explicit decrypt + dry-run-default (Finding 4, medium)

**Problem.** `rotate_encryption_key` walks each profile and, for every encrypted field, fetches `getattr(profile, field_name, None)`. That triggers `EncryptedCharField.from_db_value` which silently returns the **raw ciphertext** when decryption fails (`InvalidToken`). The command then marks the field as "changed" because the value is non-empty, calls `profile.save(update_fields=encrypted_fields)`, and re-encrypts that opaque ciphertext as if it were plaintext. A recoverable key-gap incident becomes permanent data loss.

**Chosen approach.** Replace the `getattr → save` loop with explicit decryption using a `MultiFernet` over the configured keyring. Track per-row decrypt errors. Abort the command if any row fails decryption unless `--allow-failures` is explicitly provided. Make `--dry-run` the default — operators must pass `--apply` to actually write. This is the single most useful guardrail for an irreversible operation; Codex suggested it as nice-to-have, I'm making it default.

**Design.**

Rewrite `backend/apps/accounts/management/commands/rotate_encryption_key.py`:

```python
"""Re-encrypt all PII fields with the current primary Fernet key.

Workflow:
    1. Generate a new key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    2. Prepend new key to FIELD_ENCRYPTION_KEY (comma-separated): NEW_KEY,OLD_KEY
    3. python manage.py rotate_encryption_key            # dry-run by default
    4. python manage.py rotate_encryption_key --apply    # commit changes
    5. After successful rotation, remove the old key from FIELD_ENCRYPTION_KEY
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import CustomerProfile

ENCRYPTED_FIELDS = [
    "primary_id_number",
    "secondary_id_number",
    "phone",
    "address_line_1",
    "address_line_2",
    "employer_name",
    "date_of_birth",
    "gross_annual_income",
    "other_income",
    "partner_annual_income",
]


class Command(BaseCommand):
    help = "Re-encrypt all PII fields with the current primary Fernet key. Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write changes. Without this flag the command runs in dry-run mode.",
        )
        parser.add_argument(
            "--allow-failures",
            action="store_true",
            help="Continue past rows that fail decryption (audit-logged). Without this flag, the command aborts on the first failure.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        allow_failures = options["allow_failures"]

        keys = self._load_keys()
        multi_fernet = MultiFernet([Fernet(k.encode() if isinstance(k, str) else k) for k in keys])
        primary_fernet = Fernet(keys[0].encode() if isinstance(keys[0], str) else keys[0])

        profiles = CustomerProfile.objects.all()
        total = profiles.count()
        rotated = 0
        skipped_failures = []

        mode_label = "APPLY" if apply_changes else "DRY-RUN"
        self.stdout.write(f"[{mode_label}] Rotating {total} profiles across {len(ENCRYPTED_FIELDS)} fields...")

        # Use raw .values() to fetch ciphertext bytes without going through from_db_value.
        rows = profiles.values("id", *ENCRYPTED_FIELDS).iterator(chunk_size=100)

        for row in rows:
            decrypted = {}
            row_errors = []
            for field in ENCRYPTED_FIELDS:
                ciphertext = row[field]
                if not ciphertext:
                    continue
                try:
                    plaintext = multi_fernet.decrypt(
                        ciphertext.encode() if isinstance(ciphertext, str) else ciphertext
                    )
                    decrypted[field] = plaintext
                except InvalidToken:
                    row_errors.append(field)

            if row_errors:
                skipped_failures.append({"profile_id": str(row["id"]), "fields": row_errors})
                if not allow_failures:
                    self.stdout.write(self.style.ERROR(
                        f"Profile {row['id']} failed decryption on fields: {row_errors}. "
                        f"Aborting. Use --allow-failures to skip and continue."
                    ))
                    raise CommandError("Rotation aborted: decryption failures.")
                else:
                    self.stdout.write(self.style.WARNING(
                        f"Skipping profile {row['id']}: decrypt failures on {row_errors}"
                    ))
                    continue

            if not decrypted:
                continue

            if apply_changes:
                with transaction.atomic():
                    update_kwargs = {
                        field: primary_fernet.encrypt(plaintext).decode()
                        for field, plaintext in decrypted.items()
                    }
                    CustomerProfile.objects.filter(pk=row["id"]).update(**update_kwargs)
            rotated += 1

        verb = "Re-encrypted" if apply_changes else "Would re-encrypt"
        self.stdout.write(self.style.SUCCESS(f"{verb} {rotated} of {total} profiles."))
        if skipped_failures:
            self.stdout.write(self.style.WARNING(
                f"Skipped {len(skipped_failures)} profiles with decryption failures: {skipped_failures}"
            ))
        if not apply_changes:
            self.stdout.write(self.style.NOTICE("DRY-RUN: no database changes written. Re-run with --apply to commit."))

    def _load_keys(self):
        raw = getattr(settings, "FIELD_ENCRYPTION_KEY", "") or ""
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if not keys:
            raise CommandError("FIELD_ENCRYPTION_KEY is not configured.")
        return keys
```

**Note on raw ciphertext access.** Using `.values()` bypasses `from_db_value` because we're asking the ORM for the raw column dictionary, not model instances. The encrypted column type is stored as a string/bytea and `.values()` returns it untouched.

**Caveat: PR #D depends on the actual storage shape of `EncryptedCharField` in this codebase.** If the local field implementation already returns raw ciphertext from `.values()`, the design above works as-is. If it intercepts at a deeper level, the implementation plan needs to fetch the raw column via `connection.cursor()`. The first executor task for PR #D is to verify this assumption against the field code in `backend/apps/accounts/fields.py` (or wherever `EncryptedCharField` lives) before writing the rotation logic.

**Tests** in `backend/apps/accounts/tests/test_rotate_encryption_key.py` (new):

- `test_dry_run_is_default_no_writes` — call command without `--apply`, assert no `CustomerProfile` row was modified (snapshot field values before/after).
- `test_apply_re_encrypts_with_primary_key` — set keyring to `[NEW, OLD]`, encrypt fixture data with `OLD`, run with `--apply`, assert fields decrypt cleanly using only `[NEW]`.
- `test_corrupt_ciphertext_aborts_without_allow_failures` — poison one field with raw bytes that aren't valid Fernet ciphertext, run with `--apply` only, assert `CommandError` and zero rows modified.
- `test_corrupt_ciphertext_skipped_with_allow_failures` — same poison, run with `--apply --allow-failures`, assert healthy rows are re-encrypted, poisoned row is left untouched, command exits 0.
- `test_dry_run_reports_what_would_happen` — capture stdout, assert the "Would re-encrypt N of M" summary appears.

## PR #E — Release v1.10.7

- Bump `APP_VERSION` in `backend/config/settings.py` from `1.10.6` to `1.10.7`.
- Bump `version` in `frontend/package.json` from `1.10.6` to `1.10.7`.
- Add `CHANGELOG.md` entry:

  ```markdown
  ## v1.10.7 — 2026-05-07 — Codex adversarial response

  Codex graded `needs-attention` on the v1.10.6 master tree. Four findings, four atomic PRs:

  - **PR #A** (#TBD): Segment-safe manual model activation (`ModelActivateView`)
  - **PR #B** (#TBD): Validation sign-off gate on promotion (warn-mode default, configurable to `block`/`off` via `ML_VALIDATION_SIGNOFF_GATE_MODE`)
  - **PR #C** (#TBD): Customer-only filter on staff endpoints (closes a PII trust-boundary leak)
  - **PR #D** (#TBD): Safe key rotation with explicit decrypt + dry-run-default (`--apply` required to write)
  ```

- Tag `v1.10.7` after merge to master.

## Sequencing

PRs A, C, D are independent — can land in any order. PR B's `validation_gate.py` plugs into existing settings infrastructure from PRs #163–#165, so it can also land independently — but its application sites in `tasks.py` and `views.py` overlap with PR A's edits to `views.py`, so **PR B must rebase onto PR A's branch** if A merges first.

Suggested merge order: **C → D → A → B → E**. C and D are pure file-isolated; A is the smaller of the two ML changes; B builds on A's audit-log additions.

Apply retarget-before-delete-merge discipline at each step (per `feedback_stacked_pr_merges.md` in memory).

## Out of scope (deliberate)

- 2FA on staff accounts (deferred since v1.9.4)
- Per-segment traffic split UI
- Refactoring `EncryptedCharField` itself — fix the rotation tool, leave field semantics alone
- Rate-limiting on the staff customer search endpoint (out of scope for this round; track separately if needed)

## Risk acknowledgements

- **PR #B with `block` mode** could halt the demo flow if no validation reports exist. Defaulting to `warn` mitigates; document the cutover procedure in the release notes alongside the existing fairness/promotion gate runbook.
- **PR #D** may surface latent decrypt failures in production data. That's the correct behavior; operators should always run without `--apply` first to discover what's broken before committing.
- **PR #A** is a behavior change for any caller that relied on the global-deactivation side effect. The training path is the only documented caller; ad-hoc manual scripts (if any) need to know the new contract.
