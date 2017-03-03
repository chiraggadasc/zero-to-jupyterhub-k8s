#!/usr/bin/python3

"""Primary scale logic"""
from workload import schedule_goal
from update_nodes import update_unschedulable
from cluster_update import gce_cluster_control
from settings import settings

import logging
import argparse
from kubernetes_control import k8s_control
from kubernetes_control_test import k8s_control_test

logging.basicConfig(
    format='%(asctime)s %(levelname)s %(message)s')
scale_logger = logging.getLogger("scale")


def shutdown_empty_nodes(nodes, k8s, cluster):
    """
    Search through all nodes and shut down those that are unschedulable
    and devoid of non-critical pods

    CRITICAL NODES SHOULD NEVER BE INCLUDED IN THE INPUT LIST
    """
    for node in nodes:
        if k8s.get_pods_number_on_node(node) == 0 and node.spec.unschedulable:
            scale_logger.info(
                "Shutting down empty node: %s", node.metadata.name)
            cluster.shutdown_specified_node(node.metadata.name)


def resize_for_new_nodes(new_total_nodes, k8s, cluster):
    """create new nodes to match new_total_nodes required
    only for scaling up

    TODO: Add gcloud python client for sizing up
    instead of CLI call"""
    scale_logger.info("Resizing up to: %d nodes", new_total_nodes)
    cluster.add_new_node(
        new_total_nodes, k8s.get_cluster_name())


def scale(options, context, test=False):
    """Update the nodes property based on scaling policy
    and create new nodes if necessary"""
    if test:
        k8s = k8s_control_test(options, context)
    else:
        k8s = k8s_control(options, context)
        # ONLY GCE is supported for scaling at this time
        cluster = gce_cluster_control(options)
    scale_logger.info("Scaling on cluster %s", k8s.get_cluster_name())

    nodes = []  # a list of nodes that are NOT critical
    for node in k8s.nodes:
        if node.metadata.name not in k8s.critical_node_names:
            nodes.append(node)
    goal = schedule_goal(k8s, options)

    scale_logger.info("Total nodes in the cluster: %i", len(k8s.nodes))
    scale_logger.info("Found %i critical nodes; recommending additional %i nodes for service",
                      len(k8s.nodes) - len(nodes), goal)

    update_unschedulable(len(nodes) - goal, nodes, k8s)

    if len(k8s.critical_node_names) + goal > len(k8s.nodes):
        scale_logger.info("Resize the cluster to %i nodes to satisfy the demand", (
            len(k8s.critical_node_names) + goal))
        if not test:
            resize_for_new_nodes(
                len(k8s.critical_node_names) + goal, k8s, cluster)
    if not test:
        # CRITICAL NODES SHOULD NOT BE SHUTDOWN
        shutdown_empty_nodes(nodes, k8s, cluster)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-v", "--verbose", help="Show verbose output (debug)", action="store_true")
    parser.add_argument(
        "--test", help="Run the script in test mode, no real action", action="store_true")
    parser.add_argument(
        "-c", "--context", required=True, help="A unique segment in the context name to specify which to use to instantiate Kubernetes")
    args = parser.parse_args()
    if args.verbose:
        scale_logger.setLevel(logging.DEBUG)
    else:
        scale_logger.setLevel(logging.INFO)

    if args.test:
        scale_logger.warning(
            "Running in test mode, no action will actually be taken")

    options = settings()
    scale(options, args.context)
