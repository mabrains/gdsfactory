import logging
import os
import warnings
from datetime import datetime
from typing import Any

import networkx as nx
import numpy as np
from pydantic import validate_call

import gdsfactory as gf
from gdsfactory import Component


@validate_call
def get_path_length_from_component(
    component: Component,
) -> list[tuple[str, str, float]]:
    """
    Gets a list of tuples containis (start_port , end_port, path_length)
    for each path in component.

    Args:
        component: the component to get path_length for.

    Returns:
        Path_length: list of tuples containis (start_port , end_port, path_length)
    for each path in component.
    """
    try:
        pathlength_graph = get_edge_based_route_attr_graph(component)
    except Exception as e:
        logging.error(f"failed to extract graph, error message {e}")
        exit(1)
    try:
        path_length = get_paths(pathlength_graph)
    except Exception as e:
        logging.error(f"failed to get component paths, error message : {e}")
        exit(1)

    return path_length


def get_edge_based_route_attr_graph(pic: Component) -> nx.Graph:
    """
    Gets a connectivity graph for the circuit, with all path attributes on edges and ports as nodes.

    Args:
        pic: the pic to generate a graph from.

    Returns:
        A NetworkX Graph
    """
    from gdsfactory.get_netlist import get_netlist_recursive

    try:
        netlists = get_netlist_recursive(pic)
    except Exception:
        logging.error("failed to get netlist")
    for netlist_name, netlist in netlists.items():
        logging.info(f"netlist_name : {netlist_name} \n netlist : {netlist}")
    netlist = netlists[pic.name]
    # print(netlist)
    try:
        return _get_edge_based_route_attr_graph(
            pic,
            netlist=netlist,
            netlists=netlists,
        )
    except Exception:
        logging.error("failed to get graph from netlist")


def add_netlist_to_graph(
    component: Component,
    netlist: Any,
) -> tuple[nx.Graph, dict, dict, dict]:
    """
    Add netlist components to graph ports as nodes with route attributes.
    """
    connections = netlist["connections"]
    logging.info(f"netlist : \n {netlist} \n")
    logging.info(f"connections : \n {connections} \n")
    logging.info(f" netlist['instances'] : \n { netlist['instances']} \n")

    g = nx.Graph()
    inst_route_attrs = {}
    node_attrs = {}
    inst_refs = {}
    for inst_name in netlist["instances"]:
        ref = component.named_references[inst_name]
        inst_refs[inst_name] = ref
        info = ref.parent.info.model_dump()

        if "route_info_length" in info:
            inst_route_attrs[inst_name] = dict()
            for key, value in info.items():
                if key.startswith("route_info"):
                    inst_route_attrs[inst_name].update({key: value})
        for port_name, port in ref.ports.items():
            ploc = port.center
            pname = f"{inst_name},{port_name}"
            n_attrs = {
                "x": ploc[0],
                "y": ploc[1],
            }
            node_attrs[pname] = n_attrs
            g.add_node(pname, **n_attrs)

    logging.info(f"inst_route_attrs : \n {inst_route_attrs} \n")
    g.add_edges_from(connections.items(), weight=0.0001)
    return g, inst_route_attrs, inst_refs, node_attrs


def connect_top_level_ports(
    g: nx.Graph, top_level_ports: dict, node_attrs: dict
) -> nx.Graph:
    edges = []
    for port, sub_port in top_level_ports.items():
        p_attrs = dict(node_attrs[sub_port])
        e_attrs = {"weight": 0.0001}
        edge = [port, sub_port, e_attrs]
        edges.append(edge)
        g.add_node(port, **p_attrs)
    g.add_edges_from(edges)
    return g


