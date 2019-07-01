# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA


import fdk
import topology
import manager

import copy
import json
import requests as req
import selectors
import socket
import sys
import time
import timeit
import threading
import types
import math


class TopologyManager(manager.Manager):
    """
    Manages topologies, constantly querying ODL RESTCONF API's and then updating
    them over time (updates are currently WIP). Provides high level API's to
    grab information on the stored topology information, as well as the
    topology according to the ODL operational data store.

    This class:
    Does not write flows to switches (See flow_manager.FlowManager)
    Does not gather/manage resources (See resource_manager.ResourceManager)
    """
    
    def __init__(self, mgrs, head,
                 ctrlr_ip_addr="localhost",
                 open_link_capacity=100000000):
        
        # Call Manager constructor
        super().__init__(mgrs, head, ctrlr_ip_addr)

        # A number which is the reserved bandwidth on all links for any
        # free-flowing traffic. Example: For 1Gbps links, you might set this to
        # 100000000 bits/sec to allocate 10% of all links to any generic traffic
        self.open_link_capacity = open_link_capacity
        
        # Map of topology-id's to actual Topology objects
        self.tops = {}

        # Map of switch OF id's to topology ID's for fast access
        self.switchid_to_oftopid = {}

        # Bridge the information between the real and the OVSDB topologies
        self.ofid_to_ovsdbid = {}
        self.ovsdbid_to_ofid = {}

        # Init and update topology data
        self.network_topology = None
        self.opendaylight_inventory = None

        # Greetings which must still be serviced.
        # Greetings remain unserviced when a device greets the FDK but has not
        # been discovered by ODL
        self.unserviced_greetings = {}

        # Init functions (Moved outside of Constructor - should be called after
        # FlowManager is initialized
        # self.update_topology()
        # self.init_link_qos()
        
        # Debug: print the topology data
        # print(json.dumps(self.network_topology, indent=3))


    def shutdown(self):
        super(TopologyManager, self).shutdown()

        print("top mgr shutdown")
        
        # Release any held mutexes
        for top_id in self.tops:
            cur_top = self.tops[top_id]
            try:
                cur_top.release_mutex(sys._getframe().f_code.co_name)
            except RuntimeError:
                # Already unlocked - do nothing
                pass

        self.shutdown_link_qos()    

        for top_id in self.tops:
            # Attempt to close any open sockets
            for node_id in self.unserviced_greetings[top_id]:
                try:
                    self.unserviced_greetings[top_id][node_id]["socket"].close()
                except BaseException:
                    pass

        # Add other shutdown capabilities here
        
        
    def get_topology(self, top_id):
        """ Return the stored topology object with ID top_id """
        return self.tops[top_id]


    def get_ovsnode_top_ofid(self, node_id):
        cur_node = self.get_ovsnode(node_id)
        return cur_node.top_id
    

    def get_ovsnode(self, node_id):
        """ Return the OVSNode without specifying which topology it is in. """
        
        cur_top_id = self.switchid_to_oftopid[node_id]
        cur_top = self.get_topology(cur_top_id)
        cur_node = cur_top.get_node(node_id)
        return cur_node

    
    # Get all topologies via RESTCONF
    # Returns a list of topologies.
    def query_network_topology(self):
        """ Get all topology information from ODL """
        # URL to grab entire topology
        url = ("http://{}:8181/restconf/operational/"
               "network-topology:network-topology/").format(self.ctrlr_ip_addr)

        # Make the request
        resp = req.get(url, auth=("admin", "admin"), headers=self.head)

        # Parse and get topology
        network_topology = resp.json()["network-topology"]["topology"]
        self.update_network_topology(network_topology)
        
        return self.network_topology


    def update_network_topology(self, data):
        self.network_topology = data


    def query_network_topology_node(self, top_id, node_id):
        url = ("http://{}:8181/restconf/operational/".format(self.ctrlr_ip_addr) +
               "network-topology:network-topology/topology/{}/".format(top_id) +
               "node/{}".format(node_id.replace("/", "%2F")))

        resp = req.get(url, auth=("admin", "admin"), headers=self.head)
        data = resp.json()["node"][0] # check node array, only 1 elem
        return data


    def get_network_topology(self):
        return self.network_topology

    
    def query_opendaylight_inventory(self):
        # Create URL
        url = ("http://{}:8181/restconf/".format(self.ctrlr_ip_addr) +
               "operational/opendaylight-inventory:nodes/")

        # Issue and parse the request
        resp = req.get(url, auth=("admin", "admin"), headers=self.head)
        self.opendaylight_inventory = resp.json()["nodes"]["node"]

        return self.opendaylight_inventory


    def get_opendaylight_inventory(self):
        return self.opendaylight_inventory


    def start_topology_update_thread(self, interval=1.0):
        """ Spin off a thread that will repeatedly query ODL for changes to the
        topology and update the topologies in TopologyManager accordingly """
        self.threads["top_update"] = threading.Thread(
            target=self.__start_topology_update_loop,
            args=(interval, ))
        self.threads["top_update"].start()
        

    def __start_topology_update_loop(self, interval):
        """ Helper function for start_topology_update_thread """
        
        while True:
            start_time = timeit.default_timer()
            self.update_topology()
            # Not sure why we had another thread spinning off here
            # thread = threading.Thread(target=self.update_bandwidth_data,
            #                           args=(top_id, interval, ))
            # thread.start()
            # thread.join()
            elapsed_time = timeit.default_timer() - start_time

            if elapsed_time > interval:
                fname = sys._getframe().f_code.co_name
                print("{} WARNING: update_topology took {}s > {}s (interval)".
                      format(fname, elapsed_time, interval),
                      file=sys.stderr)
                # return
            else:
                time.sleep(interval - elapsed_time)


    def update_topology(self):
        """
        Grab new information and update all topology objects
        """
        
        # Query network-topology and OVSDB API
        # Update according to network-topology data returned
        # Contains nodes, links, etc.
        self.query_network_topology()

        # Go through all OF topologies
        for top in self.network_topology:
            top_id = top["topology-id"]
            if top_id.startswith("flow"):
                # Create a new topology if this one doesn't already exist
                try:
                    self.tops[top_id]
                except KeyError:
                    self.tops[top_id] = topology.Topology(self)

                # Get top data and add any missing nodes (duplicates not added)
                cur_top = self.get_topology(top_id)

                # Add new nodes
                cur_top.acquire_mutex(sys._getframe().f_code.co_name)
                for node_data in top["node"]:
                    node_id = node_data["node-id"]
                    cur_top.add_node(node_data)

                    # Construct switch-to-topology id mapping
                    if isinstance(cur_top.get_node(node_id), topology.OVSNode):
                        self.switchid_to_oftopid[node_id] = top_id

                # # Initialize ARP flows on new switches
                # for node_id in cur_top.get_switch_ids():
                #     flow_mgr = self.mgrs["flow"]
                #     top_id = self.switchid_to_oftopid[node_id]

                #     try:
                #         flow_mgr.flows[node_id][0]
                #     except KeyError:
                #         flow_mgr.init_flows(top_id, 0, 1000)
                    
                cur_top.release_mutex(sys._getframe().f_code.co_name)
                    
                # Check that links exist before attempting to add them
                # For tops w/ 1 switch, a KeyError is raised so this is important
                try:
                    top["link"]
                except KeyError:
                    return

                # Connect the nodes by checking link information
                for link in top["link"]:
                    # src info
                    src_node_id = link["source"]["source-node"]
                    src_is_switch = src_node_id.startswith("openflow")
                    if src_is_switch:
                        src_port = link["source"]["source-tp"]
                    else:
                        src_port = src_node_id

                    # dst info
                    dst_node_id = link["destination"]["dest-node"]
                    dst_is_switch = dst_node_id.startswith("openflow")
                    if dst_is_switch:
                        dst_port = link["destination"]["dest-tp"]
                    else:
                        dst_port = dst_node_id

                    # Add links, specifying the corresponding ports on each device the
                    # ends of the link are connected to. Will not add the link if
                    # it already exists.
                    # cur_top = self.get_topology(top_id)
                    cur_top.acquire_mutex(sys._getframe().f_code.co_name)
                    cur_top.add_link(src_node_id, dst_node_id, src_port, dst_port)
                    cur_top.release_mutex(sys._getframe().f_code.co_name)
                    
        # Query opendaylight-inventory:nodes API and update topologies
        # Contains information on OVSNode ports and flows
        self.query_opendaylight_inventory()
        
        # Go through nodes
        for node in self.opendaylight_inventory:
            node_id = node["id"]
            top_id = self.switchid_to_oftopid[node_id]
            cur_top = self.tops[top_id]
            cur_node = cur_top.get_node(node_id)

            cur_top.acquire_mutex(sys._getframe().f_code.co_name)
            for port in node["node-connector"]:
                # Save the node connector data
                port_ofid = port["id"]
                if port_ofid.endswith("LOCAL"):
                    continue
                
                cur_node.set_node_connector_data(port_ofid, port)

                # Relate the port name to the port ofid in the switch
                port_name = port["flow-node-inventory:name"]
                cur_node.set_portname_to_portofid(port_name, port_ofid)
            cur_top.release_mutex(sys._getframe().f_code.co_name)
                
        # Go through OVSDB topologies AFTER OF topologies
        for top in self.network_topology:
            top_id = top["topology-id"]
            if top_id.startswith("ovsdb"):
                # Go through nodes in ovsdb topology
                for node in top["node"]:
                    # Only consider bridges (OVSNodes)
                    try:
                        # 1-to-1 correspondence between bridge MACs AND OVSNodes
                        br_uuid = node["ovsdb:bridge-uuid"]
                        br_name = node["ovsdb:bridge-name"]
                        br_mac = node["ovsdb:datapath-id"] 
                        br_ovsdb_id = node["node-id"]
                        ovsdb_id = node["node-id"].rsplit("/", 2)[-3]
                        tp_info = node["termination-point"]
                    except KeyError:
                        continue
                    
                    # Each bridge is represented as a node in the openflow topology
                    # So parse bridge name, get MAC addr, and convert to OF id
                    node_id = "openflow:" + str(self.mac_to_int(br_mac))

                    # Find the topology where this node is located in:
                    of_top_id = self.get_of_top_id(top_id) # top_id is an ovsdb top id
                    cur_top = self.get_topology(of_top_id)

                    # Update the node with the appropriate information
                    # Can cause KeyError if manager is set but ctrlr isnt
                    try: 
                        cur_node = cur_top.nodes[node_id]
                    except KeyError:
                        continue

                    cur_top.acquire_mutex(sys._getframe().f_code.co_name)
                    
                    cur_node.node_id = node_id
                    cur_node.top_id = of_top_id
                    cur_node.ovsdb_top_id = top_id
                    cur_node.ovsdb_id = ovsdb_id
                    cur_node.br_ovsdb_id = br_ovsdb_id
                    cur_node.br_uuid = br_uuid
                    cur_node.br_name = br_name
                    cur_node.br_mac = br_mac

                    new_tp = False
                    for tp in tp_info:
                        #print(tp)
                        # Skip bridges and other non-default ports
                        if "ovsdb:interface-type" in tp:
                            continue

                        # Get ofport of some TP
                        try:
                            tp_ofid = node_id + ":" + str(tp["ovsdb:ofport"])
                        except KeyError:
                            # Sometimes 
                            tp_name = tp["ovsdb:name"]
                            tp_ofid = cur_node.get_portofid_from_portname(tp_name)
                            tp_stats = cur_node.get_node_connector_data(tp_ofid)

                            if tp_stats is None:
                                # print("TPOFPORT NOT FOUND ")
                                continue

                            tp_ofid = tp_stats["id"]
                            # print("FOUND " + tp_ofid)

                        # cur_node.port_dict[tp_ofid] = {
                        #     "info": tp,
                        #     "port-qos": {}
                        # }

                        # Skip over ports which are already in the dict
                        # CHANGE: to update fields
                        if tp_ofid in cur_node.port_dict:
                            continue

                        # Otherwise put the new port info in the dict
                        new_tp = True
                        cur_node.set_port_data(tp_ofid, {
                            "termination-point": [
                                tp
                            ]
                        })

                    # Map OVSDB ids to OF ids + vice versa
                    self.ofid_to_ovsdbid[node_id] = ovsdb_id
                    self.ovsdbid_to_ofid[ovsdb_id] = node_id

                    # Not needed since the node data set here is only set here.
                    # But may assist keeping data consistent between threads
                    cur_top.release_mutex(sys._getframe().f_code.co_name)

