__copyright__ = """
LICENSED INTERNAL CODE. PROPERTY OF IBM.
IBM Research Licensed Internal Code
(C) Copyright IBM Corp. 2021
ALL RIGHTS RESERVED
"""
import torch
import networkx as nx
from typing import Tuple
from math import sqrt, exp
import pandas as pd


torch.set_default_tensor_type(torch.DoubleTensor)


def read_sif(filepath: str) -> Tuple[list, dict]:
    """
    Read a SIF file and returns the list of node names and a dictionnary mapping edges to their weight.
    Args:
        - filepath: path to the SIF file
    Edges are assumed to be described in the order "source weight target"
    File is assumed to be space or tab separated
    """
    node_names = []
    edges = {}
    sif_file = open(filepath, "r")
    line = sif_file.readline()
    while line:
        line.strip()
        # print(line)
        node_1, edge_weight, node_2 = line.split()
        edge = (node_1, node_2)
        if edge not in edges:
            edges[edge] = edge_weight
        if node_1 not in node_names:
            node_names.append(node_1)
        if node_2 not in node_names:
            node_names.append(node_2)
        line = sif_file.readline()
    sif_file.close()
    return (node_names, edges)


def change_SIF_convention(filepath_in: str, filepath_out: str) -> None:
    """
    For a SIF file with convention "source target weight", return the corresponding SIF file with convention "source weight target" readable by read_SIF.
    Args:
        - filepath_in: path to the input file
        - filepath_out: path at which to save the output file
    """
    file_in = open(filepath_in, "r")
    file_out = open(filepath_out, "w")
    line = file_in.readline()
    while line:
        line.strip()
        # print(line)
        node_1, node_2, edge_weight = line.split()
        file_out.writelines("\t".join([node_1, edge_weight, node_2]))
        file_out.writelines("\n")
        line = file_in.readline()
    file_in.close()
    file_out.close()


def has_cycle(G: nx.DiGraph) -> Tuple[bool, list]:
    cycle_list = []
    has_cycle = False
    for node in G.nodes():
        try:
            edges = nx.find_cycle(G, source=node, orientation="original")
            cycle_nodes = [edges[i][0] for i in range(len(edges))]
            cycle_nodes.sort()
            if cycle_nodes not in cycle_list:
                cycle_list.append(cycle_nodes)
            has_cycle = True
        except nx.NetworkXNoCycle:
            continue
    return (has_cycle, cycle_list)


def dictionnary_to_tensor(output_dict):
    # The different nodes represent the different features of my model I think
    """
    Tranforms a dictionnary representing the output or ground truth of a BioFuzzNet
    into a tensor matrix of shape number_of_nodes * number_of_cells.
    Args:
        output_dict: dict mapping nodes of a BioFuzzNet to a tensor of values
    Returns:
        a tensor matrix of shape number_of_nodes * number_of_cells
    """
    keys = list(output_dict.keys())
    node_number = len(keys)  # Features
    k = keys.pop()
    cell_number = len(output_dict[k])  # Samples
    # Get list of tensors to concatenate
    to_concat = list(output_dict.values())
    matrix = torch.cat(to_concat)
    matrix = matrix.reshape((node_number, cell_number))
    return matrix


def MSE_loss(predictions: dict, ground_truth: dict):

    """
    Compute the MSE loss over all nodes of the network
    Args :
    - predictions: dict mapping each node to its predicted value
    - ground_truth: dict mapping each node to its ground_truth.
         Unobserved nodes should not be present in ground truth.
    """
    # Remove unobserved nodes from the prediction
    predictions = {key: predictions[key] for key in ground_truth.keys()}
    # Get the matrices
    predictions = dictionnary_to_tensor(predictions)
    ground_truth = dictionnary_to_tensor(ground_truth)
    # Compute the squared loss without any reduction
    mse_loss = torch.nn.MSELoss(reduction="none")
    squared_loss = mse_loss(predictions, ground_truth)
    # Then I can average however I want
    # I will then average over the network nodes
    loss = torch.mean(squared_loss, 0)
    # Then I average over the batch
    loss = torch.mean(loss)
    return loss



