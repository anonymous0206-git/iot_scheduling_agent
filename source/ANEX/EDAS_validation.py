

def schedule_validation(node_list):
    """
    check out the constructed schedule:
    1. Check if it's a tree
    - Go from any node upwards, through the ancestors, it must reach the sink
    2. check the schedule:
    - All children of a node must have different working period (tx_wp)
    - (working period, active time slot) of the children must be smaller than the parent's
     - no collision in same (working period, active time slot)
    :return:
    """
    for u in range(1, len(node_list)):
        parent = node_list[u].parentID
        count = 1
        while parent != 0:
            parent = node_list[parent].parentID
            count += 1
            if count > len(node_list):
                print("This is not a valid tree")
                break


    """
    The parent node should be assigned larger timeslot than children nodes
    """
    for u in range(1, len(node_list)):
        for v in node_list[u].childrenIDs:
            if node_list[v].timeslot > node_list[u].timeslot:
                print("timeslot of child", v, "is larger than timeslot of it's parent:", u)
            if node_list[v].timeslot == node_list[u].timeslot:
                print(f"timeslot of child {v} is equal to timeslot of it's parent: {u} at timeslot {node_list[v].timeslot, node_list[u].channel, node_list[v].channel}")

    """
    To check if all nodes in the network are assigned timeslots
    """
    for u in range(1, len(node_list)):
        if node_list[u].timeslot is None:
            print("The node", u, "does not assign any timeslot yet")
        if node_list[u].channel is None:
            print("The node", u, "does not assign any channel yet")

    """
    To check the secondary collision while scheduling
    """
    for u in range(1, len(node_list)):
        for v in range(u+1, len(node_list)):
            if u in node_list[node_list[v].parentID].neighborIDs or v in node_list[node_list[u].parentID].neighborIDs:
                if node_list[u].channel == node_list[v].channel and node_list[u].timeslot == node_list[v].timeslot:
                    print("Secondary collision happens: Node", u, "and node", v, "are scheduled in the same channel and timeslot")

    """
    To check the primary collision while scheduling
    """
    for u in range(1, len(node_list)):
        for v in range(u+1, len(node_list)):
            if node_list[u].parentID == node_list[v].parentID:
                if node_list[u].timeslot == node_list[v].timeslot:
                    print("Primary collision happens: Node", u, "and node", v, "are schedule in the same channel and timeslot")