# ==============================================================================
# Greeting Threads
# ==============================================================================
                    
    def start_unserviced_greeting_handler(self, top_id="flow:1", interval=1.0):
        self.threads["unserviced_greeting_handler"] = threading.Thread(
            target=self.__start_unserviced_greeting_handler,
            args=(top_id, interval, )
        )
        self.threads["unserviced_greeting_handler"].start()


    def __start_unserviced_greeting_handler(self, top_id="flow:1", interval=1.0):
        cur_top = self.get_topology(top_id)
        
        while True:
            try:
                self.unserviced_greetings[top_id]
            except BaseException:
                time.sleep(interval)
                continue
            
            
            serviced_nodes = []
            cur_top.acquire_mutex()

            # Attempt to service all unserviced greetings, if any exist
            for node_id in self.unserviced_greetings[top_id]:
                greeting_data = self.unserviced_greetings[top_id][node_id]
                greeting = greeting_data["greeting"]
                sock = greeting_data["socket"]
                if self.__service_greeting(top_id, sock, greeting, False):
                    # note which nodes are successfully serviced
                    serviced_nodes.append(greeting["node_id"])

            # Stop tracking greeting on successful servicing
            for node_id in serviced_nodes:
                self.untrack_greeting(top_id, node_id)
                
            cur_top.release_mutex()

            # Try again in interval seconds
            time.sleep(interval)

    # Get cpu utilization for fog nodes
    def start_greeting_server(self, top_id="flow:1", interval=1.0):
        """ 
        Spin off a thread that will host the server which receives and
        processes greetings.
        """
        self.threads["greeting"] = threading.Thread(
            target=self.__start_greeting_server,
            args=(top_id, interval, )
        )
        self.threads["greeting"].start()

        
    def __start_greeting_server(self, top_id, interval=1.0):
        HOST = ""
        PORT = 65433
        sel = selectors.DefaultSelector()

        # Create, bind, and listen on socket
        self.socks["greeting"] = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socks["greeting"].bind((HOST, PORT))
        self.socks["greeting"].listen()
        # print("listening on", (HOST, PORT))
        self.socks["greeting"].setblocking(False)

        # Select self.socks["greeting"] for I/O event monitoring 
        sel.register(self.socks["greeting"], selectors.EVENT_READ, data=None)

        while True:
            # wait until selector is ready (or timeout expires)
            events = sel.select(timeout=None)

            # For each file object, process
            for key, mask in events:
                if key.data is None:
                    self.accept_wrapper(key.fileobj, sel)
                else:
                    cur_top = self.get_topology(top_id)
                    cur_top.acquire_mutex(sys._getframe().f_code.co_name)
                    self.service_greeting(top_id, key, mask, sel)
                    cur_top.release_mutex(sys._getframe().f_code.co_name)

                    
    def accept_wrapper(self, sock, sel):
        conn, addr = sock.accept()  # Should be ready to read
        print("accepted connection from", addr)
        conn.setblocking(False)
        data = types.SimpleNamespace(addr=addr, inb=b"", outb=b"")
        #events = selectors.EVENT_READ | selectors.EVENT_WRITE
        events = selectors.EVENT_READ
        try:
            sel.register(conn, events, data=data)
        except KeyError:
            print("Socket is already registered. Exiting")
        
    def service_greeting(self, top_id, key, mask, sel):
        sock = key.fileobj
        data = key.data
        if mask & selectors.EVENT_READ:
            recv_data = sock.recv(1024)  # Should be ready to read
            if recv_data:
                # Decode the data received
                print("Received data from", data.addr[0])
                raw_data = recv_data.decode()
                greeting = json.loads(raw_data)
                print(json.dumps(greeting, indent=3))

                # Attempt to service the greeting
                self.__service_greeting(top_id, sock, greeting, True)

                # send ack for greeting
                # (moved to __service_greeting, only ACKs once greeting is complete)
                # sock.sendall(" ".encode())
            else:
                print("closing connection to", data.addr)
                sel.unregister(sock)
                sock.close()

    def __service_greeting(self, top_id, sock, greeting, should_track=True):
        # Finally store the data in the topology
        cur_top = self.get_topology(top_id) # Get topology

        # Parse request
        try:
            node_id = greeting["node_id"]           
            host_type = greeting["host_type"]
            hostname = greeting["hostname"]
            docker_port = greeting["docker_port"]
        except KeyError:
            fname = sys._getframe().f_code.co_name
            print("{} ERROR - Malformed greeting. Skipping.".
                  format(fname))
            return False
        
        try:
            cur_top.nodes[node_id]
        except KeyError:
            # Greeting received before the topology receives it!
            # Should track it and service later, unless already tracked
            fname = sys._getframe().f_code.co_name
            print(("{} WARNING - ".format(fname) +
                   "{} not in topology {}. ".format(node_id, top_id)))
            
            if should_track:
                self.track_greeting(top_id, sock, greeting)

            # Can't yet service
            return False

        # Update node in the topology
        if host_type == "Fog":
            cur_top.nodes[node_id] = cur_top.nodes[node_id].create_fog_node()
        elif host_type == "Edge":
            cur_top.nodes[node_id] = cur_top.nodes[node_id].create_edge_node()
        else:
            # Bad greeting
            return False

        cur_top.nodes[node_id].hostname = hostname
        cur_top.nodes[node_id].docker_port = docker_port

        # Add Fog nodes to docker swarm
        if(isinstance(cur_top.nodes[node_id], topology.FogNode)):
            fog_ip = cur_top.nodes[node_id].ip_addr
            fog_port = cur_top.nodes[node_id].docker_port
            # TODO: Add docker port for fog node here
            self.mgrs["res"].swarm.join_swarm(node_id, fog_ip, fog_port)
            # get memory limit from swarm node information
            swarm_node = self.mgrs["res"].swarm.nodes[node_id]
            mem_max = int(swarm_node["Description"]["Resources"]["MemoryBytes"])
            cur_top.nodes[node_id].mem_max = int(mem_max/math.pow(10,6)) # convert to MB
            # print(cur_top.nodes[node_id].mem_max)

        # ACK that the greeting has been successful
        sock.sendall(" ".encode())
        return True


    def track_greeting(self, top_id, socket, greeting):
        """
        Tracks a greeting that cannot yet be fulfilled.
        Stores information in unserviced_greetings.
        """
        node_id = greeting["node_id"]
        try:
            self.unserviced_greetings[top_id][node_id] = {
                "greeting": greeting,
                "socket": socket
            }
        except KeyError:
            self.unserviced_greetings[top_id] = {
                node_id: {
                "greeting": greeting,
                "socket": socket
                }
            }


    def untrack_greeting(self, top_id, node_id):
        # self.unserviced_greetings[top_id][node_id]["socket"].close()
        del self.unserviced_greetings[top_id][node_id]

            