def MSE_entropy_loss(predictions, ground_truth, mixed_gates_regularisation, gates):
    """
    Compute a MSE loss mixed with a separate loss for regularising the MIXED gates in BioMixNets.
    Args:
        - predictions: dict mapping each node to its predicted value
        - ground_truth: dict mapping each node to its ground_truth. Unobserved nodes should not be present in ground truth.
        - mixed_gates_regularisation: parameters for the regularisation of the mixed gates. If it has value p_reg, for each mixed gate,
            we add the value p_reg*AND_param*(1-AND_param)
        - gates: list of mixed gates in the network
    """
    mse_loss = MSE_loss(predictions=predictions, ground_truth=ground_truth)
    regularisation_loss = 0
    for mixed_gate in gates:
        regularisation_loss = regularisation_loss + (
            torch.sigmoid(mixed_gate.AND_param)
            * (1 - torch.sigmoid(mixed_gate.AND_param))
        )

    loss = mse_loss + mixed_gates_regularisation * regularisation_loss
    return loss


# Possibly deprecated
def compute_state_difference(state_1: dict, state_2: dict):
    """
    For two BioFuzzNet states represented by dict,
    compute the maximum over all nodes in those dict of the infinite norm
    of the difference of the node state
    ie: max_{n a node of the BioFuzzNet} (||state_1(node)-state_2(node)||)
    where ||x - y|| = max_{i}( |x(i)-y(i)| for x and y two vectors)

    Args:
        state_1, state_2: dict mapping each node of a BioFuzzNet to a tensor
        representing the current state of a node. They should have the same keys.
    """
    difference = {
        key: torch.abs(torch.sub(state_1[key], state_2[key])) for key in state_1.keys()
    }
    max_diff_per_state = [torch.max(val).item() for val in difference.values()]
    max_diff = max(max_diff_per_state)
    return max_diff


def draw_BioFuzzNet(
    G: nx.DiGraph, edge_color_scheme: dict, node_shape_scheme: dict, pos=None
) -> dict:
    # Cannot constrain G to have a BioFuzzNet class, otherwise there will be a circular import
    """
    Draws the BioFuzzNet.

    Args:
       edge_color_scheme: a dict associating the 'edge_type' attribute of BioFuzzNet edges to a color
       node_shape_scheme: a dict associating the 'node_type' attribute of BioFuzzNet nodes to a shape
    Returns:
        dictionnary of node positions keyed by nodes
    """
    if (
        pos is None
    ):  # I do not know how to pass that as a default argument since I need to apply it to the graph
        pos = nx.circular_layout(G)
    node_type_list = list(node_shape_scheme.keys())
    for node_type in node_type_list:
        nodes_to_plot = [
            node
            for node, attributes in G.nodes(data=True)
            if attributes["node_type"] == node_type
        ]
        nx.draw_networkx_nodes(
            G,
            pos,
            nodelist=nodes_to_plot,
            node_shape=node_shape_scheme[node_type],
        )
    # Draw the edges and the labels
    edge_colors = [edge_color_scheme[G[u][v]["edge_type"]] for u, v in G.edges()]
    nx.draw_networkx_edges(G, pos, edge_color=edge_colors)
    nx.draw_networkx_labels(G, pos, font_size=8)
    return pos


def obtain_params(G) -> Tuple[dict, list, list]:
    """
    Return a tuple of the list of values taken by parameters n and K
        of a HillTransferFunction from a BioFuzzNet.

    Args:
        A BioFuzzNet

    Return:
        Tuple[dictionnary mapping transfer edges to their parameter values,
            list of values of n,
            list of values of K]
    """
    param_dict = {
        e: [p.item() for p in G.edges()[e]["layer"].parameters()] for e in G.transfer_edges
    }
    n = []
    K = []
    for edge, params in param_dict.items():
        ni = exp(params[0])
        Ki = exp(params[1])
        n.append(ni)
        K.append(Ki)
    return (param_dict, n, K)


def param_dict_to_lists(param_dict) -> Tuple[list, list]:
    """
    Separate a dictionnary mapping transfer edges with HillTransferFunction
        to the values of the parameters of the HillTransferFunction into two
        lists of parameter values

    Args:
        param_dict: a dictionnary mapping transfer edges with HillTransferFunction
            to the values of the parameters of the HillTransferFunction
    """
    n = []
    K = []
    for edge, params in param_dict.items():
        ni = torch.exp(params[0]).item()
        Ki = torch.exp(params[1]).item()
        n.append(ni)
        K.append(Ki)
    return (n, K)


