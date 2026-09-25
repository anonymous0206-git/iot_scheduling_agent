# import gentopo
import queue
import sys
from collections import defaultdict

import numpy as np

vertex_c = []
edge_c = []
INFINITY = sys.maxsize - 1


# T = 10 # L is length of time slot in a period

def distance(src, dst):
    """

    :param src:
    :param dst:
    :return:
    """
    return np.sqrt(np.square(src.x - dst.x) + np.square(src.y - dst.y))


def create_list_of_channels(r1, r2):
    return [item for item in range(r1, r2 + 1)]


def link(u, v):
    """
    Create a link consisting of two nodes as a type tuple
    """
    return (u, v)


def intersection(lst1, lst2):
    return list(set(lst1) & set(lst2))


def layering(node_list):
    """

    :param node_list:
    :return:
    """

    N = len(node_list)
    node_list[0].layer = 0
    traversed = [0]
    remaining = [i for i in range(1, N)]
    current_layer = 0
    while len(remaining) > 0:
        traversing = set([])
        for i in traversed:
            if node_list[i].layer == current_layer:
                for k in remaining:
                    if k in node_list[i].neighborIDs:
                        node_list[i].next_layer_neighbors.append(k)
                        node_list[k].prev_layer_neighbors.append(i)
                        node_list[k].layer = current_layer + 1
                        traversing.add(k)
        traversed += list(traversing)
        remaining = [x for x in remaining if x not in traversing]
        current_layer += 1
    return node_list, current_layer


def tree_construction_based_minimum_link_delay(node_list, T):
    """

    :param node_list:
    :param T:
    :return:
    """

    node_list, max_layer = layering(node_list)
    nodes_in_tree = [0]

    for i in range(1, max_layer + 1):
        for send_node in range(1, len(node_list)):
            delay = 100000
            if node_list[send_node].layer == i:
                for rcv_node in node_list[send_node].neighborIDs:
                    # if node_list[rcv_node].layer == (i-1) or node_list[rcv_node].layer == i:
                    if node_list[rcv_node].layer == (i - 1):
                        for rcv_slot in node_list[rcv_node].active_slot:
                            for send_slot in node_list[send_node].active_slot:
                                if rcv_slot > send_slot and rcv_slot - send_slot < delay:
                                    # if rcv_slot > send_slot:
                                    delay = rcv_slot - send_slot
                                    temp_parent = rcv_node
                                elif rcv_slot <= send_slot and rcv_slot + T - send_slot < delay:
                                    # else:
                                    delay = rcv_slot + T - send_slot
                                    temp_parent = rcv_node

            if node_list[send_node].delay > delay:
                if node_list[send_node].parentID is None:
                    node_list[send_node].parentID = temp_parent
                    node_list[temp_parent].childrenIDs.append(send_node)
                    node_list[send_node].delay = delay
                    nodes_in_tree.append(send_node)
                else:
                    parent_old = node_list[send_node].parentID
                    node_list[send_node].parentID = temp_parent
                    node_list[temp_parent].childrenIDs.append(send_node)
                    node_list[parent_old].childrenIDs.remove(send_node)
                    node_list[send_node].delay = delay

    if len(nodes_in_tree) != len(node_list):
        print(len(nodes_in_tree))
        print("Disconnected network")

    leaf_nodes_set = []
    non_leaf_nodes_set = []
    for node_id in range(1, len(node_list)):
        if not node_list[node_id].childrenIDs:
            leaf_nodes_set.append(node_id)
        if node_list[node_id].childrenIDs:
            non_leaf_nodes_set.append(node_id)

    for each_node in node_list:
        find_descendent_nodes(node_list, each_node)

    return node_list, max_layer


def find_descendent_nodes(node_list, x):
    for each_child in x.childrenIDs:
        if each_child not in x.descIDs:
            x.descIDs.append(each_child)
            if node_list[each_child].childrenIDs == []:
                continue
            else:
                dsc = find_descendent_nodes(node_list, node_list[each_child])
                for each_id in dsc:
                    if each_id not in x.descIDs:
                        x.descIDs.append(each_id)
    return x.descIDs


def find_parent_node_list(node_list, children_list):
    list_of_links = []
    for each_node in children_list:
        list_of_links.append(link(each_node, node_list[each_node].parentID))
    return list_of_links


