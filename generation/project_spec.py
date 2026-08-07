"""Domain contract for generated project definitions."""

from enum import StrEnum
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ArchitectureKind(StrEnum):
    """Architectures supported by the first scaffold profile."""

    HEXAGONAL = "hexagonal"


class ProjectDefinition(BaseModel):
    """Immutable-ish input contract for deterministic project scaffolding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=80)
    architecture: ArchitectureKind
    language: str = "python"
    api: str = "fastapi"
    database: str = "postgresql"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", value):
            raise ValueError("project name must be lowercase and start with a letter")
        return value

    @field_validator("language", "api", "database")
    @classmethod
    def normalize_values(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("language")
    @classmethod
    def supported_language(cls, value: str) -> str:
        if value != "python":
            raise ValueError("P3-15 currently supports only python")
        return value

    @field_validator("api")
    @classmethod
    def supported_api(cls, value: str) -> str:
        if value != "fastapi":
            raise ValueError("P3-15 currently supports only fastapi")
        return value

    @field_validator("database")
    @classmethod
    def supported_database(cls, value: str) -> str:
        if value != "postgresql":
            raise ValueError("P3-15 currently supports only postgresql")
        return value
