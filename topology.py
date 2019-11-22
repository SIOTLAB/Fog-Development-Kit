# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA

import json
import sys
import time
import threading

class Topology:
    def __init__(self, mgr, ctrlr_ip_addr="localhost"):
        # Set the manager of this topology
        self.mgr = mgr
        
        # dict of node info
        # keys: Node ID's
        # ^ Map to a dictionary of node information for the corresponding node
        self.nodes = {}
        self.node_ids = set([])

        # dict of node neighbor info
        # keys: Node ID's
        # Top-level keys: node_id's
        # ^ These correspond to a list of neighbors (and other information like
        # src/dst port) of the node specified by node_id. Its possible to have
        # one neighbor pop up multiple times here, since we may have multiple
        # links connecting two nodes
        # Then bot-level keys are just fields related to that link:
        # src_port_id, dst_port_id, dst_node_id (neighbor id), etc.
        
        self.neighbors = {}

        # dict of links mapping to utilization information
        # keys: 2-tuples of form (src_port, dst_port) <- uniquely ID links
        # ^ these keys map to dicts of the form:
        # {
        # "cur_bytes": current-byte-reading
        # "prev_bytes": previous-byte-reading
        # }
        # Want to access link utilization from neighbors? Then do:
        # src_port = self.neighbors[node_id][x]["src_port"]
        # dst_port = self.neighbors[node_id][x]["dst_port"]
        # Then lookup self.links[(src_port, dst_port)]["utilization"]
        # self.links = {}

        # dict of flow_ids to flow information
        # self.flows = {
        #     "node_id": {
        #        
        #     }
        # }
        self.ctrlr_ip_addr = ctrlr_ip_addr

        # ^ neighbors are connected by links/edges, see add_link(), etc.
        # ^ Also for EVERY neighbor, need src+dst port (used to view
        # bandwidth) -> maybe then use id as key, then "src"+"dst" subkeys map
        # to port ids
        self.max_link_capacity = 10000000  # link capacity
        self.n = 0                     # num nodes
        self.l = 0                     # num links

        # Mutex for topology access and manipulation
        self.mutex = threading.Lock()

      
    # Formats the network topology as a string [Ex: str(topology_object_name)]
    # Very useful for debugging, etc.
    def __str__(self):
        top_str = "Num nodes: {}  |  Num links: {}\n".format(self.n, self.l)
        top_str += ("Neighbor information below."
                    " Format = <node_id>: <list of neighbor node_ids>\n")
        for node_id in self.neighbors:
            top_str += node_id

            # Print IP address and the OVS port for non-OVS devices
            if not node_id.startswith("openflow"):
                top_str += (" (ip_addr={}, ovs_port={})".
                            format(self.nodes[node_id].ip_addr,
                                   self.nodes[node_id].ovs_port))

            top_str += ": ["
            for n in self.neighbors[node_id]:
                top_str += json.dumps(n, indent=3) + ",\n"
                # top_str += ("\n\t" + n["dst_node_id"] + ", " +
                #             n["src_port"] + " -> " + n["dst_port"])

            top_str = top_str.rstrip(",\n") + "]\n\n-----\n\n" # end of neighbor list

        return top_str


    def acquire_mutex(self, fname=None):
        # if fname is not None:
        #     print("{}: LOCK".format(fname))
            
        self.mutex.acquire()


    def release_mutex(self, fname=None):
        # if fname is not None:
        #     print("{}: UNLOCK".format(fname))
            
        self.mutex.release()

    
    def get_link_capacity(self, src_port_ofid, dst_port_ofid):
        """ Return the capacity of the link that tp_ofid is on. """
        src_node_id = src_port_ofid.rsplit(":", 1)[-2]
        for neighbor in self.neighbors[src_node_id]:
            if neighbor["dst_port"] == dst_port_ofid:
                return neighbor["bps_capacity"]

        # Link not found
        raise KeyError


    def get_node_ids(self):
        """
        Return all nodes in the network
        """
        
        return self.node_ids


    def get_all_edges(self):
        """
        Return all edges in the network.
        """
        
        ans = []
        for node_id in self.neighbors:
            for edge_to_neighbor in self.neighbors[node_id]:
                ans.append(edge_to_neighbor)

        return ans


    def get_all_neighbors(self):
        return self.neighbors


    def get_neighbors(self, node_id):
        """
        Return all neighbor entries/outgoing edges from node_id
        """

        return self.neighbors[node_id]

    
    def get_num_links(self):
        return self.l


    def get_num_nodes(self):
        return self.n

    
    def add_link(self, src_node_id, dst_node_id, src_port, dst_port, capacity=10000000):
        """
        Add an edge/link in the topology between two nodes (1 edge for each direction)
        NOTE: Need to add weights for these links corresponding to utilization
        Need to pass capacity as an argument here - Defaults to 10mbits/s
        currently
        """

        # Get function name
        fname = sys._getframe().f_code.co_name
        
        # Do not add the link if the nodes are not in the topology
        if src_node_id not in self.nodes or dst_node_id not in self.nodes:
            #print("{}: Nodes {} and/or {} not found - can't add link".
                  # format(fname, src_node_id, dst_node_id),
                  # file=sys.stderr)
            return

        # Do not add the link if the link already exists
        for i in range(0, len(self.neighbors[src_node_id])):
            neighbor_id = self.neighbors[src_node_id][i]["dst_node_id"]
            if (neighbor_id == dst_node_id and
                self.neighbors[src_node_id][i]["src_port"] == src_port and
                self.neighbors[src_node_id][i]["dst_port"] == dst_port):
                # print("{}: link already exists - exiting".format(fname))
                return

        # Do not add the link if the link already exists
        for i in range(0, len(self.neighbors[dst_node_id])):
            neighbor_id = self.neighbors[dst_node_id][i]["dst_node_id"]
            if (neighbor_id == src_node_id and
                self.neighbors[dst_node_id][i]["src_port"] == dst_port and
                self.neighbors[dst_node_id][i]["dst_port"] == src_port):
                # print("{}: link already exists - exiting".format(fname))
                return

        # Derive src/dst interfaces
        # Want to make a version of this function in the Topology class. Not
        # good architecture
        src_int = self.mgr.get_interface(src_node_id, src_port)
        dst_int = self.mgr.get_interface(dst_node_id, dst_port)
            
        # Destination entry in the topology
        src_entry = {
            "src_node_id": src_node_id,
            "dst_node_id": dst_node_id,
            "src_port": src_port,
            "dst_port": dst_port,
            "src_int": src_int,
            "dst_int": dst_int,
            "bps_reserved": 0,
            "bps_current": 0,
            "bps_capacity": capacity,
            "cur_bytes_sent": 0,
            "cur_bytes_recvd": 0,
            "prev_bytes_sent": 0,
            "prev_bytes_recvd": 0,
            "utilization_pct": 0.0
        }
        self.neighbors[src_node_id].append(src_entry)

        # Destination entry in the topology
        dst_entry = {
            "src_node_id": dst_node_id,
            "dst_node_id": src_node_id,
            "src_port": dst_port,
            "dst_port": src_port,
            "src_int": dst_int,
            "dst_int": src_int,
            "bps_reserved": 0,
            "bps_current": 0,
            "bps_capacity": capacity,
            "cur_bytes_sent": 0,
            "cur_bytes_recvd": 0,
            "prev_bytes_sent": 0,
            "prev_bytes_recvd": 0,
            "utilization_pct": 0.0
        }
        self.neighbors[dst_node_id].append(dst_entry)

        # Add the link to self.links if it does not already exist
        # if ((src_port, dst_port) not in self.links and
        #     (dst_port, src_port) not in self.links):
        #     self.links[(src_port, dst_port)] = src_index
        #     self.links[(dst_port, dst_port)] = dst_index
        
        self.l += 1

        
    # Delete ALL links between 2 nodes
    def del_link(self, src_node_id, dst_node_id):
        # Ensure both nodes exist
        if src_node_id not in self.nodes or dst_node_id not in self.nodes:
            #print("del_link(): Nodes {} or {} not found - can't delete link",
                  # file=sys.stderr)
            return

        # Del src -> dst edge in graph (+ grab node info)
        for i in range(0, len(self.neighbors[src_node_id])):
            if self.neighbors[src_node_id][i]["dst_node_id"] == dst_node_id:
                # Grab port information to remove entry from self.links
                src_port = self.neighbors[src_node_id][i]["src_port"]
                dst_port = self.neighbors[src_node_id][i]["dst_port"]
                
                # Remove neighbor entry
                self.neighbors[src_node_id].pop(i)

        # Del dst -> src edge in graph
        for i in range(0, len(self.neighbors[dst_node_id])):
            if self.neighbors[dst_node_id][i]["dst_node_id"] == src_node_id:
                # Remove neighbor entry
                self.neighbors[dst_node_id].pop(i)

        # Use port info to delete entry in links
        # if (src_port, dst_port) in self.links:
        #     del self.links[(src_port, dst_port)]
        # elif (dst_port, src_port) in self.links:
        #     del self.links[(dst_port, src_port)]
        # else:
        #     fname = sys._getframe().f_code.co_name
        #     #print("{}: ERROR removing entry from self.links".format(fname),
        #           file=sys.stderr)

        # Adjust link counter
        self.l -= 1

        
    def add_link_reservation(self, node_id, tp_ofid, value):
        """
        Adjust a reserved link bandwidth by value bps.
        To reduce a reservation: just add a negative value.
        """

        try:
            # Look for the port
            port = None
            for edge in self.neighbors[node_id]:
                if edge["src_port"] == tp_ofid:
                    port = edge
                    break

            # Stop if the port is down
            if port is None:
                # fname = sys._getframe().f_code.co_name
                # print("{}: Port {} not found. Exiting.".format(fname, tp_ofid))
                return

            # Adjust the link reservation amount
            port["bps_reserved"] += value
        except KeyError:
            pass


    def set_link_reservation(self, tp_ofid, value):
        """
        Adjust a reserved link bandwidth by value bps.
        To reduce a reservation: just add a negative value.
        """

        try:
            # Get the node_id that the port is on
            node_id = tp_ofid.rsplit(":", 1)[-2]

            # Look for the port
            port = None
            for edge in self.neighbors[node_id]:
                if edge["src_port"] == tp_ofid:
                    port = edge

            # Stop if the port is down
            if port is None:
                return

            # Adjust the link reservation amount
            port["bps_reserved"] = value
        except KeyError:
            pass
        
        
    # n should be a node queried from odl.get_topologies()["node"]
    # NOTE: need to add weights to non-OVS nodes corresponding to utilization
    def add_node(self, node):
        # Do not add the node if it already exists
        try:
            node_id = node["node-id"]
            # print("attmepting to add " + node_id)

            # Do not add duplicate node
            if node_id in self.nodes:
                return
            
            # Derive OVSNode Object from ID
            if node_id.startswith("openflow"):
                new_node = OVSNode(node_id)
            # Derive HostNode object from id
            else:
                ip_addr = node["host-tracker-service:addresses"][0]["ip"]
                attachment_point = node["host-tracker-service:attachment-points"][0]["tp-id"]
                attachment_point = attachment_point.rsplit(":", 1)
                ovs_node_id = attachment_point[0]
                ovs_port = attachment_point[1]
                new_node = HostNode(node_id, ip_addr, ovs_node_id, ovs_port)
                
            # Need to differentiate between fog and edge here
            # Why? We only want fog CPU utilization, etc.  
            self.nodes[node_id] = new_node
            self.neighbors[node_id] = [] # list of dicts
            self.node_ids.add(node_id)
            self.n += 1
        except BaseException:
            fname = sys._getframe().f_code.co_name
            #print("{}: Something went wrong - can't add node {}".
                  # format(fname, node["node-id"]), file=sys.stderr)
            return

        
    # Delete the node with id=node_id
    def del_node(self, node_id):
        try:
            # Delete in+outgoing links
            for dst_node_id in self.neighbors[node_id]:
                self.del_link(node_id, dst_node_id)

            # Delete node
            del self.nodes[node_id]
            del self.neighbors[node_id]
            self.node_ids.remove(node_id)

            # Adjust node counter
            self.n -= 1
        except KeyError:
            fname = sys._getframe().f_code.co_name
            #print("{}: Node {} not found - can't delete node".
                  # format(fname, node_id),
                  # file=sys.stderr)
            return
        

    def get_node(self, node_ofid):
        return self.nodes[node_ofid]
    
        
    def get_switch_ids(self):
        """ Return a list of OpenVSwitch node ids in this Topology. """
        switch_ids = []
        
        for node_id in self.nodes:
            if isinstance(self.nodes[node_id], OVSNode):
                switch_ids.append(node_id)

        return switch_ids

    
    def get_host_ids(self):
        """ Return a list of Edge/Fog node id's in this Topology """
        host_ids = []
        
        for node_id in self.nodes:
            if (isinstance(self.nodes[node_id], HostNode)):
                host_ids.append(node_id)
                
        return host_ids

    
    def get_edge_ids(self):
        """ Return a list of EdgeNode id's in this Topology """
        edge_ids = []
        
        for node_id in self.nodes:
            if (isinstance(self.nodes[node_id], EdgeNode)):
                edge_ids.append(node_id)
                
        return edge_ids

    
    def get_fog_ids(self):
        """ Return a list of FogNode id's in this Topology """
        fog_ids = []
        
        for node_id in self.nodes:
            if (isinstance(self.nodes[node_id], FogNode)):
                fog_ids.append(node_id)

        return fog_ids

    
