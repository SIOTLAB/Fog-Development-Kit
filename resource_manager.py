# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA


import manager

import docker
import json
import math
import os
import random
import requests as req
import selectors
import socket
import subprocess
import sys
import time
import timeit
import threading
import types

import topology
import topology_manager

class ResourceManager(manager.Manager):
    """
    ResourceManager manages resources in the network by:
    - Setting up servers used to receive resource data from fog devices
    - Leveraging a TopologyManager to associate resource data with various
      devices across different topologies
    - Leveraging a FlowManager to rewrite flow paths in a topology
    - Using OVSDB (via RESTCONF) to setup queues for specific flows
    - <More stuff here>
    """
    def __init__(self, mgrs, head, ctrlr_ip_addr, swarm=None):
        # Call Manager constructor
        super().__init__(mgrs, head, ctrlr_ip_addr)

        # 1 Tbps max link speed
        self.max_link_speed = 1000000000000

        # Allocated resources - used for deallocation later
        self.allocated_resources = {
            # "edge-node-id": {
            #    "port": {
            #        "src-ip": string,
            #        "dst-ip": string,
            #        "cpu_pct": num,
            #        "mem_mb": num,
            #        "hops": {
            #           "node-id": {
            #              "top-id": string,
            #              "node-id": string,
            #              "ovsdb-id": string,
            #              "br-ovsdb-id": string,
            #              "inport-ofid": string,
            #              "outport-ofid": string,
            #              "queues": [
            #                {
            #                  "queue-name": string,
            #                  "queue-num": string,
            #                  "qos-id": string
            #                },
            #                ....
            #              ],
            #              "table-id": string,
            #              "flow-id": string,
            #            }
            #         }
            #         .. 
            #       ]
            #

            
            # FORMAT EXAMPLE FOR 1 PATH:
            # "<src_ofid>TO<dstofid>": {
            #    "src-ip": string,
            #    "dst-ip": string,
            #    "hops": [
            #       {
            #          "node-id": string,
            #          "ovsdb-id": string,
            #          "br-ovsdb-id": string,
            #          "inport-ofid": string,
            #          "outport-ofid": string,
            #          "queue-id": string,
            #          "queue-name": string,
            #          "table-id": string,
            #          "flow-id": string,
            #       }
            #       ... (more hops)
            #    ]
            # }
        }
        
        if swarm is not None:
            self.swarm = swarm
        else:
            self.swarm = DockerSwarm(ctrlr_ip_addr=ctrlr_ip_addr)

            
    def shutdown(self):
        print("res mgr shutdown")
        super(ResourceManager, self).shutdown()

        # shutdown containers
        self.swarm.remove_all_containers()
            
        # make all nodes leave the swarm
        for top_id in self.mgrs["top"].tops:
            cur_top = self.mgrs["top"].tops[top_id]
            self.swarm.close_swarm(cur_top)
        # Add other shutdown capabilities here
        
        
    def start_link_util(self, top_id="flow:1", interval=1.0):
        """
        start_link_util:
        Starts a thread that retrieves and prints out link utilization
        information once every interval seconds

        notes:
        link = 2-tuple consisting of source and destination port (which are strings)
        Ex: ("openflow:1234:1", "openflow:5678:2")
        """

        self.threads["link_util"] = threading.Thread(target=self.__start_link_util,
                                                     args=(top_id, interval, ))
        self.threads["link_util"].start()                        
        

    def __start_link_util(self, top_id="flow:1", interval=1.0):
        top_mgr = self.mgrs["top"]
        cur_top = top_mgr.get_topology(top_id)
        
        first_run = True # Don't want to print the first run
        while True:
            start_time = timeit.default_timer()
            cur_top.acquire_mutex(sys._getframe().f_code.co_name)
            self.update_bandwidth_data(top_id, interval)
            cur_top.release_mutex(sys._getframe().f_code.co_name)
            # Not sure why we had another thread spinning off here
            # thread = threading.Thread(target=self.update_bandwidth_data,
            #                           args=(top_id, interval, ))
            # thread.start()
            # thread.join()
            elapsed_time = timeit.default_timer() - start_time

            if not first_run:
                top_mgr = self.mgrs["top"]
                # print link util here
                info = top_mgr.get_topology(top_id).get_all_neighbors()
                
                # print(json.dumps(info, indent=3)) 
            else:
                first_run = False

            if elapsed_time > interval:
                fname = sys._getframe().f_code.co_name
                print("{}: ERROR".format(fname), file=sys.stderr)
                return
            else:
                time.sleep(interval - elapsed_time)

                
    # interval is a float and is in seconds
    def update_bandwidth_data(self, top_id, interval):
        self.__update_bandwidth_data(top_id)

        # Keep this seperate from __update_bandwidth_data
        # We want to make all requests first in that function, then update
        # everything here (otherwise updates may happen far apart from each
        # other resulting in inconsistent)
        top_mgr = self.mgrs["top"]
        cur_top = top_mgr.get_topology(top_id)
        
        for node_id in cur_top.get_node_ids():
            for edge in cur_top.get_neighbors(node_id):
                # Get link data from the TopologyManager
                cur_bytes_sent = edge["cur_bytes_sent"]
                cur_bytes_recvd = edge["cur_bytes_recvd"]
                prev_bytes_sent = edge["prev_bytes_sent"]
                prev_bytes_recvd = edge["prev_bytes_recvd"]

                # Calculate link statistics based on the data from TopologyManager
                new_bytes_sent = cur_bytes_sent - prev_bytes_sent
                new_bits_sent = new_bytes_sent * 8
                
                new_bytes_recvd = cur_bytes_recvd - prev_bytes_recvd
                new_bits_recvd = new_bytes_recvd * 8
                
                new_bytes = new_bytes_sent + new_bytes_recvd
                new_bits = new_bytes * 8

                # new_bits / interval -> bits per second on the link
                edge["bps_current"] = new_bits_sent // interval

                # Get link speed information
                src_port_ofid = edge["src_port"]
                if src_port_ofid.startswith("host"):
                    src_port_speed = self.max_link_speed
                else:
                    src_node_id = src_port_ofid.rsplit(":", 1)[0]
                    src_node = cur_top.get_node(src_node_id)
                    src_port_speed = src_node.get_port_speed(src_port_ofid) #kbps
                    src_port_speed *= 1000

                dst_port_ofid = edge["dst_port"]
                if dst_port_ofid.startswith("host"):
                    dst_port_speed = self.max_link_speed
                else:
                    dst_node_id = dst_port_ofid.rsplit(":", 1)[0]
                    dst_node = cur_top.get_node(dst_node_id)
                    dst_port_speed = dst_node.get_port_speed(dst_port_ofid) #kbps
                    dst_port_speed *= 1000

                # Update the capacity of the link
                # NOTE: need to add support for full/half duplex
                edge["bps_capacity"] = min(src_port_speed, dst_port_speed)

                # Update link utilization
                try:
                    ratio = edge["bps_current"] / edge["bps_capacity"] 
                    edge["utilization_pct"] = ratio * 100
                except ZeroDivisionError:
                    # Don't use links not reporting capacity correctly
                    edge["utilization_pct"] = 110

                    if (src_port_speed == 0):
                        cur_top.add_link_reservation(node_id, src_port_ofid,
                                                     self.max_link_speed)
                    if (dst_port_speed == 0):
                        cur_top.add_link_reservation(node_id, dst_port_ofid,
                                                     self.max_link_speed)
                    
        
    def __update_bandwidth_data(self, top_id):
        cur_top = self.mgrs["top"].get_topology(top_id)

        for node_id in cur_top.get_node_ids():
            for edge in cur_top.get_neighbors(node_id):
                # Get the port/link we're updating bandwidth for
                port_ofid = edge["src_port"]
                
                # Then create a URL to get utilization information for the link
                url = ("http://{}:8181/".format(self.ctrlr_ip_addr) +
                       "restconf/operational/" +
                       "opendaylight-inventory:nodes/node/{}/".format(node_id) +
                       "node-connector/{}".format(port_ofid))

                # Make and parse request
                resp = req.get(url, auth=("admin", "admin"), headers=self.head)
                try:
                    # print(json.dumps(resp.json(), indent=3), file=sys.stderr)
                    # index 0 appears to have all information... Not sure why
                    # its in a list
                    # print(url)
                    # print(json.dumps(resp.json(), indent=3))
                    data = resp.json()["node-connector"][0]
                    key = ("opendaylight-port-statistics:"
                           "flow-capable-node-connector-statistics")
                    util_data = data[key]

                except Exception as ex:
                    ex_type = type(ex).__name__
                    fname = sys._getframe().f_code.co_name
                    # print("{}: {} parsing data for {}".format(fname, ex_type, top_id),
                    #       file=sys.stderr)
                    continue

                # Update link information
                # edge["bps_current"] = 0

                # Old way of setting capacity - OVS doesn't appear to display
                # capacity correctly though so instead we are using a different method
                # bps = data["flow-node-inventory:current-speed"] * 1000
                # self.links[link]["bps_capacity"] = bps
                # link_capacity_kbps = data["flow-node-inventory:current-speed"]
                # edge["bps_capacity"] = link_capacity_kbps * 1000
                edge["prev_bytes_sent"] = edge["cur_bytes_sent"]
                edge["prev_bytes_recvd"] = edge["cur_bytes_recvd"]

                bytes_sent = util_data["bytes"]["transmitted"]
                bytes_recvd = util_data["bytes"]["received"]
                edge["cur_bytes_sent"] = bytes_sent
                edge["cur_bytes_recvd"] = bytes_recvd
                # edge["utilization_pct"] = 0.0

                
    def add_link_reservation(self, top_id, node_id, tp_ofid, value):
        """
        Add a reservation to a link.
        This action should be performed after:
        1) A queue has been added to a qos on the port with id tp_ofid
        2) An enqueue flow has been pushed to enqueue packets on the queue
        """
        
        # Get the topology manager
        top_mgr = self.mgrs["top"]

        # Remove the link reservation
        # Get the node + top
        cur_top = top_mgr.get_topology(top_id)
        cur_node = cur_top.get_node(node_id)
        
        # Get tp_ofid and the q rate
        # tp_ofid = cur_node.get_port_from_qos(qos_id)
        # queue = cur_node.get_queue(q_id)

        # Get the max-rate of the queue
        # for config in queue["queues-other-config"]:
        #     if config["queue-other-config-key"] == "max-rate":
        #         max_rate = int(config["queue-other-config-value"])

        # Adjust the link reservation on the node
        cur_top.add_link_reservation(node_id, tp_ofid, value)

            
    # Get resource data for fog nodes
    def start_fog_util(self, top_id="flow:1", interval=1.0):
        self.threads["cpu_util"] = threading.Thread(target=self.__start_fog_util,
                                                    args=(top_id, interval, ))
        self.threads["cpu_util"].start()

        
    def __start_fog_util(self, top_id, interval=1.0):
        top_mgr = self.mgrs["top"]
        cur_top = top_mgr.get_topology(top_id)
        
        HOST = ""
        PORT = 65432
        sel = selectors.DefaultSelector()

        # Create, bind, and listen on socket
        self.socks["cpu_util"] = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socks["cpu_util"].bind((HOST, PORT))
        self.socks["cpu_util"].listen()
        print("listening on", (HOST, PORT))
        self.socks["cpu_util"].setblocking(False)

        # Select self.socks["cpu_util"] for I/O event monitoring 
        sel.register(self.socks["cpu_util"], selectors.EVENT_READ, data=None)

        while True:
            # wait until selector is ready (or timeout expires)
            events = sel.select(timeout=None)

            # For each file object, process
            for key, mask in events:
                if key.data is None:
                    self.accept_connection(key.fileobj, sel)
                else:
                    cur_top.acquire_mutex(sys._getframe().f_code.co_name)
                    self.service_fog(top_id, key, mask, sel)
                    cur_top.release_mutex(sys._getframe().f_code.co_name)

     # Get resource data for fog nodes
    def start_edge_requests(self, top_id="flow:1", interval=1.0):
        self.threads["edge_requests"] = threading.Thread(target=self.__start_edge_requests,
                                                    args=(top_id, interval, ))
        self.threads["edge_requests"].start()

        
    def __start_edge_requests(self, top_id, interval=1.0):
        top_mgr = self.mgrs["top"]
        cur_top = top_mgr.get_topology(top_id)
        
        HOST = ""
        PORT = 65434
        sel = selectors.DefaultSelector()

        # Create, bind, and listen on socket
        self.socks["edge_requests"] = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socks["edge_requests"].bind((HOST, PORT))
        self.socks["edge_requests"].listen()
        print("listening on", (HOST, PORT))
        self.socks["edge_requests"].setblocking(False)

        # Select self.socks["edge_requests"] for I/O event monitoring 
        sel.register(self.socks["edge_requests"], selectors.EVENT_READ, data=None)

        while True:
            # wait until selector is ready (or timeout expires)
            events = sel.select(timeout=None)

            # For each file object, process
            for key, mask in events:
                if key.data is None:
                    self.accept_connection(key.fileobj, sel)
                else:
                    cur_top.acquire_mutex(sys._getframe().f_code.co_name)
                    self.service_edge(top_id, key, mask, sel)
                    cur_top.release_mutex(sys._getframe().f_code.co_name)

                    
    def start_shutdown_requests(self, top_id="flow:1", interval=1.0):
        self.threads["shutdown_requests"] = threading.Thread(target=self.__start_shutdown_requests,
                                                    args=(top_id, interval, ))
        self.threads["shutdown_requests"].start()

        
    def __start_shutdown_requests(self, top_id, interval=1.0):
        top_mgr = self.mgrs["top"]
        cur_top = top_mgr.get_topology(top_id)
        
        HOST = ""
        PORT = 65435
        sel = selectors.DefaultSelector()

        # Create, bind, and listen on socket
        self.socks["shutdown_requests"] = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socks["shutdown_requests"].bind((HOST, PORT))
        self.socks["shutdown_requests"].listen()
        print("listening on", (HOST, PORT))
        self.socks["shutdown_requests"].setblocking(False)

        # Select self.socks["shutdown_requests"] for I/O event monitoring 
        sel.register(self.socks["shutdown_requests"], selectors.EVENT_READ, data=None)

        while True:
            # wait until selector is ready (or timeout expires)
            events = sel.select(timeout=None)

            # For each file object, process
            for key, mask in events:
                if key.data is None:
                    self.accept_connection(key.fileobj, sel)
                else:
                    cur_top.acquire_mutex(sys._getframe().f_code.co_name)
                    self.service_shutdown_request(top_id, key, mask, sel)
                    cur_top.release_mutex(sys._getframe().f_code.co_name)

                    
    # Note: start_greeting_server() and associated greeting functions are
    # reliant on this wrapper. If changing this code, please split changes off
    # into a seperate function so that greetings are not broken.
    def accept_connection(self, sock, sel):
        conn, addr = sock.accept()  # Should be ready to read
        print("accepted connection from", addr)
        conn.setblocking(False)
        data = types.SimpleNamespace(addr=addr, inb=b"", outb=b"")
        #events = selectors.EVENT_READ | selectors.EVENT_WRITE
        events = selectors.EVENT_READ 
        sel.register(conn, events, data=data)

    
    def service_fog(self, top_id, key, mask, sel):
        sock = key.fileobj
        data = key.data
        if mask & selectors.EVENT_READ:
            recv_data = sock.recv(1024)  # Should be ready to read
            if recv_data:
                print("Received", repr(recv_data), "from", data.addr[0])
                raw_data = recv_data.decode()
                resources = raw_data.split()

                # Get current topology according to top_id
                cur_top = self.mgrs["top"].get_topology(top_id)

                # Store HostNode class type in a variable (shorter label)
                for node_id in cur_top.nodes:
                    if(isinstance(cur_top.nodes[node_id], topology.FogNode) and
                       cur_top.nodes[node_id].ip_addr == data.addr[0]):
                        cur_top.nodes[node_id].cpu_util = float(resources[0])
                        cur_top.nodes[node_id].mem_available = float(resources[1])
                        cur_top.nodes[node_id].disk_available = float(resources[2])
                        break
            else:
                print("closing connection to", data.addr)
                sel.unregister(sock)
                sock.close()

                
    def service_edge(self, top_id, key, mask, sel):
        sock = key.fileobj
        data = key.data
        if mask & selectors.EVENT_READ:
            recv_data = sock.recv(1024)  # Should be ready to read
            if recv_data:
                print("Received", repr(recv_data), "from", data.addr[0])
                # Receive request
                raw_data = recv_data.decode()
                request = json.loads(raw_data)

                '''
                Request Format:
                {
                    "node_id": <node id>
                    "image": <image-name>,
                    "cpu": <free cpu %>,
                    "ram": <free ram (MB)>,
                    "disk": <free disk (MB)>,
                    "bandwidth": <free bandwidth (B/sec)>,
                }
                
                Response Format:
                {
                    "resp-code": <0 on success, -1 on failure>,
                    "ip": <fog-ip>,
                    "port": <fog-port>,
                    "failure-msg": <failure message>
                }
                '''

                # Run RAA on request 
                # Below is a crude RAA, simply selects an arbitrary fog node
                cur_top = self.mgrs["top"].get_topology(top_id)
                # get first fog node
                # node_id = next(iter(self.mgrs["res"].swarm.nodes))
                # get random fog node
                # node_id = random.choice(list(self.mgrs["res"].swarm.nodes.keys()))
                # fog_ip = cur_top.nodes[node_id].ip_addr
                # docker_port = cur_top.nodes[node_id].docker_port
                # RAA should return response message
                # A simple response is constructed below
                response = self.resource_allocation_algorithm(request, top_id)
                node_id = response["node_id"]
                fog_ip = response["ip"]
                docker_port = response["port"]
                
                # If success, allocate resources for container
                if response["resp-code"] == 0:
                    resp, service_id = self.swarm.create_container(node_id,
                                                                   request,
                                                                   docker_port)
                    # Check for error while creating container
                    if resp is not True:
                        response["resp-code"] = -1
                        response["failure-msg"] = "Error creating container"
                    else:
                        response["service_id"] = service_id

                # Send success/failure msg to edge node
                sock.sendall(json.dumps(response).encode())
            else:
                print("closing connection to", data.addr)
                sel.unregister(sock)
                sock.close()

                
    def service_shutdown_request(self, top_id, key, mask, sel):
        sock = key.fileobj
        data = key.data
        if mask & selectors.EVENT_READ:
            recv_data = sock.recv(1024)  # Should be ready to read
            if recv_data:
                print("Received", repr(recv_data), "from", data.addr[0])
                # Receive request
                raw_data = recv_data.decode()
                request = json.loads(raw_data)

                # Call shutdown api for deallocating all the resources along path
                # Chris: for right now i am just going to deallocate container
                node_id = request["node_id"]
                service_id = request["service_id"]
                port = request["port"]

                # Resource deallocation algorithm here
                self.resource_deallocation_algorithm(request, top_id)

                # Remove the container
                resp = self.swarm.remove_container(node_id, service_id)

                # create response to send back to edge
                response = {}
                if resp is True:
                    response["resp-code"] = 0
                else:
                    response["resp-code"] = -1

                # Send success/failure msg to edge node
                sock.sendall(json.dumps(response).encode())
            else:
                print("closing connection to", data.addr)
                sel.unregister(sock)
                sock.close()

        
    def distance_vector(self, src_node_id, top_id, required_bandwidth):
        """
        Run the Bellman-Ford distance vector algorithm on the given node in the
        given topology. Return a dictionary, containing the distance vector and
        the parent vector to each node. Parent vector should contain a
        2-tuple. For example, parent[node_1_ofid] = (node_2_ofid,
        node_2_tp_ofid), where node_2_tp_ofid is the OF id of the termination
        point (port) which can be used to DIRECTLY reach node_2 (IE: this port
        has a link directly connecting to node_1)

        Required bandwidth is the bandwidth along a path requested by an edge device.
        """

        # Distance and parent vectors
        distance = {}
        parent = {}

        # Get topology of the switch
        top_mgr = self.mgrs["top"]
        #cur_top_id = top_mgr.get_ovsnode_top_ofid(src_node_id)
        cur_top = top_mgr.get_topology(top_id)

        # Initialize the distance vector (SSSP_0)
        for node_id in cur_top.get_node_ids():
            distance[node_id] = math.inf
        distance[src_node_id] = 0

        # SSSP_i for 1<=i<n
        for i in range(1, cur_top.get_num_nodes()):
            for edge in cur_top.get_all_edges():
                # Maybe calculate the weight here
                available_bandwidth = edge["bps_capacity"] - edge["bps_reserved"]

                try:
                    temp = distance[edge["src_node_id"]] + 1/available_bandwidth
                except ZeroDivisionError:
                    # do not consider links with 0 available bandwidth
                    continue
                
                # If the new path is better AND still supports the bandwidth
                # requirement then update the cost of the path to reflec this
                # better route. Update the parent to reflect this change
                if (distance[edge["dst_node_id"]] > temp and
                    available_bandwidth >= required_bandwidth):
                    # Update distance vector
                    distance[edge["dst_node_id"]] = temp

                    # Update parent vector
                    parent[edge["dst_node_id"]] = {
                        "dst_node_id": edge["dst_node_id"],
                        "dst_port": edge["dst_port"],
                        "src_node_id": edge["src_node_id"], # parent of dst node
                        "src_port": edge["src_port"]
                    }

        return {
            "distance": distance,
            "parent": parent
        }


    def resource_allocation_algorithm(self, edge_req, top_id):
        """
        Fulfill an edge request by allocating resources on the network and fog
        devices.
        """

        # Initialize successful response:
        # Note: not returned if insufficient resources.
        response = {}

        # Other managers
        top_mgr = self.mgrs["top"]
        flow_mgr = self.mgrs["flow"]

        # Get fog node
        cur_top = top_mgr.get_topology(top_id)
        fog_node_ids = cur_top.get_fog_ids()

        # Parse edge request data
        edge_node_id = edge_req["node_id"]
        #fog_port = edge_req["port"]
        img_name = edge_req["image"]
        cpu_pct_req = edge_req["cpu"]
        mem_mb_req = edge_req["ram"]
        bandwidth_bps_req = edge_req["bandwidth"]

        # Get all fog nodes which can service the edge request
        # print("GETTING ALL POSSIBLE FOG NODES WHICH CAN SERVICE EDGE")
        request_servicers = []
        for node_id in fog_node_ids:
            cur_fog_node = cur_top.get_node(node_id)
            if (cur_fog_node.get_cpu_avail_pct() >= cpu_pct_req and
                cur_fog_node.get_mem_avail_mb() >= mem_mb_req):
                request_servicers.append(node_id)

        # Return a bad response when no resources exist for the container
        if len(request_servicers) == 0:
            # print("SENDING FAILURE MSG BACK TO EDGE: NO FOG HAS ENOUGH RESOURCES")
            response["resp-code"] = -1
            response["node_id"] = None
            response["ip"] = None
            response["port"] = None  # self.swarm.generate_port_num(node_id)
            response["service_id"] = None
            response["failure-msg"] = "No fog nodes can satisfy the request."
            return response

        # Run the distance vector algorithm to find good paths to the fog node
        # print("RUNNING DISTANCE VECTOR")
        res = self.distance_vector(edge_node_id, top_id, bandwidth_bps_req)
        # print("DISTANCE VECTOR RETURNED")
        parent = res["parent"]
        distance = res["distance"]

        # Choose the fog node along the path with the greatest amount of
        # bandwidth
        # print("FINDING THE LOWEST COST FOG NODE")
        cheapest_fog_node = {
            "node_id": None,
            "distance": math.inf
        }
        for node_id in request_servicers:
            if distance[node_id] < cheapest_fog_node["distance"]:
                cheapest_fog_node["node_id"] = node_id
                cheapest_fog_node["distance"] = distance[node_id]

        fog_node_id = cheapest_fog_node["node_id"]
        
        # If the cheapest fog node has a distance of infinity, then there
        # exists no path to that node!
        if cheapest_fog_node["distance"] == math.inf:
            # print("SENDING FAILURE MSG BACK TO EDGE: NO PATH EXISTS TO FOG")
            response["resp-code"] = -1
            response["node_id"] = None
            response["ip"] = None
            response["port"] = None # self.swarm.generate_port_num(node_id)
            response["service_id"] = None
            response["failure-msg"] = "Insufficient network bandwidth."
            return response

        fog_port = self.swarm.generate_port_num(fog_node_id)
        
        # AT THIS POINT: The RAA is sucessful. Now we allocate resources.
        # Prepare the allocated_resources dict entry:
        # print("UPDATING ALLOCATED RESOURCE DATA STRUCTURES")
        try:
            self.allocated_resources[edge_node_id][fog_node_id][fog_port] = {}
        except KeyError:
            try:
                self.allocated_resources[edge_node_id][fog_node_id] = {
                    fog_port: {}
                }
            except KeyError:
                self.allocated_resources[edge_node_id] = {
                    fog_node_id: {
                        fog_port: {}
                    }
                }
        alloc = self.allocated_resources[edge_node_id][fog_node_id][fog_port]

        # Initialize all hops for later
        # print("INITIALIZING ALL HOPS")
        alloc["hops"] = {}
        cur = parent[fog_node_id]
        print("\n============================================================\n")
        print("CHOSEN PATH:")
        print(cur["dst_node_id"], end="")
        while True:
            print(" <-> " + cur["src_node_id"], end="")
            # Stop at edge
            if cur["src_node_id"] not in parent:
                break

            cur_node = top_mgr.get_ovsnode(cur["src_node_id"])
            switch_id = cur["src_node_id"]
            alloc["hops"][switch_id] = {
                "top_id": cur_node.top_id,
                "ovsdb_id": cur_node.ovsdb_id,
                "br_ovsdb_id": cur_node.br_ovsdb_id,
                # This is correct - the parent vector format makes naming weird
                "dst_port": cur["src_port"],
                "queues": {},
                "flows": []
            }

            cur = parent[cur["src_node_id"]]

            alloc["hops"][switch_id]["src_port"] = cur["dst_port"]
            
        print()
        print("\n============================================================\n")
        
        # Store data on edge and fog
        fog_node_id = cheapest_fog_node["node_id"]
        fog_node = cur_top.get_node(fog_node_id)
        fog_ip_addr = fog_node.get_ip_addr()
        edge_node = cur_top.get_node(edge_node_id)
        edge_ip_addr = edge_node.get_ip_addr()

        # Formulate response
        response = {}
        response["resp-code"] = 0
        response["edge_node_id"] = edge_node_id
        response["node_id"] = fog_node_id
        response["ip"] = fog_ip_addr
        response["port"] = fog_port
        response["service_id"] = None
        response["failure-msg"] = None
        fog_port = response["port"]
        
        # Allocate fog resources
        alloc["fog_node_id"] = fog_node_id
        alloc["cpu_pct"] = cpu_pct_req
        alloc["mem_mb"] = mem_mb_req
        alloc["bandwidth_bps"] = bandwidth_bps_req
        fog_node.add_reserved_cpu_pct(cpu_pct_req)
        fog_node.add_reserved_mem_mb(mem_mb_req)

        # Traverse the path and allocate resources
        # print("ATTEMPTING TO ALLOCATE RESOURCES")
        cur = parent[fog_node_id]
        num_flows = 0
        while True:
            # For reference
            dst_node_id = cur["dst_node_id"]
            dst_node = cur_top.get_node(dst_node_id)
            dst_port = cur["dst_port"]

            src_node_id = cur["src_node_id"]
            src_port = cur["src_port"]
            src_node = cur_top.get_node(src_node_id)

            # 1. Create Queues to limit bandwidth in 1 direction:
            # Create queue on the src_side (unless it is an edge node)
            # Queue points up (created on top of src node)
            if not isinstance(src_node, topology.EdgeNode):
                src_queue_id = (edge_node_id + "-TO-" +
                                fog_node_id + "-" + str(response["port"]))
                top_mgr.create_queue(src_node_id, src_queue_id, bandwidth_bps_req)

                # QoS Already exists - get the qos_id put the queue on it.
                src_qos_id = "defaultqos" + str(src_port.rsplit(":", 1)[-1])
                top_mgr.add_qos_queue(src_node_id, src_qos_id, src_queue_id)

                # Update alloc
                queues = alloc["hops"][src_node_id]["queues"]
                queues[src_queue_id] = {
                    "queue_num": src_node.get_queue_num(src_qos_id, src_queue_id),
                    "qos_id": src_qos_id
                }

            # 2. Create Queues to limit bandwidth in the other direction:
            # Create queue on the dst side (unless it is the fog node)
            # Queue points down (created on bot of dst node)
            if not isinstance(dst_node, topology.FogNode):
                # Create Queue (edge -> fog)
                dst_queue_id = (fog_node_id + "-TO-" +
                                edge_node_id + "-" + str(response["port"]))
                top_mgr.create_queue(dst_node_id, dst_queue_id, bandwidth_bps_req)

                # QoS Already exists - get the qos_id put the queue on it.
                dst_qos_id = "defaultqos" + str(dst_port.rsplit(":", 1)[-1])
                top_mgr.add_qos_queue(dst_node_id, dst_qos_id, dst_queue_id)

                # Update alloc
                queues = alloc["hops"][dst_node_id]["queues"]
                queues[dst_queue_id] = {
                    "queue_num": dst_node.get_queue_num(dst_qos_id, dst_queue_id),
                    "qos_id": dst_qos_id
                }

            fog_port = str(response["port"])
            # 3. Push flows to reserve the path in 1 direction:
            # Push flow on src side unless its an edge node
            # Flow points up (edge src, fog dst)
            if not isinstance(src_node, topology.EdgeNode):
                flow_prefix = (edge_node_id + "-TO-" +
                               fog_node_id + "-" + fog_port)
                src_queue_num = src_node.get_queue_num(src_qos_id, src_queue_id)
                flow_ids = flow_mgr.create_enqueue_flows(
                    top_id, src_node_id, 0, flow_prefix,
                    edge_ip_addr, fog_ip_addr,
                    src_port, src_queue_id, src_queue_num,
                    fog_port, True, 2000
                )
                # print("RAA CREATED 2 FLOWS ON {}".format(src_node_id))

                # Update alloc
                flows = alloc["hops"][src_node_id]["flows"]
                for flow_id in flow_ids:
                    flows.append(flow_id)

                num_flows += 2
                # Link reservation used to be here

            # 4. Push flows to reserve the path in the other direction:
            # Push flow on dst side unless its a fog node
            # Flow points down (fog src, edge dst)
            if not isinstance(dst_node, topology.FogNode):
                flow_prefix = (fog_node_id + "-TO-" +
                               edge_node_id + "-" + fog_port)
                dst_queue_num = dst_node.get_queue_num(dst_qos_id, dst_queue_id)
                flow_ids = flow_mgr.create_enqueue_flows(
                    top_id, dst_node_id, 0, flow_prefix,
                    fog_ip_addr, edge_ip_addr,
                    dst_port, dst_queue_id, dst_queue_num,
                    fog_port, False, 2000
                )
                # print("RAA CREATED 2 FLOWS ON {}".format(dst_node_id))

                # Update alloc
                flows = alloc["hops"][dst_node_id]["flows"]
                for flow_id in flow_ids:
                    flows.append(flow_id)

                num_flows += 2

                # Link reservation used to be here

            # Reserve the link
            cur_top.add_link_reservation(dst_node_id, dst_port, bandwidth_bps_req)
            cur_top.add_link_reservation(src_node_id, src_port, bandwidth_bps_req)

            # Stop if no parent(next node is edge)
            if cur["src_node_id"] not in parent:
                # print("EXITING RAA")
                break

            cur = parent[cur["src_node_id"]]
            # print("ANOTHER RAA ITER")
            
            
        # print("RAA CREATED {} FLOWS (s/b multiple of 4)".format(num_flows))

        # Update other alloc information
        alloc["edge_ip_addr"] = edge_ip_addr
        alloc["fog_ip_addr"] = fog_ip_addr

        # Return SUCCESS response - Sufficient resources found + allocated
        return response
    

    def resource_deallocation_algorithm(self, edge_req, top_id):
        # Get manager references
        top_mgr = self.mgrs["top"]
        cur_top = top_mgr.get_topology(top_id)
        flow_mgr = self.mgrs["flow"]
        
        # To access alloc
        fog_port = edge_req["port"]
        fog_node_id = edge_req["node_id"]
        edge_node_id = edge_req["edge_node_id"]

        # Get alloc entry for this container
        try:
            alloc = self.allocated_resources[edge_node_id][fog_node_id][fog_port]
        except KeyError:
            # No resources have been allocated
            return

        # Begin extracting data
        # fog_node_id = alloc["fog_node_id"]
        edge_ip_addr = alloc["edge_ip_addr"]
        fog_ip_addr = alloc["fog_ip_addr"]

        # Resource data
        cpu_pct = alloc["cpu_pct"]
        mem_mb = alloc["mem_mb"]
        bandwidth_bps = alloc["bandwidth_bps"]

        # Paths data
        hops = alloc["hops"]

        # Deallocate fog resources
        # - add reservation of each resource negatively
        cur_top = top_mgr.get_topology(top_id)
        fog_node = cur_top.get_node(fog_node_id)
        fog_node.add_reserved_cpu_pct(-cpu_pct)
        fog_node.add_reserved_mem_mb(-mem_mb)

        # Remove the path (before deleting queues):
        # Go through all hops
        for node_id in alloc["hops"]:
            cur_hop = alloc["hops"][node_id]

            # - Delete the associated enqueue flows
            for flow_id in cur_hop["flows"]:
                flow_mgr.delete_flow(node_id, 0, flow_id)                

            # - Deallocate the link by removing queues
            for queue_id in cur_hop["queues"]:
                qos_id = cur_hop["queues"][queue_id]["qos_id"]

                # - Remove queues from QoS'es
                top_mgr.remove_qos_queue(node_id, qos_id, queue_id)

                # - Delete the queues
                top_mgr.delete_queue(node_id, queue_id)

            # Add link reservation of negative bandwidth reservation
            src_port_ofid = alloc["hops"][node_id]["src_port"]
            dst_port_ofid = alloc["hops"][node_id]["dst_port"]
            cur_top.add_link_reservation(node_id, src_port_ofid, -bandwidth_bps)
            cur_top.add_link_reservation(node_id, dst_port_ofid, -bandwidth_bps)


        # Finally deallocate the link on the edge and fog
        cur_top.add_link_reservation(edge_node_id, edge_node_id, -bandwidth_bps)
        cur_top.add_link_reservation(fog_node_id, fog_node_id, -bandwidth_bps)
            
        # Remove the allocated_resources entry:
        del self.allocated_resources[edge_node_id][fog_node_id][fog_port]
        