@validate_call
def _get_edge_based_route_attr_graph(
    component: Component,
    netlist: dict[str, Any],
    netlists: dict[str, dict[str, Any]],
) -> nx.Graph:
    top_level_ports = netlist["ports"]
    try:
        g, inst_route_attrs, inst_refs, node_attrs = add_netlist_to_graph(
            component, netlist
        )
    except Exception as e:
        logging.error("failed to add netlist to graph")
        logging.error(f"error : \n {(str(e))}")
        exit(1)

    # connect all internal ports for devices with connectivity defined
    # currently we only do this for routing components, but could do it more generally in the future
    for inst_name, inst_dict in netlist["instances"].items():
        route_info = inst_route_attrs.get(inst_name)
        inst_component = component.named_references[inst_name]
        route_attrs = get_internal_netlist_attributes(
            inst_dict, route_info, inst_component
        )
        if route_attrs:
            for link, attrs in route_attrs.items():
                in_port, out_port = link.split(":")
                inst_in = f"{inst_name},{in_port}"
                inst_out = f"{inst_name},{out_port}"
                g.add_edge(inst_in, inst_out, **attrs)
        else:
            sub_inst = inst_refs[inst_name]
            logging.info(f"sub_inst : {sub_inst}, netllist name {sub_inst.parent.name}")
            if sub_inst.parent.name in netlists:
                sub_netlist = netlists[sub_inst.parent.name]
                try:
                    sub_graph = _get_edge_based_route_attr_graph(
                        sub_inst.parent,
                        netlist=sub_netlist,
                        netlists=netlists,
                    )
                except Exception as e:
                    logging.error(
                        f" error in recursive loop, \n sub_inst :  {sub_inst} , \n sub_netlist {sub_netlist} "
                    )
                    logging.error(f"error message {e}")
                else:
                    sub_nodes = []
                    sub_edges = []
                    for edge in sub_graph.edges(data=True):
                        s, e, d = edge
                        new_edge = []
                        for node_name in [s, e]:
                            new_node_name = _get_subinst_node_name(node_name, inst_name)
                            new_edge.append(new_node_name)
                        new_edge.append(d)
                        sub_edges.append(new_edge)
                    for node in sub_graph.nodes(data=True):
                        n, d = node
                        new_name = _get_subinst_node_name(n, inst_name)
                        x = d["x"]
                        y = d["y"]
                        new_pt = sub_inst._transform_point(
                            np.array([x, y]),
                            sub_inst.origin,
                            sub_inst.rotation,
                            sub_inst.x_reflection,
                        )
                        d["x"] = new_pt[0]
                        d["y"] = new_pt[1]
                        new_node = (new_name, d)
                        sub_nodes.append(new_node)
                    g.add_nodes_from(sub_nodes)
                    g.add_edges_from(sub_edges)
            else:
                warnings.warn(
                    f"ignoring any links in {inst_name} ({sub_inst.parent.name})"
                )

    # connect all top level ports
    logging.info(f"top level ports : {top_level_ports}")
    if top_level_ports:
        try:
            connect_top_level_ports(g, top_level_ports, node_attrs)
        except Exception:
            logging.error("failed to connect top level ports")
            exit(1)
    return g


def get_paths(pathlength_graph: nx.Graph) -> list[dict[str, Any]]:
    """
    Gets a list of dictionaries from the pathlength graph describing each of the aggregate paths.

    Args:
        pathlength_graph: a graph representing a circuit

    Returns:
        Path_length: list of tuples containis (start_port , end_port, path_length)
    for each path in component.
    """

    paths = nx.connected_components(pathlength_graph)
    route_records = []
    for path in paths:
        node_degrees = pathlength_graph.degree(path)
        end_nodes = [n for n, deg in node_degrees if deg == 1]
        end_ports = []
        for node in end_nodes:
            inst, port = _node_to_inst_port(node)
            end_ports.append((inst, port))
        if len(end_ports) > 1:
            node_pairs = find_node_pairs(end_nodes)
            for node_pair in node_pairs:
                end_nodes = list(node_pair)
                all_paths = nx.all_shortest_paths(pathlength_graph, *end_nodes)
                for path in all_paths:
                    start_port = end_nodes[0]
                    end_port = end_nodes[1]
                    edges = pathlength_graph.edges(nbunch=path, data=True)
                    edge_data = [e[2] for e in edges if e[2]]
                    path_length = sum_lengths(edge_data)
                    route_records.append((start_port, end_port, path_length))

    return route_records


def find_node_pairs(nodes: list[str]) -> list[set[str]]:
    node_pairs = []
    for n1 in nodes:
        for n2 in nodes:
            if n1 != n2:
                s = {n1, n2}
                if s not in node_pairs:
                    node_pairs.append(s)
    return node_pairs


def _get_subinst_node_name(node_name: str, inst_name: str) -> str:
    return (
        f"{inst_name}.{node_name}" if "," in node_name else f"{inst_name},{node_name}"
    )


