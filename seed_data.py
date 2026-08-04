"""Seed script for initializing Digital Organization Runtime (DOR) database with demo data."""

import logging
from infrastructure.database.base import engine, Base, SessionLocal
from domain.models import (
    OrganizationModel, DepartmentModel, ActorModel, RoleDefinitionModel,
    CapabilityModel, PolicyModel, WorkflowTemplateModel
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dor.seed")

def seed():
    logger.info("Initializing database schema...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # 1. Organization
        org = db.query(OrganizationModel).filter_by(name="EIRA Tech Org").first()
        if not org:
            org = OrganizationModel(
                name="EIRA Tech Org",
                domain="software-engineering",
                mission="Autonomous AI-driven Digital Organization Runtime"
            )
            db.add(org)
            db.commit()
            db.refresh(org)
            logger.info(f"Created Organization: {org.name} ({org.id})")

        # 2. Department
        dept = db.query(DepartmentModel).filter_by(name="Core Engineering").first()
        if not dept:
            dept = DepartmentModel(
                organization_id=org.id,
                name="Core Engineering",
                purpose="Builds and maintains core DOR services"
            )
            db.add(dept)
            db.commit()
            db.refresh(dept)
            logger.info(f"Created Department: {dept.name} ({dept.id})")

        # 3. Roles
        dev_role = db.query(RoleDefinitionModel).filter_by(title="Senior AI Engineer").first()
        if not dev_role:
            dev_role = RoleDefinitionModel(
                organization_id=org.id,
                title="Senior AI Engineer",
                description="Generates, audits, and executes software features",
                responsibilities=["Code Generation", "Refactoring", "Testing"]
            )
            db.add(dev_role)

        rev_role = db.query(RoleDefinitionModel).filter_by(title="Code Reviewer").first()
        if not rev_role:
            rev_role = RoleDefinitionModel(
                organization_id=org.id,
                title="Code Reviewer",
                description="Audits and approves pull requests and security gates",
                responsibilities=["Code Review", "Security Auditing"]
            )
            db.add(rev_role)

        db.commit()

        # 4. Capabilities
        cap = db.query(CapabilityModel).filter_by(name="code_generation").first()
        if not cap:
            cap = CapabilityModel(
                organization_id=org.id,
                name="code_generation",
                description="Ability to generate Python and FastAPI code",
                category="engineering"
            )
            db.add(cap)
            db.commit()

        # 5. Actors
        actor1 = db.query(ActorModel).filter_by(name="EIRA AI Developer").first()
        if not actor1:
            actor1 = ActorModel(
                organization_id=org.id,
                name="EIRA AI Developer",
                actor_type="digital_employee",
                status="active"
            )
            db.add(actor1)

        actor2 = db.query(ActorModel).filter_by(name="Human Supervisor").first()
        if not actor2:
            actor2 = ActorModel(
                organization_id=org.id,
                name="Human Supervisor",
                actor_type="human",
                status="active"
            )
            db.add(actor2)

        db.commit()

        # 6. Default Feature Workflow Template
        tmpl = db.query(WorkflowTemplateModel).filter_by(name="Feature Development").first()
        if not tmpl:
            tmpl = WorkflowTemplateModel(
                organization_id=org.id,
                name="Feature Development",
                version="1.0.0",
                definition={
                    "states": ["CREATED", "IN_PROGRESS", "REVIEW", "APPROVED", "COMPLETED"],
                    "transitions": [
                        {"from_state": "CREATED", "to_state": "IN_PROGRESS", "condition": "len(intent_id) > 0"},
                        {"from_state": "IN_PROGRESS", "to_state": "REVIEW", "condition": "artifact_created == True"},
                        {"from_state": "REVIEW", "to_state": "APPROVED", "condition": "score > 80"},
                        {"from_state": "APPROVED", "to_state": "COMPLETED", "condition": "status == 'approved'"}
                    ]
                }
            )
            db.add(tmpl)
            db.commit()

        logger.info("Database seeding completed successfully!")

    except Exception as e:
        logger.error(f"Error during seeding: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed()
