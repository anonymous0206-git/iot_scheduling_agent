import numpy as np
from libs import node
import random
import sys
import queue

INFINITY = sys.maxsize - 1

def distance(src, dst):
    """

    :param src:
    :param dst:
    :return:
    """
    return np.sqrt(np.square(src.x - dst.x) + np.square(src.y - dst.y))


def check_pos_duplicated(pos, node_list):
    """

    :param pos:
    :param node_list:
    :return:
    """
    # return True if there is any node with same location
    for each in node_list:
        if each.x == pos[0] and each.y == pos[1]:
            return True
    else:
        return False


def random_rect(file_name=None, num_node=20, x_range=40, y_range=40, comm_range=25, time_slot=10, active_slot_no=2):
    """
    The node_list of type 'node' will be created, including num_node sensors
    the root node is located at the center of the area
    :param timeslot:
    :param file_name:
    :param num_node:
    :param x_range:
    :param y_range:
    :param comm_range:
    :param t:
    :return:
    """
    node_list = []
    # posRoot = (x_range/2, y_range/2)
    #root = node.Node(0, 0, 0)
    #node_list.append(root)
    root = node.Node(0, x_range/2, y_range/2, active_slot= random.sample(range(0, time_slot-1), active_slot_no))
    node_list.append(root)
    for i in range(1, num_node):
        while True:
            newPos = (random.randint(0, x_range), random.randint(0, y_range))#square topo
            if not check_pos_duplicated(newPos, node_list):
                break
        newNode = node.Node(ID=i, x=newPos[0], y=newPos[1], active_slot=random.sample(range(0, time_slot-1), active_slot_no))
        #print "New node:", newPos
        #newNode.ID = i
        node_list.append(newNode)
        #print newNode.x, newNode.y
    for i in range(0, num_node-1):
        for j in range(i+1, num_node):
            if distance(node_list[i], node_list[j]) <= comm_range:
                node_list[i].neighborIDs.append(j)
                node_list[j].neighborIDs.append(i)
    return node_list


def read_from_topo_repo(topofile, comm_range):
    """
    structure of the file:
    first line: D xx L xx which are the density and sidelength
    from the second line:
        node ID, x-coordinate, y coordinate, active time slot
        seperated by space bar
    :param topofile:
    :return:
    """
    N = -1
    T = -1
    node_list = []
    index = 0
    for line in topofile:
        element = line.split(' ')
        if index == 0:  # first line, just N and T values
            pass
            #D = element[1]
            #L = element[3]
        else:  # from the second line, read ID, x, y of each node
            active_slot = []
            id = int(element[0])
            x = int(element[1])
            y = int(element[2])
            for item in range(3,len(element)-1):
                active_slot.append(int(element[item]))
            #ts = int(element[3])
            newnode = node.Node(id, x, y, active_slot)
            #newnode.ID = id
            node_list.append(newnode)
        index += 1

    for i in range(0, len(node_list)-1):
        for j in range(i+1, len(node_list)):
            if distance(node_list[i], node_list[j]) <= comm_range:
                if node_list[i].ID != i:
                    print("ID and index are not matched!!!")
                node_list[i].neighborIDs.append(node_list[j].ID)
                node_list[j].neighborIDs.append(node_list[i].ID)
    return node_list

def build_bfs(node_list):
    # Build a Breadth First Search Tree, equivalent to an SPT in case all edge costs are 1
    for each_node in node_list:
        each_node.distance = INFINITY
    node_list[0].distance = 0
    q = queue.Queue()
    q.put(node_list[0])
    count = 0
    while q.empty() is False:
        current = q.get()
        count += 1
        for each_node_id in current.neighborIDs:
            if node_list[each_node_id].distance == INFINITY:
                node_list[each_node_id].distance = current.distance + 1
                node_list[each_node_id].parentID = current.ID
                current.childrenIDs.append(each_node_id)
                q.put(node_list[each_node_id])
    else:
        if count < len(node_list):
            print("Disconnected network!!!")
            return False
    return True