# ==============================================================================
# Bandwidth Allocation / QoS / Queue API
#
# Do not attach mutexes to these functions
# The RAA/RDA are wrapped in mutexes
# ==============================================================================
# Full process to remove Bandwidth allocation from a port:
# QoS exists on port, and queues exist on the QoS.
# So then we must:
# - Remove queues from the QoS
# - Delete the queues from the Switch
# - Remove the QoS from the port
# - Delete the QoS


    def is_queue_operational(self, node_id, q_id):
        """
        Return True if the queue is found in the operational data store.
        Return False otherwise.
        """
        of_top_id = self.switchid_to_oftopid[node_id]
        cur_top = self.get_topology(of_top_id)

        cur_node = cur_top.get_node(node_id)
        ovsdb_top_id = cur_node.ovsdb_top_id
        ovsdb_id = cur_node.ovsdb_id
        op_node_data = self.query_network_topology_node(ovsdb_top_id, ovsdb_id)

        try:
            queues = op_node_data["ovsdb:queues"]
        except KeyError:
            return False # Queue not created

        for queue in queues:
            if q_id == queue["queue-id"]:
                return True

        return False


    def is_qos_operational(self, node_id, qos_id):
        """
        Return True if the QoS is found in the operational data store.
        Return False otherwise.
        """
        of_top_id = self.switchid_to_oftopid[node_id]
        cur_top = self.get_topology(of_top_id)

        cur_node = cur_top.get_node(node_id)
        ovsdb_top_id = cur_node.ovsdb_top_id
        ovsdb_id = cur_node.ovsdb_id
        op_node_data = self.query_network_topology_node(ovsdb_top_id, ovsdb_id)

        try:
            qoses = op_node_data["ovsdb:qos-entries"]
        except KeyError:
            return False # Qos not created

        for qos in qoses:
            if qos_id == qos["qos-id"]:
                return True

        return False

    
    def is_queue_on_qos(self, node_id, q_id, qos_id):
        """
        Return True if the queue with id q_id is on the QoS with id qos_id.
        Return False otherwise.
        Results are based on the contents of the operational data store.
        """
        
        of_top_id = self.switchid_to_oftopid[node_id]
        cur_top = self.get_topology(of_top_id)

        cur_node = cur_top.get_node(node_id)
        ovsdb_top_id = cur_node.ovsdb_top_id
        ovsdb_id = cur_node.ovsdb_id
        op_node_data = self.query_network_topology_node(ovsdb_top_id, ovsdb_id)

        try:
            qoses = op_node_data["ovsdb:qos-entries"]
        except KeyError:
            return False # Qos not created

        # Go through QoSes
        for qos in qoses:
            # On a QoS match, check all of its queues
            if qos_id == qos["qos-id"]:
                try:
                    queues = qos["queue-list"]
                except KeyError:
                    return False
                
                for queue in queues:
                    cur_q_id = queue["queue-ref"].rsplit("'", 2)[-2]
                    # print(cur_q_id + " vs " + q_id)
                    if q_id == cur_q_id:
                        return True

        # Note: returns false for nonexistant qos and/or queues (versus
        # throwing error)
        return False

    
    def is_qos_on_tp(self, node_id, tp_ofid):
        """
        Return True if there is SOME QoS on the specified tp with OF id tp_ofid
        Return False otherwise.
        Results are based on the contents of the operational data store.
        """
        of_top_id = self.switchid_to_oftopid[node_id]
        cur_top = self.get_topology(of_top_id)

        cur_node = cur_top.get_node(node_id)
        ovsdb_top_id = cur_node.ovsdb_top_id
        br_ovsdb_id = cur_node.br_ovsdb_id
        op_node_data = self.query_network_topology_node(ovsdb_top_id, br_ovsdb_id)
        
        try:
            tps = op_node_data["termination-point"]
        except KeyError:
            return False # No tps -> no QoS on any tp

        # Go through the tps:
        for tp in tps:
            cur_tp_id = tp["tp-id"]
            try:
                cur_tp_ofid = cur_node.get_portofid_from_portname(cur_tp_id)
            except KeyError:
                continue
            
            # On a match, go through all QoS'es on the tp
            if tp_ofid == cur_tp_ofid:
                try:
                    tp["ovsdb:qos-entry"]
                    return True
                except KeyError:
                    return False

        # Note: returns false for nonexistant qos and/or queues (versus
        # throwing error)
        return False
    
    
    # Functions for creating/deleting queues.
    def get_queue_skeleton(self):
        queue_dict = {
            "ovsdb:queues": [
                {
                    # "queue-id": "q0",
                    "dscp": 25,
                    "queues-other-config": [
                        #{
                        #    "queue-other-config-key": "max-rate",
                        #    "queue-other-config-value": "500000"
                        #}
                    ]
                }
            ]
        }

        return queue_dict

    
    def set_queue_field(self, queue_dict, key, val):
        queue_dict["ovsdb:queues"][0][key] = val
        return queue_dict

    
    def add_queue_other_config(self, queue_dict, key, val):
        if not isinstance(key, str):
            fname = sys._getframe().f_code.co_name
            print(("{} - ERROR: key must be a string".format(fname)),
                  file = sys.stderr)
            return -1

        if not isinstance(val, str):
            fname = sys._getframe().f_code.co_name
            print(("{} - ERROR: val must be a string".format(fname)),
                  file = sys.stderr)
            return -1

        queue_dict["ovsdb:queues"][0]["queues-other-config"].append({
            "queue-other-config-key": key,
            "queue-other-config-value": val
        })

        return queue_dict


    def create_queue(self, node_id, q_id, max_rate):
        """ 
        Create a queue on the OVSNode with node_id.
        Check to confirm creation and make repeated requests until the queue is
        on the node.
        """

        # Create the queue
        # print ("Creating queue {} on node {}".format(q_id, node_id))
        queue_dict = self.__create_queue(node_id, q_id, max_rate)
        
        while True:
            # Check that the creation is successful
            # Concurrency ensured here since we wait before adding another queue
            if self.is_queue_operational(node_id, q_id):
                cur_node = self.get_ovsnode(node_id)
                cur_top = self.get_topology(cur_node.get_top_id())
                cur_node.add_queue(queue_dict)
                break
    

    def __create_queue(self, node_id, q_id, max_rate):
        #ovsdb_top_id, ovsdb_id, q_id, max_rate):
        """ 
        Helper function to create_queue().
        Create a new queue but doesn't double check if it actually exists after.
        """

        # Get the necessary data 
        try:
            top_id = self.switchid_to_oftopid[node_id]
        except KeyError:
            # Not a switch - skip this node
            return

        cur_top = self.tops[top_id]
        cur_node = cur_top.nodes[node_id]
        ovsdb_top_id = cur_node.ovsdb_top_id
        ovsdb_id = cur_node.ovsdb_id

        # Create URL
        url = ("http://{}:8181/restconf/config/".format(self.ctrlr_ip_addr) +
               "network-topology:network-topology/topology/{}/".format(ovsdb_top_id) +
               "node/{}/ovsdb:queues/{}".format(ovsdb_id.replace("/", "%2F"), q_id))

        # Create HTTP body data - the payload
        queue_dict = self.get_queue_skeleton()
        queue_dict = self.set_queue_field(queue_dict, "queue-id", q_id)
        queue_dict = self.add_queue_other_config(queue_dict, "max-rate",
                                                 str(max_rate))

        # Make the request
        resp = req.put(url, auth=("admin", "admin"),
                       headers=self.head, data=json.dumps(queue_dict))

        return queue_dict
        

    def delete_queue(self, node_id, q_id):
        """ Delete a queue on the specified node. It must be an OVSNode. """

        # print ("Deleting queue {} on node {}".format(q_id, node_id))
        
        # Delete the queue
        self.__delete_queue(node_id, q_id)
        
        while True:
            # Exit once queue is no longer operational
            if not self.is_queue_operational(node_id, q_id):
                cur_node = self.get_ovsnode(node_id)
                cur_node.del_queue(q_id)
                break
    
    
    def __delete_queue(self, node_id, q_id):
        """ 
        Helper function to delete_queue(). 
        Deletes a queue but doesn't double check if it still exists after.
        """
        # ovsdb_top_id, ovsdb_id, q_id):
        

        # Get the necessary data
        try:
            top_id = self.switchid_to_oftopid[node_id]
        except KeyError:
            # Not a switch - skip this node
            return

        cur_top = self.tops[top_id]
        cur_node = cur_top.nodes[node_id]
        ovsdb_top_id = cur_node.ovsdb_top_id
        ovsdb_id = cur_node.ovsdb_id

        # Create URL
        url = ("http://{}:8181/restconf/config/".format(self.ctrlr_ip_addr) +
               "network-topology:network-topology/topology/{}/".format(ovsdb_top_id) +
               "node/{}/ovsdb:queues/{}".format(ovsdb_id.replace("/", "%2F"), q_id))

        # Make request
        resp = req.delete(url, auth=("admin", "admin"), headers=self.head)

            
    def get_qos_skeleton(self):
        qos = {
            "ovsdb:qos-entries": [
                {
                    # "qos-id": "qos1",
                    "qos-type": "ovsdb:qos-type-linux-htb",
                    "qos-other-config": [
                        # {
                        #     "other-config-key": "max-rate",
                        #     "other-config-value": "10000000"
                        # }
                    ],
                    "queue-list": [
          #               {
          #                   "queue-number": "0",
          #                   "queue-ref": "/network-topology:network-topology/network-topology:topology[network-topology:topology-id='ovsdb:1']/network-topology:node[network-topology:node-id='ovsdb://uuid/c5686a7b-cf19-4bb1-878f-516527c9ffbc']/ovsdb:queues[ovsdb:queue-id='q0']"
          #               },
          #               {
          #                   "queue-number": "1",
          #                   "queue-ref": "/network-topology:network-topology/network-topology:topology[network-topology:topology-id='ovsdb:1']/network-topology:node[network-topology:node-id='ovsdb://uuid/c5686a7b-cf19-4bb1-878f-516527c9ffbc']/ovsdb:queues[ovsdb:queue-id='q1']"
          #               },
          #               {
        	            
          # "queue-number": "2",
          #                   "queue-ref": "/network-topology:network-topology/network-topology:topology[network-topology:topology-id='ovsdb:1']/network-topology:node[network-topology:node-id='ovsdb://uuid/c5686a7b-cf19-4bb1-878f-516527c9ffbc']/ovsdb:queues[ovsdb:queue-id='2']"
          #               }
                    ]
                }
            ]
        }
        return qos

    
    def set_qos_field(self, qos_dict, key, val):
        """ Set a top-level field in the qos_dict. """        
        qos_dict["ovsdb:qos-entries"][0][key] = val
        return qos_dict

    
    def add_qos_other_config(self, qos_dict, key, val):
        """ Set qos-other-config in qos_dict """
        if not isinstance(key, str):
            fname = sys._getframe().f_code.co_name
            print(("{} - ERROR: key must be a string".format(fname)),
                  file = sys.stderr)
            return -1

        if not isinstance(val, str):
            fname = sys._getframe().f_code.co_name
            print(("{} - ERROR: val must be a string".format(fname)),
                  file = sys.stderr)
            return -1
        
        qos_dict["ovsdb:qos-entries"][0]["qos-other-config"].append({
            "other-config-key": key,
            "other-config-value": val
        })
        return qos_dict


    def create_qos(self, node_id, qos_id, max_rate, qos_dict=None, delete=False):
        """ 
        Create a blank QoS.
        Add queues later using the payload generated here.
        """

        # print ("Creating qos {} on node {}".format(qos_id, node_id))
        # Create the QoS
        temp = self.__create_qos(node_id, qos_id, max_rate, qos_dict)
        qos_dict = temp
            
        while True:
            # Exit if the QoS exists
            if (not delete and self.is_qos_operational(node_id, qos_id)) or delete:
                cur_node = self.get_ovsnode(node_id)
                cur_node.add_qos(qos_dict)
                break            

            
    def __create_qos(self, node_id, qos_id, max_rate, qos_dict=None):
        """
        Helper function to create_qos(). 
        Creates a QoS but doesn't check that it actually exists afterwards
        """
        # print("__create_qos: before mod - Putting qos {} on {}".format(qos_id, node_id))
        # Get the necessary data
        try:
            top_id = self.switchid_to_oftopid[node_id]
        except KeyError:
            # Not a switch - skip this node
            return

        cur_top = self.tops[top_id]
        cur_node = cur_top.nodes[node_id]
        ovsdb_top_id = cur_node.ovsdb_top_id
        ovsdb_id = cur_node.ovsdb_id

        # Create URL
        url = ("http://localhost:8181/restconf/config/" +
               "network-topology:network-topology/" +
               "topology/{}/".format(ovsdb_top_id) +
               "node/{}/".format(ovsdb_id.replace("/", "%2F")) +
               "ovsdb:qos-entries/{}".format(qos_id))

        # Create HTTP data payload
        if qos_dict is None:
            qos_dict = self.get_qos_skeleton()
            qos_dict = self.set_qos_field(qos_dict, "qos-id", qos_id)
            qos_dict = self.add_qos_other_config(qos_dict, "max-rate",
                                                 str(max_rate))
        else:
            # print("QoS {} exists. Modifying.".format(qos_id))
            
            # Remove old max-rate config
            other_config = qos_dict["ovsdb:qos-entries"][0]["qos-other-config"]
            for i in range(0, len(other_config)):
                setting = other_config[i]
                if setting["other-config-key"] == "max-rate":
                    other_config.pop(i)
            
            # Set new max-rate
            qos_dict = self.add_qos_other_config(qos_dict, "max-rate",
                                                 str(max_rate))

        # print("__create_qos: After mod - Putting qos {} on {}".format(qos_id, node_id))
        # print(json.dumps(qos_dict, indent=3))

        resp = req.put(url, auth=("admin", "admin"),
                       headers=self.head, data=json.dumps(qos_dict))

        return qos_dict


    def delete_qos(self, node_id, qos_id):
        """ 
        Delete a QoS. You MUST delete ALL queues on the QoS before this.
        """

        # print ("Deleting qos {} on node {}".format(qos_id, node_id))

        # Delete the qos
        self.__delete_qos(node_id, qos_id)
        
        while True:
            if not self.is_qos_operational(node_id, qos_id):
                cur_node = self.get_ovsnode(node_id)
                cur_node.del_qos(qos_id)
                break
            
        
    def __delete_qos(self, node_id, qos_id):
        """ 
        delete_qos() helper function. 
        Deletes qos but doesn't check if it still exists after. """
        # Get the necessary data
        try:
            top_id = self.switchid_to_oftopid[node_id]
        except KeyError:
            # Not a switch - skip this node
            return

        cur_top = self.tops[top_id]
        cur_node = cur_top.nodes[node_id]
        ovsdb_top_id = cur_node.ovsdb_top_id
        ovsdb_id = cur_node.ovsdb_id

        # Make sure the qos exists and get it
        try:
            qos_dict = copy.deepcopy(cur_node.qos_dict[qos_id])
        except KeyError:
            return
        
        if len(qos_dict["ovsdb:qos-entries"][0]["queue-list"]) != 0:
            fname = sys._getframe().f_code.co_name
            print("{} - ERROR: You MUST delete ALL ".format(fname) +
                  "queues on a QoS before deleting the QoS",
                  file=sys.stderr)
            # print(qos_dict["ovsdb:qos-entries"][0]["queue-list"])
            # print(json.dumps(self.network_topology, indent=3))
            
            return
        
        url = ("http://localhost:8181/restconf/config/" +
               "network-topology:network-topology/" +
               "topology/{}/".format(ovsdb_top_id) +
               "node/{}/".format(ovsdb_id.replace("/", "%2F")) +
               "ovsdb:qos-entries/{}".format(qos_id))

        resp = req.delete(url, auth=("admin", "admin"), headers=self.head)


    def add_qos_queue(self, node_id, qos_id, q_id):
        """ 
        Add a queue to a QoS and push it to a switch.
        Also reserves link bandwidth
        """

        # print ("Putting queue {} on qos {} (node {})".format(q_id, qos_id, node_id))

        # Put the queue on the qos
        self.__add_qos_queue(node_id, qos_id, q_id)

        # Current
        cur_node = self.get_ovsnode(node_id)

        # # Get the node + top
        # cur_node = self.get_ovsnode(node_id)
        # cur_top_id = cur_node.top_id
        # cur_top = self.get_topology(cur_top_id)

        # # Get tp_ofid and the q rate
        # tp_ofid = cur_node.get_port_from_qos(qos_id)
        # queue = cur_node.get_queue(q_id)

        # Wait for the change to take effect
        while True:
            if self.is_queue_on_qos(node_id, q_id, qos_id):
                cur_node.set_queue_on_qos(q_id, qos_id)
                break
            # print("Queue not on the specified QoS...")

        # # Get the max-rate of the queue
        # for config in queue["queues-other-config"]:
        #     if config["queue-other-config-key"] == "max-rate":
        #         max_rate = int(config["queue-other-config-value"])

        # # Adjust the reservation on that port
        # cur_top.add_link_reservation(tp_ofid, max_rate)
        

    def __add_qos_queue(self, node_id, qos_id, q_id):
                      #ovsdb_top_id, ovsdb_id, qos_dict, q_id):
        """
        Helper function to add_qos_queue().
        Adds a QoS to a queue but doesn't double check this afterwards.
        """
        
        # Get the necessary data
        try:
            top_id = self.switchid_to_oftopid[node_id]
        except KeyError:
            # Not a switch - skip this node
            return

        cur_top = self.tops[top_id]
        cur_node = cur_top.nodes[node_id]
        ovsdb_top_id = cur_node.ovsdb_top_id
        ovsdb_id = cur_node.ovsdb_id
        
        # Make sure the qos exists and get it
        try:
            max_rate = cur_node.get_qos_max_rate(qos_id) # max_rate=None w bad qos_id
            qos_dict = copy.deepcopy(cur_node.qos_dict[qos_id])
        except KeyError:
            return
        
        # Find lowest available queue number
        # Construct a set of current queue numbers
        # Then check all numbers from 0 to the length of the queue and add the
        # smallest one not in the queue numbers
        queues = qos_dict["ovsdb:qos-entries"][0]["queue-list"]
        queue_nums = set([])
        for queue in queues:
            queue_nums.add(queue["queue-number"])

        # Go through all queue nums and set the lowest as the q_num
        # Worst case: i = len(queues) is not in the nums (given) and is added
        # Otherwise some smaller q_num is used
        for i in range(0, len(queues) + 1):
            if i not in queue_nums:
                q_num = i

        # Create the queue JSON object
        queue = {
            "queue-number": q_num,
            "queue-ref": (
                "/network-topology:network-topology/network-topology:topology" +
                "[network-topology:topology-id='{}']/".format(ovsdb_top_id) +
                "network-topology:node" +
                "[network-topology:node-id='{}']/".format(ovsdb_id) + 
                "ovsdb:queues[ovsdb:queue-id='{}']".format(q_id)
            )
        }
        qos_dict["ovsdb:qos-entries"][0]["queue-list"].append(queue)
        # print("Putting qos_dict on {}".format(node_id))
        # print(json.dumps(qos_dict, indent=3))

        # Commit the changed dict
        resp = self.create_qos(node_id, qos_id, max_rate, qos_dict)


    def remove_qos_queue(self, node_id, qos_id, q_id):
        """
        Delete a Queue from a QoS and push the change to a switch.
        Also deallocates link bandwidth
        NOTE: Deletion from the rear is the fastest way of deleting all
        queues. No shifting that way.
        """

        # print ("Removing queue {} from qos {} (node {})".format(q_id, qos_id, node_id))
        # Remove the queue from the qos
        self.__remove_qos_queue(node_id, qos_id, q_id)

        cur_node = self.get_ovsnode(node_id)
        # # Remove the link reservation
        # # Get the node + top
        # cur_node = self.get_ovsnode(node_id)
        # cur_top_id = cur_node.top_id
        # cur_top = self.get_topology(cur_top_id)

        # # Get tp_ofid and the q rate
        # tp_ofid = cur_node.get_port_from_qos(qos_id)
        # queue = cur_node.get_queue(q_id)

        # # Get the max-rate of the queue
        # for config in queue["queues-other-config"]:
        #     if config["queue-other-config-key"] == "max-rate":
        #         max_rate = int(config["queue-other-config-value"])

        # # Remove the reservation from the link
        # cur_top.add_link_reservation(tp_ofid, -max_rate)
        
        # Wait for the new change to hit
        while True:
            if not self.is_queue_on_qos(node_id, q_id, qos_id):
                cur_node.unset_queue_on_qos(q_id)
                break
    

    def __remove_qos_queue(self, node_id, qos_id, q_id): # CHANGE 
                         #node_id, qos_dict, q_num):
        """
        Helper function to remove_qos_queue().
        Removes a QoS from a queue but doesn't double check that this is the
        case afterwards.
        """

        # Get the necessary data
        try:
            top_id = self.switchid_to_oftopid[node_id]
        except KeyError:
            # Not a switch - skip this node
            return

        cur_top = self.tops[top_id]
        cur_node = cur_top.nodes[node_id]
        ovsdb_top_id = cur_node.ovsdb_top_id
        ovsdb_id = cur_node.ovsdb_id

        # Make sure the qos exists and get it
        try:
            max_rate = cur_node.get_qos_max_rate(qos_id) # max_rate=None w bad qos_id
            qos_dict = copy.deepcopy(cur_node.qos_dict[qos_id])
        except KeyError:
            return
        
        queue_list = qos_dict["ovsdb:qos-entries"][0]["queue-list"]

        # Remove the queue from the queue_list
        for i in range(0, len(queue_list)):
            cur_queue = queue_list[i]
            if cur_queue["queue-ref"].split("'")[-2] == q_id:
                q_num = i
                queue_list.pop(i)
                break

        # Adjust the queue numbers of all other queues in the QoS
        # Note: This breaks the qos once things are updated
        # for i in range(int(q_num), len(queue_list)):
        #     queue_list[i]["queue-number"] = str(i)

        # Commit the changed dict
        resp = self.create_qos(node_id, qos_id, max_rate, qos_dict, True)
            

    # tp_id = eth0, etc.
    def get_tp_skeleton(self):
        """
        DO NOT USE. Query OVSNode.port_dict[port_ofid]["info"]
        A basic skeleton for termination points. Put your TP on the
        termination-point list and then use it as your body. Only need one tp
        in the list.
        """
        tp_dict = {
            "termination-point": [
                # {
                #     "tp-id": tp_id,
                #     "ovsdb:port-uuid": "f43ad252-d678-4cae-94c4-4302b4e98a24",
                #     "ovsdb:port-external-ids": [
                #         {
                #             "external-id-key": "opendaylight-iid",
                #             "external-id-value": "/network-topology:network-topology/network-topology:topology[network-topology:topology-id='ovsdb:1']/network-topology:node[network-topology:node-id='ovsdb://uuid/c5686a7b-cf19-4bb1-878f-516527c9ffbc/bridge/br0']/network-topology:termination-point[network-topology:tp-id='ens39']"
                #         }
                #     ],
                #     "ovsdb:qos-entry": {
      	        #         "qos-key": "1",
      	        #         "qos-ref": "/network-topology:network-topology/network-topology:topology[network-topology:topology-id='ovsdb:1']/network-topology:node[network-topology:node-id='ovsdb://uuid/c5686a7b-cf19-4bb1-878f-516527c9ffbc']/ovsdb:qos-entries[ovsdb:qos-id='qos1']"
                #     },
                #     "ovsdb:interface-uuid": "c3a796b8-eff4-48e2-ae04-5f5bafcaf1a0",
                #     "ovsdb:name": tp_id
                # }
            ]
        }

        return tp_dict

    
    # tp-id + ovsdb:name - name of port
    # ovsdb:interface-uuid
    # ovsdb:port-uuid
    def set_tp_field(self, tp_dict, key, val):
        tp_dict["termination-point"][0][key] = val
        return tp_dict

    
    def unset_tp_field(self, tp_dict, key):
        del tp_dict["termination-point"][0][key]
        return tp_dict

    
    def get_tp_field(self, tp_dict, key):
        return tp_dict["termination-point"][0][key]


    # br_uuid -> ovsdb_id, port name, port uuid, int uuid, ovsdb top id,
    # qos_id
    # tp is just termination-point aka port
    # ovsdb_top_id: "ovsdb:1"
    # br_uuid: "ovsdb://uuid/123-345-.../bridge/br0" -> ovsdb_id
    # tp_id: "eth0", etc. == ovsdb:name -> int uuid, port uuid
    # qos_id: pick one! 
    def add_qos_to_tp(self, node_id, qos_id, tp_ofid):
        """
        Add the qos with id qos_id to the switch.
        tp_ofid is assumed to be the openflow id of the port
        Example: openflow:123:5 is the tp_ofid of port 5
        """

        # print("Putting qos {} on tp {} (node{})".format(qos_id, tp_ofid, node_id))

        tp_dict = self.__add_qos_to_tp(node_id, qos_id, tp_ofid)
        
        while True:
            if self.is_qos_on_tp(node_id, tp_ofid):
                cur_node = self.get_ovsnode(node_id)
                cur_node.set_port_data(tp_ofid, tp_dict)
                cur_node.set_qos_on_port(qos_id, tp_ofid)
                break
            
    
    def __add_qos_to_tp(self, node_id, qos_id, tp_ofid):
        """
        Helper function to add_qos_to_tp()
        """
        
        # Extract OF portnum from tp_ofid
        ofport = int(tp_ofid.split(":")[-1])
        
        # ovsdb_top_id, br_uuid,
        # Get the necessary data
        try:
            top_id = self.switchid_to_oftopid[node_id]
        except KeyError:
            # Not a switch - skip this node
            return

        cur_top = self.tops[top_id]
        cur_node = cur_top.nodes[node_id]
        ovsdb_top_id = cur_node.ovsdb_top_id
        ovsdb_id = cur_node.ovsdb_id
        br_ovsdb_id = cur_node.br_ovsdb_id
        
        # Find the topology
        cur_top_data = None
        for top in self.network_topology:
            if ovsdb_top_id == top["topology-id"]:
                cur_top_data = top
                break

        # Exit if the topology does not exist
        if cur_top_data is None:
            print("No top data")
            return

        # Search for the bridge
        cur_node_data = None
        for node_data in cur_top_data["node"]:
            if node_data["node-id"] == br_ovsdb_id:
                cur_node_data = node_data
                break

        # Exit if the bridge does not exist
        # (Bridge is considered a node in OVSDB)
        if cur_node_data is None:
            print("No node data: " + br_ovsdb_id)
            # print(json.dumps(cur_top_data, indent=3))
            return

        # Search for the termination point (port)
        cur_tp_data = None
        for tp_data in cur_node_data["termination-point"]:
            try:
                tp_ofport = tp_data["ovsdb:ofport"]
            except KeyError:
                tp_name = tp_data["ovsdb:name"]
                tp_ofid = cur_node.get_portofid_from_portname(tp_name)
                tp_ofport = cur_node.get_portnum_from_portofid(tp_ofid)
            if tp_ofport == ofport:
                cur_tp_data = tp_data

        # Exit if the tp does not exist
        if cur_tp_data is None:
            print("No tp data")
            return

        cur_tp_data = cur_node.port_dict[tp_ofid]

        # Get port uuid and int uuid for request
        port_uuid = self.get_tp_field(cur_tp_data, "ovsdb:port-uuid")

        # Doesnt work
        # int_uuid = self.get_tp_field(cur_tp_data, "ovsdb:interface-uuid")

        # Create body
        tp_dict = copy.deepcopy(cur_tp_data)

        try:
            self.unset_tp_field(tp_dict, "ovsdb:ifindex")
        except KeyError:
            pass
        # del tp_dict["ovsdb:ofport"]
        # tp_dict = self.get_tp_skeleton(tp_ofid)
        # tp_dict = self.set_tp_field(tp_dict, "ovsdb:interface-uuid", int_uuid)
        # tp_dict = self.set_tp_field(tp_dict, "ovsdb:port-uuid", port_uuid)

        tp_id = self.get_tp_field(tp_dict, "ovsdb:name")
        
        external_id_value = (
            "/network-topology:network-topology/network-topology:topology" +
            "[network-topology:topology-id='{}']/".format(ovsdb_top_id) +
            "network-topology:node" +
            "[network-topology:node-id='{}']/".format(br_ovsdb_id) +
            "network-topology:termination-point" +
            "[network-topology:tp-id='{}']".format(tp_id)
        )

        tp_dict = self.set_tp_field(tp_dict, "ovsdb:port-external-ids", [{
            "external-id-key": "opendaylight-iid",
            "external-id-value": external_id_value
        }])

        qos_ref = (
            "/network-topology:network-topology/network-topology:topology" +
            "[network-topology:topology-id='{}']/".format(ovsdb_top_id) +
            "network-topology:node" +
            "[network-topology:node-id='{}']/".format(ovsdb_id) +
            "ovsdb:qos-entries[ovsdb:qos-id='{}']".format(qos_id)
        )

        tp_dict = self.set_tp_field(tp_dict, "ovsdb:qos-entry", {
            "qos-key": "1",
            "qos-ref": qos_ref
        })

        url = ("http://{}:8181/restconf/config/".format(self.ctrlr_ip_addr) +
               "network-topology:network-topology/" +
               "topology/{}/".format(ovsdb_top_id) +
               "node/{}/".format(br_ovsdb_id.replace("/", "%2F")) +
               "termination-point/{}".format(tp_id))

        # tp_dict = { "termination-point": [ tp_dict ] }

        #print(url)
        #print(json.dumps(tp_dict, indent=3))
        resp = req.put(url, auth=("admin", "admin"),
                       headers=self.head, data=json.dumps(tp_dict))
        #print(resp.text)
            
        return tp_dict


    def remove_qos_from_tp(self, node_id, tp_ofid):
        """ Remove ALL QoS from a tp. Does NOT delete the QoS"""

        # print("Removing ALL qos from tp {} (node{})".format(tp_ofid, node_id))
        qos_id = self.__remove_qos_from_tp(node_id, tp_ofid)
        
        while True:
            if not self.is_qos_on_tp(node_id, tp_ofid):
                cur_node = self.get_ovsnode(node_id)
                cur_node.del_port_qos(tp_ofid)
                cur_node.unset_qos(qos_id)
                break

        
    def __remove_qos_from_tp(self, node_id, tp_ofid):
        """
        Helper function to remove_qos_from_tp()
        """
        
        # Get the necessary data
        try:
            top_id = self.switchid_to_oftopid[node_id]
        except KeyError:
            # Not a switch - skip this node
            return

        cur_top = self.get_topology(top_id)
        cur_node = cur_top.get_node(node_id)
        ovsdb_top_id = cur_node.ovsdb_top_id
        ovsdb_id = cur_node.ovsdb_id
        br_ovsdb_id = cur_node.br_ovsdb_id

        tp_dict = copy.deepcopy(cur_node.port_dict[tp_ofid])
        tp_id = self.get_tp_field(tp_dict, "ovsdb:name")
        # Return if no qos exists.
        #print(json.dumps(tp_dict, indent=3))

        # Try to get and unset QoS 
        try:
            #print(json.dumps(tp_dict, indent=3))
            qos_entry = self.get_tp_field(tp_dict, "ovsdb:qos-entry")
            qos_id = qos_entry["qos-ref"].rsplit("'", 2)[-2]
            self.unset_tp_field(tp_dict, "ovsdb:qos-entry")
        except KeyError:
            pass

        # Try to unset ifindex
        try:
            self.unset_tp_field(tp_dict, "ovsdb:ifindex")
        except KeyError:
            pass
        
        # del tp_dict["ovsdb:port-external-ids"]

        url = ("http://{}:8181/restconf/config/".format(self.ctrlr_ip_addr) +
               "network-topology:network-topology/" +
               "topology/{}/".format(ovsdb_top_id) +
               "node/{}/".format(br_ovsdb_id.replace("/", "%2F")) +
               "termination-point/{}".format(tp_id))

        # tp_dict = { "termination-point": [ tp_dict ] }

        resp = req.put(url, auth=("admin", "admin"),
                       headers=self.head, data=json.dumps(tp_dict))
        
        return qos_id


    def init_link_qos(self):
        # Create queues (1 for each qos/port on each switch)
        # Create qoses (1 for each port on each switch)
        # Put qoses on ports
        # ^ NEED TO APPROPRIATELY TRACK THESE DURING EXECUTION FOR shutdown()
        # AND need to add update method to update qos accordingly
        #print(self.switchid_to_oftopid)
        for node_id in self.switchid_to_oftopid:
            top_id = self.switchid_to_oftopid[node_id]
            cur_top = self.tops[top_id]
            cur_node = cur_top.nodes[node_id]
            # print(cur_node.port_dict)
            for tp_ofid in cur_node.port_dict:
                # Get the port num in string form
                tp_dict = cur_node.port_dict[tp_ofid]
                #print(json.dumps(cur_node.port_dict, indent=3))
                try:
                    ofport = str(self.get_tp_field(tp_dict, "ovsdb:ofport"))
                except KeyError:
                    tp_name = str(self.get_tp_field(tp_dict, "ovsdb:name"))
                    tp_ofid = cur_node.get_portofid_from_portname(tp_name)
                    ofport = cur_node.get_portnum_from_portofid(tp_ofid)
                    
                # Create a queue for the port
                queue_id = "default" + str(ofport)
                self.create_queue(node_id, queue_id, self.open_link_capacity)

                #time.sleep(0.1)

                # Create a qos for the port
                qos_id = "defaultqos" + str(ofport)
                port_speed = self.get_port_speed(tp_ofid)
                self.create_qos(node_id, qos_id, port_speed)

                #time.sleep(0.1)
                                
                # Put the queue on the QoS
                self.add_qos_queue(node_id, qos_id, queue_id)

                #time.sleep(0.1)
                
                # Put the queue on the QoS
                self.add_qos_to_tp(node_id, qos_id, tp_ofid)

                #time.sleep(0.1)

                # Reserve the bandwidth on the port
                cur_top.set_link_reservation(tp_ofid, self.open_link_capacity) 

                
    def shutdown_link_qos(self):
        for node_id in self.switchid_to_oftopid:
            # print("shutting down " + str(node_id))

            top_id = self.switchid_to_oftopid[node_id]
            cur_top = self.tops[top_id]
            cur_node = cur_top.nodes[node_id]

            # print(json.dumps(cur_node.port_dict, indent=3))

            # Remove QoSes from ports
            for tp_ofid in cur_node.port_dict.keys():
                #print(cur_node.port_dict.keys())
                self.remove_qos_from_tp(node_id, tp_ofid)
                
                # Undo all reservations
                cur_top.set_link_reservation(tp_ofid, 0) 
            
            #time.sleep(0.1)
            # Remove queues from QoSes
            for queue_id in cur_node.queue_dict.keys():
                qos_id = cur_node.queue_to_qos[queue_id]
                self.remove_qos_queue(node_id, qos_id, queue_id)

            #time.sleep(0.1)

            # print(json.dumps(cur_node.queue_dict, indent=3))
            # Delete queues
            for queue_id in copy.deepcopy(cur_node.queue_dict):
                self.delete_queue(node_id, queue_id)

            #time.sleep(0.1)

            # Delete QoS'es
            # print(json.dumps(cur_node.queue_dict, indent=3))
            for qos_id in copy.deepcopy(cur_node.qos_dict):                
                self.delete_qos(node_id, qos_id)

            #time.sleep(0.1)


