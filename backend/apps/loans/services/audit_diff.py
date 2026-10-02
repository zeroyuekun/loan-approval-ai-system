"""Field-level change details for AuditLog rows on staff edits (API and admin)."""


def _audit_value(value):
    """JSON-safe rendering of a model value for AuditLog details."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def snapshot(instance):
    return {f.attname: getattr(instance, f.attname) for f in instance._meta.concrete_fields}


def field_change_details(before, instance, *, values_for=None, names_only=()):
    """AuditLog details for a staff edit: every changed field by name, plus
    before/after values (all changed fields, or only ``values_for``). Fields
    in ``names_only`` (free text) never have their values recorded."""
    changed = [name for name, old in before.items() if name != "updated_at" and getattr(instance, name) != old]
    details = {"changed_fields": sorted(n.removesuffix("_id") for n in changed)}
    for name in changed:
        if name in names_only or (values_for is not None and name not in values_for):
            continue
        details[name.removesuffix("_id")] = {
            "from": _audit_value(before[name]),
            "to": _audit_value(getattr(instance, name)),
        }
    return details