def get_internal_netlist_attributes(
    route_inst_def: dict[str, dict], route_info: dict | None, component: Component
) -> dict[str, Any] | None:
    if route_info:
        link = _get_link_name(component)
        component_name = route_inst_def["component"]
        attrs = route_info
        attrs["component"] = component_name
        return {link: attrs}
    else:
        return None


def _get_link_name(component: Component) -> str:
    ports = sorted(component.ports.keys())
    if len(ports) != 2:
        raise ValueError("routing components must have two ports")
    return ":".join(ports)


def _is_scalar(val: Any) -> bool:
    return isinstance(val, float | int)


def sum_lengths(records: list[dict[str, Any]]) -> float:
    path_length = 0.0
    for record in records:
        try:
            record["route_info_length"]
        except KeyError:
            continue
        else:
            if _is_scalar(record["route_info_length"]):
                path_length += record["route_info_length"]
    return path_length


def _node_to_inst_port(node: str) -> tuple[str, str]:
    ip = node.split(",")
    if len(ip) == 2:
        inst, port = ip
    elif len(ip) == 1:
        port = ip[0]
        inst = ""
    else:
        raise ValueError(
            f"did not expect a connection name with more than one comma: {node}"
        )
    return inst, port


def test_read_gds_file(gds_file_path: str) -> None:
    try:
        c = gf.read.import_gds(gds_file_path)
    except FileNotFoundError:
        logging.error(f"cannot find gds file, path : {gds_file_path}")
        exit(1)
    path_length = get_path_length_from_component(c)
    c.show()
    logging.info(f"{gds_file_path} file path_lengths : \n {path_length}")


def test_gds_component() -> None:
    cname = "test_path_length_from component"
    c = gf.Component(cname)

    path_1_i1 = c.add_ref(gf.components.straight(length=100), "path_1_i1")
    path_1_i2 = c.add_ref(gf.components.straight(length=50), "path_1_i2")
    path_1_i3 = c.add_ref(gf.components.bend_euler(radius=50), "path_1_i3")
    path_1_i4 = c.add_ref(gf.components.bend_euler_s(radius=100), "path_1_i4")
    path_1_i3.connect("o1", path_1_i2.ports["o1"])
    path_1_i1.connect("o1", path_1_i2.ports["o2"])
    path_1_i4.connect("o1", path_1_i1.ports["o2"])

    path_2_i1 = c.add_ref(gf.components.straight(length=100), "path_2_i1")
    path_2_i2 = c.add_ref(gf.components.straight(length=50), "path_2_i2")
    path_2_i2.center = (500, 500)
    path_2_i3 = c.add_ref(gf.components.bend_euler(radius=50), "path_2_i3")
    path_2_i4 = c.add_ref(gf.components.bend_euler_s(radius=100), "path_2_i4")
    path_2_i3.connect("o1", path_2_i2.ports["o1"])
    path_2_i1.connect("o1", path_2_i2.ports["o2"])
    path_2_i4.connect("o1", path_2_i1.ports["o2"])

    path_3_i1 = c.add_ref(gf.components.straight(length=10), "path_3_i1")
    path_3_i2 = c.add_ref(gf.components.straight(length=5), "path_3_i2")
    path_3_i2.center = (250, 250)
    path_3_i3 = c.add_ref(gf.components.bend_euler(radius=5), "path_3_i3")
    path_3_i4 = c.add_ref(gf.components.bend_euler_s(radius=10), "path_3_i4")
    path_3_i3.connect("o1", path_3_i2.ports["o1"])
    path_3_i1.connect("o1", path_3_i2.ports["o2"])
    path_3_i4.connect("o1", path_3_i1.ports["o2"])

    c.show()
    path_length = get_path_length_from_component(c)
    logging.info(f"{cname} path_lengths : \n {path_length}")


def main() -> None:
    # gds_file_path = "test_path_length/inverter.gds"
    # test_read_gds_file(gds_file_path)
    test_gds_component()


if __name__ == "__main__":
    if not os.path.exists("logs/path_length_from_component/"):
        os.mkdir("logs/path_length_from_component/")

    now_str = datetime.utcnow().strftime("path_length_from_component_%Y_%m_%d_%H_%M_%S")
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[
            logging.FileHandler(f"logs/path_length_from_component/{now_str}.log"),
            logging.StreamHandler(),
        ],
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%d-%b-%Y %H:%M:%S",
    )
    logging.getLogger()
    main()