def check_child_scheduled(node_list, x):
    """
    To check if all child nodes of a node have been scheduled
    :param node_list:
    :param x:
    :return: True if all children have been scheduled
            False if one of children not yet scheduled
    """
    temp = 0
    for each_child in node_list[x].childrenIDs:
        if node_list[each_child].channel is None and node_list[each_child].timeslot is None:
            temp += 1
    if temp == 0:
        return True
    else:
        return False


def check_neighbor_scheduled_and_active_at_current_slot(node_list, x, slot):
    """
    To check if there is a neighbor of x has not been scheduled
    :param node_list:
    :param x:
    :return: True if there is a neighbor node has NOT been scheduled
            False if all neighbor nodes have been scheduled
    """
    temp = 0
    for each_node in node_list[x].neighborIDs:
        if node_list[each_node].channel is None and node_list[each_node].timeslot is None:
            for each_active_slot in node_list[each_node].active_slot:
                if each_active_slot == slot:
                    temp += 1
    if temp != 0:
        return True
    else:
        return False


def find_candidate_senders_at_current_slot(node_list, slot):
    Mt = []
    for each_node in range(0, len(node_list)):
        if node_list[each_node].timeslot is None:
            if check_child_scheduled(node_list, each_node) is True or len(node_list[each_node].childrenIDs) == 0:
                if check_neighbor_scheduled_and_active_at_current_slot(node_list, each_node, slot) is True:
                    Mt.append(each_node)
    return Mt


def weight_calc(node_list, x, slot):
    node_list[x].weight = 0
    for each_neighbor in node_list[x].neighborIDs:
        if slot in node_list[each_neighbor].active_slot and node_list[each_neighbor].timeslot is None:
            node_list[x].weight += 1


def collision_in_eligible_senders(node_list, sender, set_sender):
    degree = -1
    for each_node in set_sender:
        if sender in node_list[node_list[each_node].parentID].neighborIDs or each_node in node_list[
            node_list[sender].parentID].neighborIDs:
            degree += 1
    if degree == -1:
        return False
    else:
        return True


def dynamic_schedule(node_list, M_slot, S_slot, R_slot, T, f, slot, wp):
    """
    This function is to apply parent changing approach and schedule candidate senders in M_slot
    :param node_list:
    :param M_slot:
    :param S_slot:
    :param R_slot:
    :param T:
    :param slot:
    :return:
    """
    eligible_senders = []
    Parent_set = []
    candidate_senders_queue = queue.Queue()
    for q in M_slot:
        candidate_senders_queue.put(q)
    # for m in M_slot:
    while not candidate_senders_queue.empty():
        m = candidate_senders_queue.get()
        if m not in Parent_set:
            r = None
            neighbors_of_m = [v for v in node_list[m].neighborIDs if
                              node_list[v].timeslot is None and v not in eligible_senders]
            for p in neighbors_of_m:
                if slot in node_list[p].active_slot and node_list[p].timeslot is None:
                    if p not in Parent_set:
                        if r is None:
                            r = p
                        else:
                            neighbors_of_p = [x for x in node_list[p].neighborIDs if
                                              node_list[x].timeslot is None and slot in node_list[x].active_slot]
                            neighbors_of_r = [y for y in node_list[r].neighborIDs if
                                              node_list[y].timeslot is None and slot in node_list[y].active_slot]
                            # neighbors_of_p = node_list[p].weight
                            # neighbors_of_r = node_list[r].weight
                            if len(neighbors_of_p) < len(neighbors_of_r):
                                # if neighbors_of_p < neighbors_of_r:
                                r = p
            if r is not None:
                p = node_list[m].parentID
                node_list[m].parentID = r
                eligible_senders.append(m)
                Parent_set.append(r)
                node_list[r].childrenIDs.append(m)
                node_list[p].childrenIDs.remove(m)

                if p not in Parent_set:
                    if len(node_list[p].childrenIDs) != 0:
                        for w in node_list[p].childrenIDs:
                            if node_list[w].timeslot is None:
                                break
                        else:
                            candidate_senders_queue.put(p)
                    else:
                        candidate_senders_queue.put(p)

    C = defaultdict(list, {k: [] for k in range(1, 8)})
    for each_node in eligible_senders:
        for k, v in C.items():
            if collision_in_eligible_senders(node_list, each_node, v) == False:
                v.append(each_node)
                break

    for color_c, nodes in C.items():
        if color_c <= f:
            for each_node in nodes:
                node_list[each_node].timeslot = (wp - 1) * T + slot
                node_list[each_node].channel = color_c
                S_slot.append(each_node)
                R_slot.append(node_list[each_node].parentID)
        else:
            break


