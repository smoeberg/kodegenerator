"""Compatibility entrypoint delegating to the canonical worker CLI."""

import os
import socket
import sys

from cli.worker import main
from infrastructure.runtime.db import build_session_factory
from services.worker_identity import WorkerIdentityStore, WorkerPrincipal

__all__ = ["run"]


def run(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    verifier = None
    if not args:
        if os.environ.get("DOR_QUEUE_BACKEND", "local").lower() == "database":
            principal, verifier = _authenticated_principal()
            capabilities = ",".join(principal.capabilities)
            worker_id = principal.worker_id
        else:
            capabilities = os.environ.get("DOR_WORKER_CAPABILITIES", "").strip()
            worker_id = (
                os.environ.get("DOR_WORKER_ID", "").strip() or socket.gethostname()
            )
        if not capabilities:
            raise RuntimeError("worker capabilities must be configured")
        args = [
            "--id",
            worker_id,
            "--caps",
            capabilities,
        ]
        if os.environ.get("DOR_QUEUE_BACKEND", "local").lower() == "database":
            args.append("--pipeline")
    return main(args, identity_verifier=verifier)


def _authenticated_principal():
    database_url = os.environ.get("DATABASE_URL")
    organization_id = os.environ.get("DOR_WORKER_ORGANIZATION_ID", "")
    service_id = os.environ.get("DOR_WORKER_SERVICE_ID", "")
    credential = os.environ.get("DOR_WORKER_CREDENTIAL", "")
    instance_id = os.environ.get("DOR_WORKER_INSTANCE_ID") or socket.gethostname()
    if not all((database_url, organization_id, service_id, credential)):
        raise RuntimeError(
            "database workers require DATABASE_URL, DOR_WORKER_ORGANIZATION_ID, "
            "DOR_WORKER_SERVICE_ID and DOR_WORKER_CREDENTIAL"
        )
    store = WorkerIdentityStore(build_session_factory(database_url))

    def authenticate() -> WorkerPrincipal:
        return store.authenticate(
            organization_id=organization_id,
            service_id=service_id,
            instance_id=instance_id,
            credential=credential,
        )

    principal = authenticate()
    return principal, lambda: authenticate().worker_id


if __name__ == "__main__":
    sys.exit(run())