# ==============================================================================
# Conversion API (Helps bridge gap between the OVSDB and OF topologies)
# ==============================================================================

    def openflow_id_to_mac(self, node_id):
        return int_to_mac(node_id.split(":")[-1])
        
            
    def mac_to_openflow_id(self, datapath_id):
        return "openflow:" + mac_to_int(datapath_id)

    
    def mac_to_int(self, mac_str):
        mac_str = mac_str.replace(":", "")
        return int(mac_str, 16)


    def int_to_mac(self, int_str):
        if not isinstance(int_str, str):
            try:
                int_str = str(int_str)
            except BaseException:
                fname = sys._getframe().f_code.co_name
                print(("{} - ERROR: int_str should be a string".format(fname)),
                      file = sys.stderr)

        # Get the number in hex
        mac_str = str(int(int_str, 16))

        # Insert colons to convert to mac
        mac_str = ":".join(format(s, "02x") for s in byes.fromhex(mac_str))

        return mac_str

    
    def get_ovsdbid(self, ofid):
        """ Given a OpenFlow node id, return the OVSDB id """
        return self.ofid_to_ovsdbid[ofid]

    
    def get_ofid(self, ovsdbid):
        """ Given a OVSDB id, return the OpenFlow node id """
        return self.ovsdbid_to_ofid[ovsdbid]
    

    def get_ovsdb_top_id(self, of_top_id):
        """ Given an OpenFlow topology ID, return the OVSDB topology id """
        return "ovsdb:" + of_top_id.split(":")[-1]

    
    def get_of_top_id(self, ovsdb_top_id):
        """ Given an OVSDB topology id, return the OpenFlow topology ID """
        return "flow:" + ovsdb_top_id.split(":")[-1]


