# kdantic — Pydantic → Kubernetes CRD Generator (annotations-first)

Generate Kubernetes **CustomResourceDefinition (CRD)** manifests from Pydantic models with **annotations-first** derivation, **explicit CLI overrides**, optional **CLI CRD_CONFIG file fallback**, and **dunder fallbacks** only when annotations are absent.

Works with **Pydantic v1 and v2**. Produces clean, Helm- and `kubectl`-compatible YAML.

---

## 🔑 Precedence model   

```
Annotations  >  __crd_meta__ (structured metadata)  >  Settings (configuration file or CLI)  >  Derivations (class 
name, pluralize, etc.)
```

- **Annotations**: `apiVersion`, `kind`, presence of `namespace` (root or `metadata`)
- **Structured dunder metadata**: a single optional `__crd_meta__` object implementing the CRDMetaProtocol (see below)
- **Settings defaults**: `--default-group --default-version --default-scope --default-singular --default-plural 
--default-short-names` (may also be provided via configuration file)
- **Derivations**: fallback kind from class name; singular from kind; plural from singular; short name from kind

(Former per-field dunder attributes and external CRD config file support were removed in favor of one validated object.)

---

## ✨ Features

- Works with Pydantic v1 and v2
- Annotations-first resolution (`apiVersion`, `kind`, scope via `namespace`)
- Single, Protocol‑validated `__crd_meta__` object (PEP 544) for optional overrides
- Deterministic fallback to settings defaults
- Kind derived from class name when absent
- Optional fields are marked `nullable: true` (no `anyOf`)
- CRDs are compatible with Helm and Kubernetes controllers
- Configurable CRD boilerplate and OpenAPI formats via YAML config file
- Derives **group/version** from `apiVersion: Literal["foo.bar/v1"]` (or default/Enum `.value`)
- Derives **kind** from `kind: Literal["Widget"]` (or default/Enum or class name)
- Infers **scope** as `Namespaced` if a `namespace` field exists on the root or on `metadata`, else `Cluster`
- `Optional[...]` and `T | None` become `nullable: true` (no `anyOf: null`)
- Supports `Literal[...]` string enums and `enum.Enum` / `StrEnum`
- Supports `list[T]` and `dict[str, T]` / `Mapping[str, T]` → `items` / `additionalProperties`
- Inlined schemas (no `$ref`)
- Optional fields -> `nullable: true` (no `anyOf`)
- Enum / Literal support
- `enum.StrEnum` polyfill for Python < 3.11
- Quiet mode to reduce noise

---

## 🚀 Usage

### From a filesystem path

```bash
python kdantic.py   --model-path ./examples/models.py   --output-dir ./crds   --overwrite-files
```

### From a dotted module path (preferred for packages)

```bash
python kdantic.py   --models examples.models   --project-root .   --output-dir ./crds
```

### Runtime overrides (highest precedence)

```bash
# Force group and scope across all models
python kdantic.py . --output-dir ./crds --group platform.foo.bar --scope Cluster

# Provide a version when models lack apiVersion
python kdantic.py . --output-dir ./crds --version v1alpha1

# Adjust names
python kdantic.py . --output-dir ./crds --plural widgets --singular widget --short-names wdg

# Provide fallback config file (used only where annotations are absent)
python kdantic.py . --output-dir ./crds --crd-config ./examples/crd_config.yaml
```

Use `--model-name` to target a single class.

---

## 🧩 Model example

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

class ObjectMeta(BaseModel):
    name: str
    namespace: Optional[str] = None  # presence => Namespaced

class K8sWidgetModel(BaseModel):
    apiVersion: Literal["foo.bar/v1"]
    kind: Literal["Widget"]
    metadata: ObjectMeta
    spec: dict = Field(default_factory=dict)
```

---

## ⚙️ CLI options

| Flag                    | Description |
|-------------------------|-------------|
| `--mode.path`           | Path to a `.py` file or directory of Pydantic models |
| `--mode.import-name`    | Dotted import path to a module/package of models |
| `--project-root`        | Repo root added to `sys.path` for imports |
| `--model-name`          | Only generate CRD for a specific model class |
| `--default-group`       | Fallback group when not resolvable from annotations or `__crd_meta__` |
| `--default-version`     | Fallback version |
| `--default-scope`       | Fallback scope (`Namespaced` or `Cluster`) |
| `--default-singular`    | Fallback singular name |
| `--default-plural`      | Fallback plural name |
| `--default-short-names` | Fallback comma/space separated short names |
| `--crd-kind`            | CRD object kind (normally `CustomResourceDefinition`) |
| `--crd-version`         | CRD API version (default `apiextensions.k8s.io/v1`) |
| `--output-directory`    | Directory for generated CRD YAML files |
| `--output-overwrite`    | Overwrite existing files |
| `--quiet`               | Suppress non-error logs |
| `--helm`                | Helm mode: emits CRDs suitable for inclusion in a chart) |


---

## 📝 Structured metadata (`__crd_meta__`)

```python
class Meta(BaseModel):
    group: str | None = "example.com" # can be omitted; inferred from 'apiVersion'
    version: str | None = "v1" # can be omitted; inferred from 'apiVersion'
    scope: str | None = "Namespaced" # can be omitted; inferred from presence of 'namespace' field
    kind: str | None = None          # can be set to None; derived from class name
    singular: str | None = None      # derives from kind by default
    plural: str | None = None        # derives from singular by default
    shortNames: list[str] | None = None  # derives from kind by default

class Thing(BaseModel):
    apiVersion: Literal["example.com/v1"]
    kind: Literal["Thing"]
    namespace: str
    __crd_meta__ = Meta()
```

Validation:
- Shape checked against a `CRDMetaProtocol` (PEP 544 `runtime_checkable`)
- Wrong attribute names or types → warning; metadata ignored

## Helm Compatibility

When `--helm` is enabled, it generates a Helm-compatible CRD manifest with the necessary boilerplate,
including Helm template directives for dynamic naming and versioning and tracking. This ensures that the generated CRDs
can be seamlessly integrated into existing Helm charts.

As an argument to the command switch, pass the name of your chart.

You can omit `--helm` for plain `kubectl apply -f` style generation.
