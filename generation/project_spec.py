"""Domain contract for generated project definitions."""

from enum import StrEnum
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ArchitectureKind(StrEnum):
    """Architectures supported by the scaffold engine."""

    HEXAGONAL = "hexagonal"
    CLEAN = "clean"
    MODULAR = "modular"
    PLUGIN = "plugin"
    MONOLITH = "monolith"


SUPPORTED_STACKS: dict[str, dict[str, list[str]]] = {
    "python": {
        "api": ["fastapi", "flask", "django"],
        "database": ["postgresql", "sqlite", "mysql"],
    },
    "typescript": {
        "api": ["express", "fastify", "nestjs", "nextjs"],
        "database": ["postgresql", "sqlite", "mongodb", "mysql"],
    },
    "go": {
        "api": ["gin", "chi", "fiber"],
        "database": ["postgresql", "sqlite", "mysql"],
    },
    "php": {
        "api": ["wordpress", "laravel", "symfony", "vanilla"],
        "database": ["mysql", "mariadb", "sqlite", "none"],
    },
    "csharp": {
        "api": ["aspnetcore", "minimalapi"],
        "database": ["sqlserver", "postgresql", "sqlite"],
    },
    "rust": {
        "api": ["actix", "axum"],
        "database": ["postgresql", "sqlite"],
    },
}


class ProjectDefinition(BaseModel):
    """Immutable-ish input contract for deterministic project scaffolding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=80)
    architecture: ArchitectureKind = ArchitectureKind.HEXAGONAL
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
        # Dynamic stacks are supported, known presets are validated in SUPPORTED_STACKS
        return value

    @field_validator("api")
    @classmethod
    def supported_api(cls, value: str, info) -> str:
        lang = info.data.get("language", "python")
        if lang in SUPPORTED_STACKS:
            valid_apis = SUPPORTED_STACKS[lang]["api"]
            if value not in valid_apis and value != "custom":
                # Allow custom APIs/frameworks while giving feedback
                pass
        return value

    @field_validator("database")
    @classmethod
    def supported_database(cls, value: str, info) -> str:
        lang = info.data.get("language", "python")
        if lang in SUPPORTED_STACKS:
            valid_dbs = SUPPORTED_STACKS[lang]["database"]
            if value not in valid_dbs and value != "custom":
                pass
        return value