class HostNode:
    def __init__(self, node_id, ip_addr, ovs_node_id, ovs_port, hostname=None):
        self.node_id = node_id
        self.ip_addr = ip_addr
        self.ovs_node_id = ovs_node_id
        self.ovs_port = ovs_port
        self.hostname = hostname


    def get_ip_addr(self):
        return self.ip_addr
        
        
    def create_fog_node(self):
        return FogNode(self.node_id, self.ip_addr, self.ovs_node_id,
                       self.ovs_port, self.hostname)

    
    def create_edge_node(self):
        return EdgeNode(self.node_id, self.ip_addr, self.ovs_node_id,
                       self.ovs_port, self.hostname)

    
    def __str__(self):
        rep = ""
        attrs = vars(self)
        for attr_name in attrs:
            data = attrs[attr_name]
            # if type(data) is dict:
            #     data = json.dumps(data, indent=3)
            rep += "{}: {}\n".format(attr_name, str(data))

        return rep

    
    
class EdgeNode(HostNode):
    def __init__(self, node_id, ip_addr, ovs_node_id, ovs_port, hostname=None):
        super().__init__(node_id, ip_addr, ovs_node_id, ovs_port, hostname)



class FogNode(HostNode):
    def __init__(self, node_id, ip_addr, ovs_node_id, ovs_port, hostname=None,
                 docker_port=None, cpu_util=None, mem_available=None, disk_available=None,
                 cpu_max=100, cpu_reserved=0, mem_max=None, mem_reserved=0,
                 disk_max=None, disk_reserved=0):
        super().__init__(node_id, ip_addr, ovs_node_id, ovs_port, hostname)
        self.docker_port = docker_port
        # Live resource statistics
        self.cpu_util = cpu_util # Percent (50.0, etc)
        self.mem_available = mem_available # mb available
        self.disk_available = disk_available #mb available
        
        # Resource reservation statistics
        # CPU
        self.cpu_max = cpu_max    # Percentage
        self.cpu_reserved = cpu_reserved   # Percentage

        # MEM
        self.mem_max = mem_max    # MB
        self.mem_reserved = mem_reserved   # MB

        # DISK (Not used)
        self.disk_max = disk_max   
        self.disk_reserved = disk_reserved

        
    def get_max_cpu_pct(self):
        return self.cpu_max

    
    def get_reserved_cpu_pct(self):
        return self.cpu_reserved

    
    def add_reserved_cpu_pct(self, val):
        self.cpu_reserved += val

        
    def get_max_mem_mb(self):
        return self.mem_max

    
    def get_reserved_mem_mb(self):
        return self.mem_reserved

    
    def add_reserved_mem_mb(self, val):
        self.mem_reserved += val

        
    def get_max_disk_mb(self):
        return self.disk_max

    
    def get_reserved_disk_mb(self):
        return self.disk_reserved

    
    def add_reserved_disk_mb(self, val):
        self.disk_reserved += val

        
    def get_mem_avail_mb(self):
        return self.mem_max - self.mem_reserved


    def get_disk_avail_mb(self):
        return self.disk_available


    def get_cpu_avail_pct(self):
        return self.cpu_max - self.cpu_reserved


    def get_cpu_used_pct(self):
        return self.cpu_reserved
    

