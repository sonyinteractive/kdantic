from typing import Literal, Optional, Annotated
from pydantic import BaseModel, Field
from pydantic.networks import IPvAnyAddress
from enum import Enum


# Standard Kubernetes metadata
class ObjectMeta(BaseModel):
    name: str
    namespace: Optional[str] = None  # if present => scope = Namespaced


class WidgetSpec(BaseModel):
    # simple typed fields
    replicas: int = Field(default=1, ge=0, description="Arnos widgets")
    enabled: bool = Field(default=True, description="Arnos feature")

    # string with an explicit OpenAPI format (purely for docs/UX in CRD)
    # You can remove json_schema_extra if you don't care about CRD 'format'
    service_ip: Annotated[
        IPvAnyAddress,
        Field(description="Service IP", json_schema_extra={"format": "ipvanynetwork"}),
    ] = "0.0.0.0"

    # array and map examples
    labels: dict[str, str] = Field(default_factory=dict)
    endpoints: list[str] = Field(default_factory=list)


# Your custom resource definition
class K8sWidgetModel(BaseModel):
    apiVersion: Literal["foo.bar.foobar/v1"]
    kind: Literal["Widget"]

    metadata: ObjectMeta

    # Resource spec
    spec: dict = Field(
        default_factory=dict,
        description="Desired state of the Widget",
    )

    # Optional status enables CRD subresource: status
    status: Optional[dict] = Field(
        default=None,
        description="Observed state of the Widget",
    )


class NamespacedMeta(BaseModel):
    # Having "namespace" present => kdantic infers scope = Namespaced
    name: str
    namespace: Optional[str] = None


class ClusterMeta(BaseModel):
    # No "namespace" => kdantic infers scope = Cluster
    name: str


#
# class K8sWidgetModel(BaseModel):
#     apiVersion: Literal["widgets.acme.io/v1"]
#     kind: Literal["Widget"]
#     metadata: NamespacedMeta
#     spec: dict


class K8sGadgetModel(BaseModel):
    apiVersion: str = "gadgets.example.com/v1alpha1"
    kind: str = "Gadget"
    metadata: NamespacedMeta
    spec: dict


class APIVersion_Things(str, Enum):
    V1 = "things.acme.io/v1"
    V1B = "things.acme.io/v1beta1"


class Kind_Thing(str, Enum):
    THING = "Thing"


class K8sThingModel(BaseModel):
    apiVersion: APIVersion_Things = APIVersion_Things.V1
    kind: Kind_Thing = Kind_Thing.THING
    metadata: NamespacedMeta
    spec: dict


class NetSpec(BaseModel):
    service_ip: Annotated[
        IPvAnyAddress,
        Field(description="Service IP", json_schema_extra={"format": "ipvanynetwork"}),
    ]
    labels: dict[str, str] = Field(default_factory=dict, description="K/V labels")
    ports: list[int] = Field(default_factory=list, description="Exposed ports")


class K8sNetworkModel(BaseModel):
    apiVersion: Literal["net.acme.io/v1"]
    kind: Literal["Network"]
    metadata: NamespacedMeta
    spec: NetSpec


class K8sClusterFooModel(BaseModel):
    apiVersion: Literal["foo.bar/v1"]
    kind: Literal["ClusterFoo"]
    metadata: ClusterMeta
    spec: dict


class Mode(str, Enum):
    ON = "on"
    OFF = "off"


class ServiceSpec(BaseModel):
    replicas: int = Field(ge=0, default=1)
    mode: Mode = Mode.ON
    maybe_note: Optional[str] = None
    relaxed: int | str = 0


class K8sServiceModel(BaseModel):
    apiVersion: Literal["svc.acme.io/v1"]
    kind: Literal["Service"]
    metadata: NamespacedMeta
    spec: ServiceSpec


class JobStatus(BaseModel):
    observedGeneration: Optional[int] = None
    phase: Optional[str] = None


class K8sJobModel(BaseModel):
    apiVersion: Literal["jobs.acme.io/v1"]
    kind: Literal["Job"]
    metadata: NamespacedMeta
    spec: dict = Field(default_factory=dict, description="Desired state")
    status: Optional[JobStatus] = None  # ⇒ subresources.status in CRD


class K8sWidgetNamesExplicitModel(BaseModel):
    __crd_singular__ = "widget"
    __crd_plural__ = "widgets"
    __crd_short_names__ = ["wdg"]

    apiVersion: Literal["widgets.acme.io/v1"]
    kind: Literal["Widget"]
    metadata: NamespacedMeta
    spec: dict


class K8sPolicySingularOnlyModel(BaseModel):
    __crd_singular__ = "foo"

    apiVersion: Literal["sec.acme.io/v1"]
    kind: Literal["Policy"]
    metadata: NamespacedMeta
    spec: dict


class K8sJobNoNamesModel(BaseModel):
    apiVersion: Literal["batch.acme.io/v1"]
    kind: Literal["Job"]  # singular ⇒ job, plural ⇒ jobs
    metadata: NamespacedMeta
    spec: dict