def ANEX(node_list, T, f, comm_range, alpha):
    """
    :param node_list:
    :param T:
    :param m:
    :param comm_range:
    :param alpha:
    :return:
    """
    U = [0]

    for i in range(0, len(node_list) - 1):
        for j in range(i + 1, len(node_list)):
            if distance(node_list[i], node_list[j]) <= comm_range * alpha:
                node_list[i].interfereIDs.append(node_list[j].ID)
                node_list[j].interfereIDs.append(node_list[i].ID)

    # ts = 0
    wp = 1
    while len(U) != len(node_list):

        for slot in range(0, T):
            M_slot = find_candidate_senders_at_current_slot(node_list, slot)

            for each_node in M_slot:
                weight_calc(node_list, each_node, slot)

            M_slot = sorted(M_slot, key=lambda x: node_list[x].weight, reverse=False)

            S_slot = []
            R_slot = []

            dynamic_schedule(node_list, M_slot, S_slot, R_slot, T, f, slot, wp)

            U.extend(S_slot)
            M_slot.clear()
        wp += 1

    """
    for each_node in range(1, len(node_list)):
        print("channel and timeslot of each node: %u %u %u" % (
        each_node, node_list[each_node].channel, node_list[each_node].timeslot))
    """
    return node_list


def find_candidate_senders_at_current_slot_static_schedule(node_list, slot):
    Mt = []
    for each_node in range(1, len(node_list)):
        if node_list[each_node].timeslot is None:
            if check_child_scheduled(node_list, each_node) is True or len(node_list[each_node].childrenIDs) == 0:
                # if node_list[node_list[each_node].parentID].timeslot is None and slot in node_list[node_list[each_node].parentID].active_slot:
                if slot in node_list[node_list[each_node].parentID].active_slot:
                    Mt.append(each_node)
    return Mt


def static_schedule(node_list, T, f):
    """
    This function is to apply parent changing approach and schedule candidate senders in M_slot
    :param node_list:
    :param M_slot:
    :param S_slot:
    :param R_slot:
    :param T:
    :param slot:
    :return:
    """
    U = [0]
    # ts = 0
    wp = 1
    while len(U) != len(node_list):

        for slot in range(0, T):
            M_slot = find_candidate_senders_at_current_slot_static_schedule(node_list, slot)

            for each_node in M_slot:
                weight_calc(node_list, each_node, slot)

            M_slot = sorted(M_slot, key=lambda x: node_list[x].weight, reverse=False)

            eligible_senders = []
            Parent_set = []
            candidate_senders_queue = queue.Queue()
            for q in M_slot:
                candidate_senders_queue.put(q)
            # for m in M_slot:
            while not candidate_senders_queue.empty():
                m = candidate_senders_queue.get()
                if node_list[m].parentID not in Parent_set:
                    eligible_senders.append(m)
                    Parent_set.append(node_list[m].parentID)

            S_slot = []
            R_slot = []
            C = defaultdict(list, {k: [] for k in range(1, 8)})
            for each_node in eligible_senders:
                for k, v in C.items():
                    if collision_in_eligible_senders(node_list, each_node, v) == False:
                        v.append(each_node)
                        break

            for color_c, nodes in C.items():
                if color_c <= f:
                    for each_node in nodes:
                        node_list[each_node].timeslot = (wp - 1) * T + slot
                        node_list[each_node].channel = color_c
                        S_slot.append(each_node)
                        R_slot.append(node_list[each_node].parentID)
                else:
                    break

            U.extend(S_slot)
            M_slot.clear()
        wp += 1
    """
    for each_node in range(1, len(node_list)):
        print("channel and timeslot of each node: %u %u %u" % (
            each_node, node_list[each_node].channel, node_list[each_node].timeslot))
    """

    return node_list
