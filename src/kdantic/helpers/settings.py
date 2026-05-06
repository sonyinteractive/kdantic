from pathlib import Path

import os
from typing import Literal
from functools import cache

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
    CliMutuallyExclusiveGroup,
    CliImplicitFlag,
    TomlConfigSettingsSource,
    YamlConfigSettingsSource,
    PydanticBaseSettingsSource,
    CliSettingsSource,
)
from pydantic import Field, field_validator

from kdantic.helpers.shared import _normalize_short_names


class Mode(CliMutuallyExclusiveGroup):
    path: str | None = Field(
        description="Path to a Python file or directory containing Pydantic models (e.g., ./acme/models)",
        default=None,
    )
    import_name: str | None = Field(
        description="Import name understood by Python containing Pydantic models to scan (e.g., 'acme.models')",
        default=None,
    )


class Verbosity(CliMutuallyExclusiveGroup):
    quiet: CliImplicitFlag[bool] | None = Field(
        default=False, description="Suppress non-error output"
    )
    verbose: CliImplicitFlag[bool] | None = Field(
        default=False, description="Enable verbose output"
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KDANTIC",
        case_sensitive=False,
        cli_parse_args=True,
        cli_enforce_required=False,
        cli_kebab_case=True,
        cli_exit_on_error=True,
        cli_prog_name="kdantic",
        cli_hide_none_type=True,
        toml_file=["kdantic.toml", "/etc/kdantic.toml"],
        yaml_file=["kdantic.yaml", "/etc/kdantic.yaml"],
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            env_settings,
            dotenv_settings,
            CliSettingsSource(settings_cls),
            TomlConfigSettingsSource(settings_cls),
            YamlConfigSettingsSource(settings_cls),
            init_settings,
            file_secret_settings,
        )

    mode: Mode = Field(description="operation mode (one of)", default_factory=Mode)
    verbosity: Verbosity = Field(
        description="verbosity level (one of)", default_factory=Verbosity
    )

    project_root: Path = Field(
        default_factory=lambda: os.getcwd(),
        description="Repo/project root to prepend to sys.path so --models is importable",
    )
    model_name: str | None = Field(
        default=None,
        description="only generate CRDs for the specific model class given",
    )

    default_group: str = Field(
        default="example.com", description="Default CRD group to use"
    )
    default_version: str = Field(default="v1", description="Default CRD version to use")
    default_scope: Literal["Namespaced", "Cluster"] = Field(
        default="Namespaced", description="Default CRD scope to use"
    )
    default_singular: str | None = Field(
        default=None, description="Default CRD singular to use in spec.names"
    )
    default_plural: str | None = Field(
        default=None, description="Default CRD plural to use in spec.names"
    )
    default_short_names: list[str] | None = Field(
        default=None, description="Default CRD short names to use in spec.names"
    )

    crd_kind: str = Field(default="CustomResourceDefinition")
    crd_version: str = Field(default="apiextensions.k8s.io/v1")
    crd_identity_fields: set = Field(default_factory=lambda: {"kind", "apiVersion"})

    output_directory: Path = Field(
        default_factory=lambda: Path("."),
        description="Output directory for generated CRD files",
    )
    output_overwrite: CliImplicitFlag[bool] = Field(
        default=False, description="Overwrite existing CRD files"
    )

    helm: str | None = Field(
        default=None,
        description="when set to a string value, generate templates suitable for a Helm chart under the "
        "given name (e.g., 'mychart')",
    )

    @field_validator("default_short_names", mode="after")
    @classmethod
    def normalize_short_names(cls, short_names: list[str]) -> list[str]:
        if short_names:
            return _normalize_short_names(short_names)
        return short_names


@cache
def load_settings() -> Settings:
    return Settings()


class _SettingsProxy:
    """
    Lazy, importable proxy. Accessing any attribute forces construction.
    """

    __slots__ = ()

    def __getattr__(self, name: str):
        return getattr(load_settings(), name)

    def __repr__(self) -> str:
        return repr(load_settings())


def init_settings() -> Settings:
    return load_settings()


kdantic_settings: Settings = _SettingsProxy()
