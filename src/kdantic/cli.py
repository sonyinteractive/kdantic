import logging
import sys

from pydantic import BaseModel
from rich.logging import RichHandler

from kdantic.helpers.annotations import CRDMetaData, build_crd_meta
from kdantic.helpers.dotted_file import (
    load_models_from_any_path,
    load_models_from_module,
)
from kdantic.helpers.schema import HELM_SENTINEL, build_k8s_model_schema, write_crd
from kdantic.helpers.settings import init_settings, kdantic_settings
from kdantic.helpers.shared import (
    _strip_optional,
    get_field_annotation,
    get_model_fields_map,
)

log = logging.getLogger("kdantic")


def _make_version_block(
    meta: CRDMetaData,
    spec_model: type[BaseModel] | None,
    status_model: type[BaseModel] | None,
    custom_formats: dict,
) -> dict:
    """Build the CRD versions[0] block including schema and optional CEL rules."""
    properties: dict = {}
    if spec_model:
        properties["spec"] = build_k8s_model_schema(spec_model, custom_formats)
    if status_model:
        properties["status"] = build_k8s_model_schema(status_model, custom_formats)

    version_block = {
        "name": meta.version,
        "served": True,
        "storage": True,
        "schema": {"openAPIV3Schema": {"type": "object", "properties": properties}},
    }
    if meta.cel_rules:
        log.info(":heavy_check_mark: Model has CEL rules - adding to the CRD")
        version_block["schema"]["openAPIV3Schema"]["x-kubernetes-validations"] = meta.cel_rules
    if status_model:
        version_block["subresources"] = {"status": {}}
    return version_block


def build_crd_object(meta: CRDMetaData, version_block: dict) -> dict:
    """Assemble the top-level CRD manifest dict from resolved metadata."""
    data = {
        "apiVersion": kdantic_settings.crd_version,
        "kind": kdantic_settings.crd_kind,
        "metadata": {"name": f"{meta.names.plural}.{meta.group}"},
        "spec": {
            "group": meta.group,
            "names": {
                "kind": meta.names.kind,
                "plural": meta.names.plural,
                "singular": meta.names.singular,
                "shortNames": meta.names.shortNames,
            },
            "scope": meta.scope,
            "versions": [version_block],
        },
    }
    if kdantic_settings.helm:
        data["metadata"]["labels"] = HELM_SENTINEL
    return data


def generate_crds(custom_formats: dict) -> None:
    """
    Generate CRD YAML files for all discovered Pydantic models.

    Precedence: explicit CLI flags > annotations > dunder metadata > settings defaults
    """
    if kdantic_settings.mode.import_name:
        models = load_models_from_module(
            kdantic_settings.mode.import_name,
            filter_name=kdantic_settings.model_name,
            project_root=kdantic_settings.project_root,
        )
    else:
        models = load_models_from_any_path(
            kdantic_settings.mode.path,
            filter_name=kdantic_settings.model_name,
        )

    for model_name, model_cls in models.items():
        if not (isinstance(model_cls, type) and issubclass(model_cls, BaseModel)):
            log.warning(f":warning: {model_name}: not a subclass of BaseModel — skipping.")
            continue

        model_fields_map = get_model_fields_map(model_cls)
        if "spec" not in model_fields_map:
            log.warning(f":warning: {model_name}: missing required 'spec' field — skipping.")
            continue

        meta = build_crd_meta(model_cls)
        spec_type = get_field_annotation(model_fields_map["spec"])
        status_type = None
        if "status" in model_fields_map:
            status_type = _strip_optional(get_field_annotation(model_fields_map["status"]))

        try:
            version_block = _make_version_block(
                meta,
                spec_type,
                status_type,
                custom_formats,
            )
            crd_obj = build_crd_object(meta, version_block)
            out_path = kdantic_settings.output_directory / f"{meta.names.plural}.{meta.group}.yaml"
            write_crd(out_path, crd_obj, overwrite=kdantic_settings.output_overwrite)
            log.info(f":heavy_check_mark: Generated CRD for {meta.names.kind} -> {out_path}")
        except Exception as gen_err:
            log.warning(f"[red]:warning: Failed to generate CRD for {model_name}[/red]: {gen_err}")


def main() -> None:
    """Entry point: configure logging, validate args, then generate CRDs."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False)],
    )
    init_settings()
    if not kdantic_settings.mode.path and not kdantic_settings.mode.import_name:
        log.error(
            "[red]Error:[/] one of [bold]--path[/] or [bold]--import-name[/] is required.\n"
            "  [dim]--path PATH[/]                path to a Python file or directory containing Pydantic models\n"
            "  [dim]--import-name IMPORT_NAME[/]  Python import name to scan (e.g., 'acme.models')\n"
            "Run [bold]kdantic --help[/] for full usage."
        )
        sys.exit(1)
    log.info("[bold cyan]kdantic Configuration:[/]")
    for setting, value in kdantic_settings.model_dump().items():
        log.info(f"[dim]\t[/][green]{setting}[/]: {value}")
    if kdantic_settings.verbosity.quiet:
        logging.getLogger("kdantic").setLevel(logging.WARNING)
    if kdantic_settings.verbosity.verbose:
        logging.getLogger("kdantic").setLevel(logging.DEBUG)
    generate_crds({})


if __name__ == "__main__":
    main()