#!/usr/bin/env python3
"""Policy checks for the rendered k8s manifests that a schema check cannot see.

kubeconform proves each object is schema-valid; it cannot tell that the API
server will reject an Ingress, that the kubelet will refuse a pod, or that a
NetworkPolicy blocks the only route to the backend. Each check below pins one
of those failure modes.

Placeholder credentials are checked separately by
scripts/check-k8s-placeholders.sh.

Usage:
    kubectl kustomize k8s | python scripts/check_k8s_policy.py k8s
Requires PyYAML. Exits 1 and lists every violation when any check fails.
"""

from __future__ import annotations

import pathlib
import re
import sys

import yaml

# Objects the manifests reference but deliberately do not ship (created by the
# operator or by a controller). Anything else referenced must be rendered.
EXTERNAL_SECRETS = {"loan-approval-secrets", "loan-approval-tls"}
INGRESS_CONTROLLER_NAMESPACE = "ingress-nginx"
# Queues that Celery tasks are routed to (backend/config/celery.py task_routes)
# plus Celery's default queue, which receives every unrouted task
# (apps.loans.tasks.* -- data retention and the dispatch outbox).
REQUIRED_QUEUES = {"ml", "email", "agents", "celery"}
# ingress-nginx annotations this repo uses; a typo or an invented key is
# silently ignored by the controller, so only known keys are allowed.
KNOWN_NGINX_ANNOTATIONS = {
    "limit-rps",
    "limit-rpm",
    "limit-connections",
    "limit-burst-multiplier",
    "proxy-body-size",
    "ssl-redirect",
    "force-ssl-redirect",
    "proxy-read-timeout",
    "proxy-send-timeout",
}
POSTGRES_SERVER_MAJOR = 17  # RDS (terraform/rds.tf) and compose both run 17

WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}


