import gdstk
from pydantic import BaseModel, validate_call

import gdsfactory as gf
from gdsfactory.component import ComponentReference
from gdsfactory.port import Port
from gdsfactory.typings import Route


class ComposedRouteBase(BaseModel):
    references: list[ComponentReference] | None = None
    labels: list[gdstk.Label] | None = None
    ports: tuple[Port, Port] | None = None
    length: float = 0.0
    empty_route: bool = True
    model_config = {"extra": "forbid", "arbitrary_types_allowed": True}


class ComposedRoute(ComposedRouteBase):
    def __init__(
        self,
        initial_route: Route | None = None,
        initial_reference: ComponentReference | None = None,
        port0: Port | None = None,
        port1: Port | None = None,
    ) -> None:
        """ """
        super().__init__()
        if initial_route is not None and initial_reference is not None:
            raise Exception("passed to many values")
        if initial_route is not None:
            self.add_route(initial_route)
        if initial_reference is not None:
            self.add_reference(initial_reference, port0, port1)

    def _add_initial_route(self, initial_route: Route) -> None:
        """ """
        self.length = initial_route.length
        self.ports = initial_route.ports
        self.references = initial_route.references
        self.labels = initial_route.labels
        self.empty_route = False

    def add_route(
        self, route: Route, port: Port = None, destination: Port = None
    ) -> None:
        """ """
        if port is None:
            if self.empty_route:
                self._add_initial_route(route)
            else:
                raise Exception("port is None")
        elif not self.empty_route:
            self.length += route.length
            if destination is not self.ports[1]:
                for reference in route.references:
                    reference.connect(port, self.ports[0])
                self.references = route.references + self.references
                self.labels = route.labels + self.labels
                if route.ports[0] is not port:
                    self.ports = (route.ports[0], self.ports[1])
                else:
                    self.ports = (route.ports[-1], self.ports[1])
            else:
                for reference in route.references:
                    reference.connect(port, self.ports[-1])
                self.references = self.references + route.references
                self.labels = self.labels + route.labels
                if route.ports[0] is not port:
                    self.ports = (self.ports[0], route.ports[0])
                else:
                    self.ports = (self.ports[0], route.ports[-1])

    def _get_reference_length(self, reference: ComponentReference) -> float:
        """ """
        return reference.info["length"]

    def _add_initial_reference(
        self,
        reference: ComponentReference,
        port0: str,
        port1: str,
        label: gdstk.Label | None = None,
    ) -> None:
        reference_ports = reference.get_ports_dict()
        self.ports = (reference_ports[port0], reference_ports[port1])
        self.references = [reference]
        self.labels = [label]
        self.length = self._get_reference_length(reference)
        self.empty_route = False

    def add_reference(
        self,
        reference: ComponentReference,
        port0: str,
        port1: str,
        destination: Port | None = None,
        label: gdstk.Label | None = None,
    ) -> None:
        if self.empty_route:
            self._add_initial_reference(reference, port0, port1, label)
        elif destination is None:
            raise Exception("destination port is None")
        else:
            reference_ports = reference.get_ports_dict()
            if destination is self.ports[0]:
                reference.connect(reference_ports[port0], self.ports[0])
                reference_ports = reference.get_ports_dict()
                self.ports = (reference_ports[port1], self.ports[1])
            elif destination is self.ports[1]:
                reference.connect(reference_ports[port0], self.ports[1])
                reference_ports = reference.get_ports_dict()
                self.ports = (self.ports[0], reference_ports[port1])
            else:
                raise Exception("destination port is not valid")
            self.references.append(reference)
            self.labels.append(label)
            self.length += self._get_reference_length(reference)

    def get_length(self) -> float:
        """ """
        return self.length


@validate_call
def test_composed_route_with_routes(c: gf.Component) -> ComposedRoute:
    route1_port1 = gf.Port(
        "route_1_port1",
        center=(200, 100),
        width=100,
        orientation=90,
        layer=(1, 0),
    )
    route1_port2 = gf.Port(
        "route_1_port2",
        center=(250, 150),
        width=100,
        orientation=180,
        layer=(2, 0),
    )
    route2_port1 = gf.Port(
        "route_2_port1",
        center=(300, 150),
        width=100,
        orientation=90,
        layer=(3, 0),
    )
    route2_port2 = gf.Port(
        "route_2_port2",
        center=(350, 200),
        width=100,
        orientation=180,
        layer=(4, 0),
    )
    route3_port1 = gf.Port(
        "route_2_port1",
        center=(400, 150),
        width=100,
        orientation=90,
        layer=(3, 0),
    )
    route3_port2 = gf.Port(
        "route_2_port2",
        center=(450, 250),
        width=100,
        orientation=180,
        layer=(4, 0),
    )

    route1 = gf.routing.get_route(route1_port1, route1_port2)
    route2 = gf.routing.get_route(route2_port1, route2_port2)
    route3 = gf.routing.get_route(route3_port1, route3_port2)
    my_composed_route = ComposedRoute(route1)
    my_composed_route.add_route(route2, route2.ports[0], my_composed_route.ports[1])
    my_composed_route.add_route(route3, route3.ports[1], my_composed_route.ports[0])
    print(f"route 1 length = {route1.length}")
    print(f"route 2 length = {route2.length}")
    print(f"route 3 length = {route3.length}")
    print(f"composed route length = {my_composed_route.length}")
    return my_composed_route


@validate_call
def test_composed_route_with_references(c: gf.Component) -> ComposedRoute:
    reference_1 = c << gf.components.straight(width=0.5, length=100)
    reference_1_port0, reference_1_port1 = reference_1.get_ports_list()[:2]
    reference_2 = c << gf.components.bend_euler(radius=50)
    reference_2_port0, reference_2_port1 = reference_2.get_ports_list()[:2]
    reference_3 = c << gf.components.straight(width=0.5, length=200)
    reference_3_port0, reference_3_port1 = reference_3.get_ports_list()[:2]

    my_composed_route = ComposedRoute(
        initial_reference=reference_1,
        port0=reference_1_port0.name,
        port1=reference_1_port1.name,
    )
    my_composed_route.add_reference(
        reference_2,
        reference_2_port0.name,
        reference_2_port1.name,
        my_composed_route.ports[1],
    )
    my_composed_route.add_reference(
        reference_3,
        reference_3_port1.name,
        reference_3_port0.name,
        my_composed_route.ports[1],
    )

    print(f"reference 1 length = {reference_1.info['length']}")
    print(f"reference 2 length = {reference_2.info['length']}")
    print(f"reference 3 length = {reference_3.info['length']}")
    print(f"composed route length = {my_composed_route.length}")

    return my_composed_route


if __name__ == "__main__":
    cname = "test"
    c = gf.Component(cname)
    c.add(test_composed_route_with_routes(c).references)
    c.add(test_composed_route_with_references(c).references)
    c.show()
