"""@package docstring
Programmed by the ANEX authors (byline withheld for double-blind review)
Data structure of a network node
"""

class Node:
    ## The constructor
    def __init__(self, ID=0, x=0.0, y=0.0, active_slot= []):
        ## ID of a node
        self.ID = ID
        ## x-axis position
        self.x = x
        ## y-axis position
        self.y = y
        ##active slot
        self.active_slot = active_slot
        ##ID of ancestor
        self.ancestorIDs = []
        ## ID of the parent
        self.parentID = None
        ## list of children
        self.childrenIDs = []
        ## list of descendent nodes
        self.descIDs = []
        ## list of neighbors
        self.neighborIDs = []
        ## list of neighbors in Constraint graph
        self.neighborIDs_gc = []
        ## transmitting time slot

        self.timeslot = None
        ## transmitting channel
        self.channel = None

        ##Calculate minimum delay value of a node with its neighbor from upper layer
        self.delay = 100000

        ##number of neighbors at the current active slot
        self.weight = 0

        ## receiving channel
        self.rx_channel = None
        ## transmitting working period
        self.wp = 0
        ## interference nodes
        self.interfereIDs = []

        ## distance from the source, for building a BFS Tree
        self.distance = 100000
        self.dist = -1

        self.layer = -1         # layer in the SPT

        self.next_layer_neighbors = []
        self.prev_layer_neighbors = []
        self.current_layer_neighbors = []
        self.current_prev_layer_neighbors = []
        self.added = 0
        # for constructing dfs tree:
        self.discovered = False

        #self.mat_dc = -1 # for MAT calculation for duty cycle network