def pod_spec(obj):
    if obj["kind"] == "CronJob":
        return obj["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    return obj["spec"]["template"]["spec"]


def pod_labels(obj):
    if obj["kind"] == "CronJob":
        return obj["spec"]["jobTemplate"]["spec"]["template"]["metadata"].get("labels", {})
    return obj["spec"]["template"]["metadata"].get("labels", {})


def name(obj):
    return f"{obj['kind']}/{obj['metadata']['name']}"


def selector_matches(match_labels, labels):
    return all(labels.get(k) == v for k, v in (match_labels or {}).items())


def check_ingress(objs, errors):
    for ing in (o for o in objs if o["kind"] == "Ingress"):
        ann = ing["metadata"].get("annotations", {}) or {}
        if ing["spec"].get("ingressClassName") and "kubernetes.io/ingress.class" in ann:
            errors.append(
                f"{name(ing)}: sets both spec.ingressClassName and the kubernetes.io/ingress.class "
                "annotation; the API server rejects this on create"
            )
        for key in ann:
            if key.startswith("nginx.ingress.kubernetes.io/"):
                short = key.split("/", 1)[1]
                if short not in KNOWN_NGINX_ANNOTATIONS:
                    errors.append(f"{name(ing)}: unknown ingress-nginx annotation {key} (ignored by the controller)")


def ingress_backend_services(objs):
    for ing in (o for o in objs if o["kind"] == "Ingress"):
        for rule in ing["spec"].get("rules", []):
            for path in rule.get("http", {}).get("paths", []):
                svc = path["backend"]["service"]
                yield ing, svc["name"], svc["port"]["number"]


def check_ingress_reachability(objs, errors):
    services = {o["metadata"]["name"]: o for o in objs if o["kind"] == "Service"}
    policies = [o for o in objs if o["kind"] == "NetworkPolicy"]
    for ing, svc_name, port in ingress_backend_services(objs):
        svc = services.get(svc_name)
        if svc is None:
            errors.append(f"{name(ing)}: routes to missing Service {svc_name}")
            continue
        target_port = next(
            (p.get("targetPort", p["port"]) for p in svc["spec"]["ports"] if p["port"] == port),
            None,
        )
        selector = svc["spec"].get("selector", {})
        allowed = False
        for pol in policies:
            if "Ingress" not in pol["spec"].get("policyTypes", ["Ingress"]):
                continue
            # The policy must select the service's pods.
            if not selector_matches(pol["spec"]["podSelector"].get("matchLabels"), selector):
                continue
            for rule in pol["spec"].get("ingress", []) or []:
                ports = [p.get("port") for p in rule.get("ports", [])] or [target_port]
                if target_port not in ports:
                    continue
                peers = rule.get("from")
                if not peers:  # empty from = all sources
                    allowed = True
                for peer in peers or []:
                    ns = (peer.get("namespaceSelector") or {}).get("matchLabels", {})
                    if ns.get("kubernetes.io/metadata.name") == INGRESS_CONTROLLER_NAMESPACE:
                        allowed = True
        if not allowed:
            errors.append(
                f"{name(ing)} -> Service/{svc_name}:{port}: no NetworkPolicy admits traffic from the "
                f"{INGRESS_CONTROLLER_NAMESPACE} namespace on port {target_port}; default-deny drops it"
            )


def check_pod_security(objs, errors):
    for obj in (o for o in objs if o["kind"] in WORKLOAD_KINDS):
        spec = pod_spec(obj)
        if obj["kind"] == "Job" and obj["metadata"].get("ownerReferences"):
            continue
        psc = spec.get("securityContext", {}) or {}
        if spec.get("automountServiceAccountToken") is not False:
            errors.append(f"{name(obj)}: automountServiceAccountToken must be false (no pod needs the API)")
        for c in spec.get("initContainers", []) + spec.get("containers", []):
            csc = c.get("securityContext", {}) or {}
            where = f"{name(obj)} container {c['name']}"
            if psc.get("runAsNonRoot") or csc.get("runAsNonRoot"):
                uid = csc.get("runAsUser", psc.get("runAsUser"))
                if not isinstance(uid, int):
                    errors.append(
                        f"{where}: runAsNonRoot without a numeric runAsUser; the kubelet refuses images "
                        "whose USER is a name (CreateContainerConfigError)"
                    )
            else:
                errors.append(f"{where}: runAsNonRoot is not set")
            if csc.get("allowPrivilegeEscalation") is not False:
                errors.append(f"{where}: allowPrivilegeEscalation must be false")
            if "ALL" not in ((csc.get("capabilities") or {}).get("drop") or []):
                errors.append(f"{where}: capabilities.drop must include ALL")
            seccomp = (csc.get("seccompProfile") or psc.get("seccompProfile") or {}).get("type")
            if seccomp != "RuntimeDefault":
                errors.append(f"{where}: seccompProfile.type must be RuntimeDefault")
            if csc.get("readOnlyRootFilesystem") is not True:
                errors.append(f"{where}: readOnlyRootFilesystem must be true (mount an emptyDir for scratch)")


def check_references(objs, errors):
    rendered = {(o["kind"], o["metadata"]["name"]) for o in objs}
    for obj in (o for o in objs if o["kind"] in WORKLOAD_KINDS):
        spec = pod_spec(obj)
        for vol in spec.get("volumes", []) or []:
            if "configMap" in vol and ("ConfigMap", vol["configMap"]["name"]) not in rendered:
                errors.append(f"{name(obj)}: volume {vol['name']} references missing ConfigMap {vol['configMap']['name']}")
            pvc = vol.get("persistentVolumeClaim")
            if pvc and ("PersistentVolumeClaim", pvc["claimName"]) not in rendered:
                errors.append(f"{name(obj)}: volume {vol['name']} references missing PVC {pvc['claimName']}")
            sec = vol.get("secret")
            if sec and sec["secretName"] not in EXTERNAL_SECRETS and ("Secret", sec["secretName"]) not in rendered:
                errors.append(f"{name(obj)}: volume {vol['name']} references unknown Secret {sec['secretName']}")
        for c in spec.get("initContainers", []) + spec.get("containers", []):
            for src in c.get("envFrom", []) or []:
                if "configMapRef" in src and ("ConfigMap", src["configMapRef"]["name"]) not in rendered:
                    errors.append(f"{name(obj)}: envFrom references missing ConfigMap {src['configMapRef']['name']}")


def check_part_of_label(objs, errors):
    # The egress allow-rules select app.kubernetes.io/part-of=aussieloanai; a pod
    # without it is caught only by default-deny and cannot reach Postgres/Redis.
    for obj in (o for o in objs if o["kind"] in WORKLOAD_KINDS):
        if pod_labels(obj).get("app.kubernetes.io/part-of") != "aussieloanai":
            errors.append(f"{name(obj)}: pod template lacks app.kubernetes.io/part-of=aussieloanai (egress denied)")


def worker_queues(container):
    args = (container.get("command") or []) + (container.get("args") or [])
    if "worker" not in args:
        return None
    for i, arg in enumerate(args):
        if arg in ("-Q", "--queues") and i + 1 < len(args):
            return set(args[i + 1].split(","))
        if arg.startswith("--queues="):
            return set(arg.split("=", 1)[1].split(","))
    return {"celery"}


def check_celery_queues(objs, errors):
    consumed = set()
    for obj in (o for o in objs if o["kind"] == "Deployment"):
        for c in pod_spec(obj)["containers"]:
            queues = worker_queues(c)
            if queues is None:
                continue
            unknown = queues - REQUIRED_QUEUES
            if unknown:
                errors.append(f"{name(obj)}: consumes queues no task is routed to: {sorted(unknown)}")
            consumed |= queues
    missing = REQUIRED_QUEUES - consumed
    if missing:
        errors.append(f"no Celery worker consumes {sorted(missing)}; tasks routed there never run")


def check_migrations(objs, errors):
    def runs_migrate(c):
        return "migrate" in " ".join((c.get("command") or []) + (c.get("args") or []))

    for obj in (o for o in objs if o["kind"] in WORKLOAD_KINDS):
        spec = pod_spec(obj)
        if any(runs_migrate(c) for c in spec.get("initContainers", []) + spec.get("containers", [])):
            return
    errors.append("nothing runs `manage.py migrate` (no Job or initContainer); a fresh cluster has no tables")


def check_backup_image(objs, errors):
    for obj in (o for o in objs if o["kind"] == "CronJob"):
        for c in pod_spec(obj)["containers"]:
            m = re.match(r"postgres:(\d+)", c.get("image", ""))
            if m and int(m.group(1)) < POSTGRES_SERVER_MAJOR:
                errors.append(
                    f"{name(obj)}: {c['image']} ships pg_dump {m.group(1)}, which refuses to dump a "
                    f"PostgreSQL {POSTGRES_SERVER_MAJOR} server"
                )


CHECKS = [
    check_ingress,
    check_ingress_reachability,
    check_pod_security,
    check_references,
    check_part_of_label,
    check_celery_queues,
    check_migrations,
    check_backup_image,
]


def check_orphans(k8s_dir, errors):
    """Every manifest in the directory must be listed in kustomization.yaml.

    An unlisted file is never applied by `kubectl apply -k`, so whatever it
    promises (a backup CronJob, say) silently does not exist.
    """
    root = pathlib.Path(k8s_dir)
    kust = yaml.safe_load((root / "kustomization.yaml").read_text())
    listed = {(root / r).resolve() for r in kust.get("resources", [])}
    for f in sorted(root.rglob("*.yaml")):
        if f.name == "kustomization.yaml" or f.resolve() in listed:
            continue
        errors.append(f"{f.as_posix()}: not listed in kustomization.yaml resources, so it is never applied")


def main() -> int:
    objs = [o for o in yaml.safe_load_all(sys.stdin) if o]
    if not objs:
        print("check_k8s_policy: no objects on stdin (did kustomize fail?)", file=sys.stderr)
        return 1
    errors: list[str] = []
    for check in CHECKS:
        check(objs, errors)
    if len(sys.argv) > 1:
        check_orphans(sys.argv[1], errors)
    if errors:
        print(f"k8s policy: {len(errors)} violation(s) in {len(objs)} objects")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"k8s policy: OK ({len(objs)} objects, {len(CHECKS)} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