class DockerSwarm:

    def __init__(self, ctrlr_ip_addr, nodes=None, services=None, join_token=None):
        # Nodes: dictionary mapping node_id  --> swarm node (dictionary) 
        # Services: dictionary mapping node_id --> list of swarm service info (dictionary)
        # Ports: dictionary mapping node_id --> ports currently in use by running containers (list)
        # TODO: create structure for mapping services to edge nodes which requested them
        self.ctrlr_ip_addr = ctrlr_ip_addr
        self.nodes = {}
        self.services = {}
        self.ports = {}
        # Create swarm, making the ctrlr the manager node
        self.join_token = self.init_swarm(ctrlr_ip_addr)
            
    # Initialize swarm on controller
    # Controller is now the manager for the swarm
    # Returns the swarm join token
    def init_swarm(self,manager_ip):
        p1= subprocess.Popen(["docker","swarm","init","--advertise-addr",manager_ip],stdout=subprocess.PIPE)
        p2 = subprocess.Popen(["grep", "--", "--token"],stdin=p1.stdout,stdout=subprocess.PIPE)
        p1.stdout.close()
        # docker swarm join --token <join_token> <manager_ip:port>
        # port is 2377 by default
        join_command = p2.communicate()[0].decode("utf-8")
        str = join_command.split()
        join_token = str[4]
        return (join_token)

    # Make remote client join the swarm
    def join_swarm(self, node_id, fog_ip, fog_port):
        client = docker.APIClient(base_url='tcp://{}:{}'.format(fog_ip,fog_port))
        try:
            resp = client.join_swarm(remote_addrs=[self.ctrlr_ip_addr], join_token=self.join_token)
        except docker.errors.APIError as e:
            print("DockerAPIError: Error while joining swarm")
            if hasattr(e, 'message'):
                print(e.message)
            else:
                print(e)
            # Force it to leave other swarm first and retry joining swarm
            print("Attempting to make: {} leave its current swarm".format(fog_ip))
            self.leave_swarm(fog_ip, fog_port)
            self.join_swarm(node_id, fog_ip, fog_port)
            return

        if resp is not True:
            print("Error: Swarm join request was unsuccessful")
            return

        # Add new swarm node into dictionary
        self.nodes[node_id] = self.get_swarm_node(fog_ip)


    # Make remote client leave the swarm
    def leave_swarm(self, fog_ip, fog_port):
        client = docker.APIClient(base_url='tcp://{}:{}'.format(fog_ip,fog_port))
        try:
            resp = client.leave_swarm()
        except docker.errors.APIError as e:
            print("DockerAPIError: Error while leaving swarm")
            if hasattr(e, 'message'):
                print(e.message)
            else:
                print(e)
            return False

        if resp is not True:
            print("Error: Swarm leave request was unsuccessful")
        # TODO: Remove node from dictionary here. Necessary for a dynamic topology
        return resp

    # Shutdown all swarm membership
    def close_swarm(self, topology):
    
        # Make worker nodes leave swarm
        for node_id, swarm_node  in self.nodes.items():
            fog_ip = swarm_node["Status"]["Addr"]
            print(topology.nodes[node_id])
            docker_port = topology.nodes[node_id].docker_port
            self.leave_swarm(fog_ip, docker_port)
        
        # Make manager node leave swarm
        client = docker.APIClient(base_url='unix://var/run/docker.sock')
        try:
            resp = client.leave_swarm(force=True)
        except docker.errors.APIError as e:
            print("DockerAPIError: Error while closing swarm")
            if hasattr(e, 'message'):
                print(e.message)
            else:
                print(e)
            return

        if resp is not True:
            print("Error: Swarm close request was unsuccessful")

    # List information about nodes in swarm
    # Returns a dictionary or None if an error occurred
    def list_swarm_nodes(self, filters=None):
        client = docker.APIClient(base_url='unix://var/run/docker.sock')
        try:
            resp = client.nodes(filters=filters)
        except docker.errors.APIError as e:
            print("DockerAPIError: Error while listing swarm nodes")
            if hasattr(e, 'message'):
                print(e.message)
            else:
                print(e)
            return None
        return resp

    # Get the swarm node  dictionary for the specified IP
    def get_swarm_node(self, node_ip):
        nodes = self.list_swarm_nodes(filters={"role":"worker"})
        for node in nodes:
            if(node["Status"]["Addr"]==node_ip):
                return node
        print("Warning: Node is not in swarm")

    # Create a docker service
    # This will create one container for the service on the specified node
    # Return (True, service_id) on success, (False, Non) on failure
    def create_container(self, node_id, request, port=None):
        client = docker.APIClient(base_url='unix://var/run/docker.sock')

        # expose port on container
        ports = {}
        if (port == None):
            port = self.generate_port_num(node_id)
        published_port = port
        target_port = port
        protocol = 'tcp'
        publish_mode = 'host'
        port_config_tuple = (target_port, protocol, publish_mode)
        #port_config_tuple = (target_port, None)
        ports[published_port] = port_config_tuple
        endpoint_spec = docker.types.EndpointSpec(ports=ports)
        
        # specify container specs
        port_env = str(port)
        container_spec = docker.types.ContainerSpec(image=request["image"],
                                                    tty=True,
                                                    env={"PORT":port_env})

        # specify resource constraints
        cpu_limit = self.compute_cpu_limit(node_id, request["cpu"]) 
        mem_limit = self.compute_mem_limit(node_id, request["ram"])
        resources = docker.types.Resources(cpu_limit=cpu_limit, mem_limit=mem_limit)

        # place container on specific node
        swarm_id = self.nodes[node_id]["ID"]
        placement = docker.types.Placement(constraints=["node.id=={}".format(swarm_id)]) 

        # consolidate the service configuration
        task_template = docker.types.TaskTemplate(container_spec=container_spec,
                                                  resources=resources,
                                                  placement=placement)

        # Create the container
        try:
            service_key = client.create_service(task_template=task_template,
                                                endpoint_spec=endpoint_spec)
        except docker.errors.APIError as e:
            print("DockerAPIError: Error creating a container")
            if hasattr(e, 'message'):
                print(e.message)
            else:
                print(e)
            return (False, None)

        print("Successfully created swarm service: {}".format(service_key))
        # Check if this is the first service for node_id
        if node_id not in self.services:
            self.services[node_id] = []
            self.ports[node_id] = []
        # Get service info for newly created service
        service_info = self.get_service_info(service_key["ID"])
        while(service_info is None):
            service_info = self.get_service_info(service_key["ID"])
        # Add service info to dictionary
        self.services[node_id].append(service_info)
        # Add port to list of used ports
        self.ports[node_id].append(port)
        return (True, service_key["ID"])

    # Convert from percentage of CPU to NanoCPUs
    # Return NanoCPUs (int) or None
    def compute_cpu_limit(self, node_id, cpu_request):
        if(cpu_request == None):
            return None
        fog_NanoCPUs =self.nodes[node_id]["Description"]["Resources"]["NanoCPUs"]
        service_NanoCPUs = fog_NanoCPUs * (cpu_request/100.0)
        return int(service_NanoCPUs)

    # Convert MB to B
    # Return Bytes (int) or None
    def compute_mem_limit(self, node_id, mem_request):
        if(mem_request == None):
            return None
        return int((mem_request * math.pow(10,6)))

    # Generate a random port not currently being used by the node for another container
    def generate_port_num(self, node_id):
        port = random.randint(1024, 10000)
        # check if node_id has any ports exposed
        if (node_id not in self.ports):
            return port
        
        while(port in self.ports[node_id]):
            port = random.randint(1024, 6000)
        return port
    
    # Inspect service information
    # Return dictionary or None if service_id  doesn't exist
    def get_service_info(self, service_id):
        client = docker.APIClient(base_url='unix://var/run/docker.sock')

        try:
            resp = client.inspect_service(service_id)
        except docker.errors.APIError as e:
            print("DockerAPIError: Error inspecting service")
            if hasattr(e, 'message'):
                print(e.message)
            else:
                print(e)
            return None
        return resp
    
    # Stop and remove a container
    # Return True on success, False on failure
    def remove_container(self, node_id, service_id):
        client = docker.APIClient(base_url='unix://var/run/docker.sock')

        try:
            resp = client.remove_service(service_id)
        except docker.errors.APIError as e:
            print("DockerAPIError: Error removing container")
            if hasattr(e, 'message'):
                print(e.message)
            else:
                print(e)
            return False

        if resp is not True:
            # Which one of these messages belongs herre?
            print("Error: Remove service request was unsuccessful")
            print("Successfully removed swarm service: {}".format(service_id))
            return False
        else:
            # delete service from dictionaries
            for i in range(len(self.services[node_id])):
                if self.services[node_id][i]["ID"] == service_id:
                    # TODO: grab port info and delete the port from
                    # self.ports[node_id]
                    # port =self.services[node_id][i]["Endpoint"]["Spec"]["TargetPort"]
                    del self.services[node_id][i]
                    break
            return True

    def remove_all_containers(self):
        for fog_node_id, fog_services in self.services.items():
            for service in fog_services:
                # Remove service
                resp = self.remove_container(fog_node_id, service["ID"])
                # Retry removing service until request is granted
                while(resp is not True):
                    resp = self.remove_container(fog_node_id, service["ID"])
