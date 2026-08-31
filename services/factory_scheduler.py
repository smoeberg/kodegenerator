"""Publish ready factory packages through the canonical DatabaseQueue."""

from domain.factory_work import WorkPackage, WorkPackageStatus
from infrastructure.runtime.queue import DatabaseQueue


class FactoryScheduler:
    TOPIC = "factory.work"

    def __init__(self, queue: DatabaseQueue) -> None:
        self._queue = queue

    def publish(self, package: WorkPackage) -> str:
        if package.organization_id != self._queue.organization_id:
            raise ValueError("queue and package organizations do not match")
        if package.status is not WorkPackageStatus.READY:
            raise ValueError("only ready work packages may be published")
        return self._queue.publish(
            self.TOPIC,
            {
                "organization_id": package.organization_id,
                "work_package_id": package.work_package_id,
                "fingerprint": package.content_fingerprint,
            },
            message_id=f"factory:{package.work_package_id}",
        )