# Technically models an OVS bridge, represented as a single OpenFlow device
class OVSNode:
    def __init__(self, node_id, top_id=None, ovsdb_top_id=None, ovsdb_id=None,
                 br_ovsdb_id=None, br_uuid=None, br_mac=None, br_name=None):
        self.node_id = node_id
        self.top_id = top_id
        self.ovsdb_top_id = ovsdb_top_id
        self.ovsdb_id = ovsdb_id
        self.br_ovsdb_id = br_ovsdb_id
        self.br_uuid = br_uuid # br_uuid != ovsdb_id. Seperate 
        self.br_mac = br_mac # can be converted to node_id
        self.br_name = br_name

        # Stores port information from opendaylight-inventory API
        self.node_connector_data = {} 

        # Store the data used in the HTTP bodies for the link allocation API's
        self.qos_dict = {} # qos json
        self.queue_dict = {} # queues json
        self.port_dict = {} # port json

        # For quick access to data
        self.queue_to_qos = {}
        self.qos_to_port = {}
        self.portname_to_portofid = {}
        

        # Initialize 
        # {
        #     # id is just number - port openflow:1234:0 has id 0
        #     "<port-ofid>": {
        #         # tp data
        #     }
        # }
        
        # Initialize (OLD, really port-data and info are the same.)
        # {
        #     # id is just number - port openflow:1234:0 has id 0
        #     "<port-name>": {
        #         "info": {
        #             # tp info set in topology manager 
        #         }
        #         "port-data": {
        #             # qos json which has queues
        #         }
        #     }
        # }

    def __str__(self):
        rep = ""
        attrs = vars(self)
            
        for attr_name in attrs:
            data = attrs[attr_name]
            # if type(data) is dict:
            #     data = json.dumps(data, indent=3)
            rep += "{}: {}\n".format(attr_name, str(data))

        return rep

    def get_top_id(self):
        return self.top_id
    
    # ==========================================================================
    # MUTATORS
    # ==========================================================================
    def get_queue(self, queue_id):
        return self.queue_dict[queue_id]
    
    def set_queue_on_qos(self, queue_id, qos_id):
        self.queue_to_qos[queue_id] = qos_id

    def get_qos_from_queue(self, queue_id):
        return self.queue_to_qos[queue_id]
        
    def set_qos_on_port(self, qos_id, port_ofid):
        self.qos_to_port[qos_id] = port_ofid #only 1 allowed

    def get_port_from_qos(self, qos_id):
        return self.qos_to_port[qos_id]
            
    def unset_queue_on_qos(self, queue_id):
        try:
            del self.queue_to_qos[queue_id]
        except KeyError:
            pass

        
    def unset_qos(self, qos_id):
        try:
            del self.qos_to_port[qos_id]
        except KeyError:
            pass
    
    
    def add_queue(self, queue):
        """ 
        Add a queue to the OVSNode object. 
        Does not add a queue to a physical switch.
        The queue input should just be the json sent to the controller.
        """

        queue_id = queue["ovsdb:queues"][0]["queue-id"]
        self.queue_dict[queue_id] = queue

        
    def del_queue(self, queue_id):
        """ 
        Remove a queue from the OVSNode object. 
        Does not remove a queue from a physical switch. 
        """
        del self.queue_dict[queue_id]


    def add_qos(self, qos):
        """ 
        Add a qos to the OVSNode object. Updates qos if it already exists.
        Does not add a qos to a physical switch. 
        The qos input should just be the json sent to the controller.
        """
        
        qos_id = qos["ovsdb:qos-entries"][0]["qos-id"]
        self.qos_dict[qos_id] = qos
        
        
    def del_qos(self, qos_id):
        """
        Remove a qos from the OVSNode object. 
        Does not remove a qos from a physical switch. 
        """
        
        del self.qos_dict[qos_id]

        
    def set_port_data(self, port_ofid, qos):
        """
        Set the port data of a node. Add/Remove a QoS to it beforehand.
        """
        
        # qos_id = qos["ovsdb:qos-entries"][0]["qos-id"]
        self.port_dict[port_ofid] = qos

        
    def del_port_qos(self, port_ofid):
        """
        Remove a QoS from a port on the OVSNode object.
        Does not remove a qos from a physical switch port. 
        """
        
        del self.port_dict[port_ofid]["termination-point"][0]["ovsdb:qos-entry"]
        # del self.port_dict[port_ofid]["ovsdb:port-external-ids"]


    def set_node_connector_data(self, port_ofid, stats):
        self.node_connector_data[port_ofid] = stats

        
    def del_node_connector_data(self, port_ofid):
        del self.node_connector_data[port_ofid]


    # ==========================================================================
    # ACCESSORS
    # ==========================================================================

    def set_portname_to_portofid(self, name, ofid):
        self.portname_to_portofid[name] = ofid

        
    def get_portofid_from_portname(self, name):
        return self.portname_to_portofid[name]


    def get_portnum_from_portofid(self, ofid):
        return int(ofid.split(":")[-1])
    

    def get_node_connector_data(self, port_ofid, is_name=False):
        # If port_ofid is given, just do a lookup
        if not is_name:
            return self.node_connector_data[port_ofid]
        # Otherwise, find the port_ofid based on the name
        # NOTE: this should not be used anymore - portname_to_portofid is
        # properly maintained now and should be used instead to get this.
        else:
            try:
                stats = self.portname_to_portofid[port_ofid]
            except KeyError:
                stats = None
                for tp_id in self.node_connector_data:
                    port_stat = self.node_connector_data[tp_id]
                    # #print(json.dumps(port_stat, indent=3))
                    if port_stat["flow-node-inventory:name"] == port_ofid:
                        stats = port_stat
            return stats
                    

    
    def get_port_speed(self, port_ofid):
        try:
            port = self.get_node_connector_data(port_ofid)
            speed = port["flow-node-inventory:current-speed"]

            # For VMs reporting 0 bandwidth speed, assign 1Gbps
            if speed == 0:
                speed = 1000000
                
        except KeyError:
            return None
        
        return speed
    
    
    def get_qos_max_rate(self, qos_id):
        # Get current max-rate (must exist) and re-create QoS
        # #print(json.dumps(self.qos_dict[qos_id], indent=3))
        qos_entries = self.qos_dict[qos_id]["ovsdb:qos-entries"]
        for i in range(0, len(qos_entries)):
            # Find the right qos
            if qos_entries[i]["qos-id"] == qos_id:
                max_rate = None
                other_config = qos_entries[i]["qos-other-config"]
                for setting in other_config:
                    # Find the max-rate
                    if setting["other-config-key"] == "max-rate":
                        max_rate = setting["other-config-value"]
                        break
            
        

        if max_rate is None:
            raise KeyError # bad key qos_id

        return max_rate


    def get_queue_num(self, qos_id, queue_id):
        """
        Return the queue-number of the queue which is on the specified qos.
        Throw KeyError for nonexistant qos_id or queue_id.
        """

        q_num = None
        queues = self.qos_dict[qos_id]["ovsdb:qos-entries"][0]["queue-list"]

        # Go through all queues
        for queue in queues:
            cur_queue_id = queue["queue-ref"].split("'")[-2]
            # If we have a match, get the q_num and break
            if cur_queue_id == queue_id:
                q_num = queue["queue-number"]
                break

        # queue_id is not found in the qos
        if q_num is None:
            #print(json.dumps(self.qos_dict[qos_id], indent=3))
            raise KeyError

        return q_num

    
    def get_queue_ids(self):
        ids = []
        for queue_id in self.queue_dict:
            ids.append(queue_id)

        return ids

    
    def get_qos_ids(self):
        ids = []
        for qos_id in self.qos_dict:
            ids.append(qos_id)

        return ids
        