# ==============================================================================
# Misc.
# ==============================================================================

    # def get_links(self, top_id):
    #     """ Return links and associated info from the topology with ID top_id """
    #     cur_top_data = self.get_topology(top_id)
    #     return cur_top_data.links


    # def get_links_str(self, top_id):
    #     """ Return string-formatted link """
    #     links_str = ""
    #     cur_top_data = self.get_topology(top_id)
    #     for link in cur_top_data.links:
    #         links_str += ("{}: \n{}\n".format(
    #             str(link), json.dumps(cur_top_data.links[link], indent=3)
    #         ))
    #     return links_str

    def get_port_speed(self, port_ofid):
        """
        Return the port speed of the port with the corresponding OF id.
        """ 
        node_id = port_ofid.rsplit(":", 1)[0]
        top_id = self.switchid_to_oftopid[node_id]
        cur_top = self.tops[top_id]
        node = cur_top.get_node(node_id)
        port_speed = node.get_port_speed(port_ofid) #kbps
        port_speed *= 1000
        return port_speed

    def clear_switches(self, top_id):
        """ 
        Clear flows in the switches for the topology with ID top_id.
        Really should belong in flow_manager. I don't know if we are using this yet.
        """
        # Get the topology
        cur_top = self.get_topology(top_id)

        # Get all switch_ids for the topology
        switch_ids = cur_top_data.get_switch_ids()

        # Delete all flows for each node
        cur_top.acquire_mutex(sys._getframe().f_code.co_name)
        for switch_id in switch_ids:
            flow_mgr.delete_all_flows(switch_id)
        cur_top.release_mutex(sys._getframe().f_code.co_name)


    # Given a node_id and port_id, find the interface corresponding to port_id
    def get_interface(self, node_id, port_id):
        if port_id.startswith("openflow"):
            # Make a call to grab information on the port
            url = ("http://{}:8181/restconf/operational/"
                   "opendaylight-inventory:nodes/node/{}/"
                   "node-connector/{}").format(self.ctrlr_ip_addr, node_id, port_id)
            resp = req.get(url, auth=("admin", "admin"), headers=self.head)

            # Parse response
            try:
                data = resp.json()["node-connector"][0]
            except KeyError:
                print("get_interface(): KeyError parsing json",
                      file=sys.stderr)
                return
            except BaseException:
                print("get_interface(): BaseException parsing response",
                      file=sys.stderr)
                return

            # Select interface from the response
            interface = data["flow-node-inventory:name"]
        else:
            interface = "eth0"

        return interface