def compute_MSE(list_1: list, list_2: list):
    """
    Compute the MSE between two same-length list of parameters.
    Squared error is computed between list_1[i] and list_2[i].

    Args:
        list_1
        list_2
    Return:
        Mean Squared Error between the elements of those 2 lists
    """

    squared_error = [(list_1[i] - list_2[i]) ** 2 for i in range(len(list_1))]
    return sum(squared_error) / len(squared_error)


def compute_relative_RMSE(list_1: list, list_2: list):
    """
    Compute the relative RMSE between two same-length list of parameters.
    Squared error is computed between list_1[i] and list_2[i]. list_1 is assumed
    to contain the true parameters and list_2 the estimators

    Args:
        list_1
        list_2
    Return:
        Relative Root Mean Squared Error between the elements of those 2 lists
    """

    mean_squared_error = sum(
        [(list_1[i] - list_2[i]) ** 2 for i in range(len(list_1))]
    ) / len(list_1)
    return sqrt(mean_squared_error) / sqrt(
        sum([list_2[i] ** 2 for i in range(len(list_2))])
    )


def compute_relative_error(list_1: list, list_2: list):
    """
    Compute the relative RMSE between two same-length list of parameters.
    Squared error is computed between list_1[i] and list_2[i]. list_1 is assumed
    to contain the true parameters and list_2 the estimators.

    Args:
        list_1
        list_2
    Return:
        List of Relative Error for each element of those 2 lists
    """

    relative_error = [
        sqrt((list_1[i] - list_2[i]) ** 2) / list_2[i] for i in range(len(list_1))
    ]
    return relative_error


def compute_R2_score(list_1: list, list_2: list):
    """
    Compute the R2 score between two same-length list of parameters
    assuming list_2 = f(list_1) and that the true f should be identity.

    Args:
        list_1: x-axis
        list_2: y-axis
    Return:
        R2-score between the elements of those 2 lists
    """
    # Assume the true model is identity, the residual sum of square is compared to f(x) = x
    rss = sum([(list_2[i] - list_1[i]) ** 2 for i in range(len(list_1))])
    tss = sum(
        [(list_2[i] - sum(list_2) / len(list_2)) ** 2 for i in range(len(list_2))]
    )
    return 1 - rss / tss


def compute_RMSE_outputs(model, ground_truth):
    """
    Compute the RMSE between the model output state and the ground truth

    Args:
        model, BioFuzzNet
    Return:
        a dictionnary of the Root Mean Squared Error between the the model output
        state and the ground truth for each node
    """
    rmse = {}
    for node in ground_truth.keys():
        rmse[node] = torch.sqrt(
            torch.sum(
                (model.output_states[node] - ground_truth[node]) ** 2
            )
            / len(model.output_states[node])
        ).item()
    return rmse


def compute_relative_RMSE_outputs(model):
    """
    Compute the relative RMSE between the model output state and the ground truth

    Args:
        model, BioFuzzNet
    Return:
        a dictionnary of the Root Mean Squared Error between the the model output
        state and the ground truth for each node
    """
    rrmse = {}
    for node in model.biological_nodes:
        rrmse[node] = torch.sqrt(
            (
                torch.sum(
                    (model.output_states[node] - model.nodes()[node]["ground_truth"])
                    ** 2
                )
                / len(model.output_states[node])
            )
            / (torch.sum(model.output_states[node] ** 2))
        )
    return rrmse


def compute_RRSE_outputs(model):
    """
    Compute the RRSE between the model output state and the ground truth

    Args:
        model, BioFuzzNet
    Return:
        a dictionnary of the Root Mean Squared Error between the the model output
        state and the ground truth for each node
    """
    rrse = {}
    for node in model.biological_nodes:
        mean_val = torch.mean(model.output_states[node])
        rrse[node] = torch.sqrt(
            (
                torch.sum(
                    (model.output_states[node] - model.nodes()[node]["ground_truth"])
                    ** 2
                )
            )
            / (torch.sum((model.output_states[node] - mean_val) ** 2))
        )
    return rrse