# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA


import copy
import json
import fdk
import manager
import requests as req
import sys
import topology

class FlowManager(manager.Manager):
    """
    FlowManager is a class that provides an interface to writing flows to
    switches, independently of the specific topology that the switch exists
    within.
    """
    
    def __init__(self, mgrs, head, ctrlr_ip_addr="localhost"):
        # Call Manager constructor
        super().__init__(mgrs, head, ctrlr_ip_addr)

        # A set of switch_id's for quick access
        self.switch_ids = set([])

        # A dictionary of flow ids
        # Top-level keys: node_id's
        # Low-level keys: table_id's
        # Example: flows["openflow:123"]["0"] is a set of all the flows
        # pushed to table "0" of node "openflow:123"
        self.flows = {}

        
    def shutdown(self):
        super(FlowManager, self).shutdown()


        print("flow mgr shutdown")
        self.delete_all_flows()
            
            
        # Add other shutdown capabilities here
        
    def init_topology(self, priority=1000, table_id=0):
        """
        Create flows ON ALL SWITCHES that allow all communications to/from the controller.
        Then create flows on the same switches that drop all traffic.
        
        ctrlr_priority specifies the priority of the flows allowing comms
        to/from the controller.

        drop_priority specifies the priority of the flows that drop all
        background traffic. MUST be lower than ctrlr_priority.
        """

        if drop_priority >= ctrlr_priority:
            fname = sys._getframe().f_code.co_name
            print(("{} - ERROR: ".format(fname) +
                   "drop_priority ({}) > ".format(drop_priority) +
                   "ctrlr_priority ({}).".format(ctrlr_priority)),
                  file = sys.stderr)
            return -1
            
        top_mgr = self.mgrs["top"]

        # Find all OVS nodes
        for top_id in top_mgr.tops:
            cur_top = top_mgr.tops[top_id]
            for node_id in cur_top.nodes:
                cur_node = cur_top.nodes[node_id]

                # If cur_node is an OVS node: Write a flow to it.
                if isinstance(cur_node, topology.OVSNode):
                    self.init_flows(top_id, table_id, priority)
            
    def create_enqueue_flows(self, top_id, node_id, table_id, flow_prefix,
                             src_ip_addr, dst_ip_addr, 
                             outport_ofid, queue_id, queue_num,
                             fog_port, to_fog, priority=2000):
        flow_ids = []

        flow_id = flow_prefix + "TCP"

        # Form skeleton
        payload = self.get_flow_skeleton()
        flow = payload["flow"][0]
        flow["table_id"] = table_id
        flow["priority"] = priority
        flow["id"] = flow_id
        flow["hard-timeout"] = 0
        flow["idle-timeout"] = 0
        flow["instructions"] = {
            "instruction": [
                {
                    "order": 0,
                    "apply-actions": {
                        "action": []
                    }
                }
            ]
        }

        # Match IP protocol
        eth_type = {
            "ethernet-type": {
                "type": "2048"
            }
        }
        self.add_flow_match(payload, "ethernet-match", eth_type)

        # Match Src/dst IP address
        self.add_flow_match(payload, "ipv4-source", src_ip_addr + "/32")
        self.add_flow_match(payload, "ipv4-destination", dst_ip_addr + "/32")

        if to_fog:
            self.add_flow_match(payload, "tcp-destination-port", fog_port)
        else:
            self.add_flow_match(payload, "tcp-source-port", fog_port)
            
        # Match TCP
        self.add_flow_match(payload, "ip-match", {"ip-protocol": 6})

        # Enqueue
        enqueue_type = "set-queue-action"
        enqueue_data = {
            "queue": queue_id,
            "queue-id": int(queue_num)
        }
        self.add_flow_action(payload, enqueue_type, enqueue_data, 0)

        # Output port (Already tried before enqueue - not good)
        action_type = "output-action"
        action_data = {
            "output-node-connector": outport_ofid.rsplit(":", 1)[-1],
            "max-length": "65535"
        }
        self.add_flow_action(payload, action_type, action_data, 1) #0)

        # Create + track the flow
        # print("Creating TCP flow {}".format(flow_id))
        self.create_flow(node_id, table_id, flow_id, payload)
        flow_ids.append(flow["id"])

        if to_fog:
            del payload["flow"][0]["match"]["tcp-destination-port"]
            self.add_flow_match(payload, "udp-destination-port", fog_port)
        else:
            del payload["flow"][0]["match"]["tcp-source-port"]
            self.add_flow_match(payload, "udp-source-port", fog_port)

        # Construct UDP flow
        flow_id = flow_prefix + "UDP"
        flow["id"] = flow_id
        flow["match"]["ip-match"] = {"ip-protocol": 17}

        # Create + track the flow
        # print("Creating UDP flow {}".format(flow_id))
        self.create_flow(node_id, table_id, flow_id, payload)
        flow_ids.append(flow["id"])

        return flow_ids

                    
    def init_flows(self, top_id, table_id, priority=1000):
        """
        Create flows on a switch to allow communications to/from the
        controller, and to drop all other traffic.
        Flows must, for each switch, accept traffic on one port and redirect
        traffic to all other ports. Redirection to ports is random.
        """

        # Get nodes data on the topology with id TOP_ID
        network_topology = self.mgrs["top"].get_network_topology()
        for top_data in network_topology:
            if top_data["topology-id"] == top_id:
                cur_top_node_data = top_data["node"]

        # Go through nodes
        for cur_node_data in cur_top_node_data:
            tps = []
            node_id = cur_node_data["node-id"]
            if not node_id.startswith("openflow"):
                continue

            # print("Pushing flows for {}".format(node_id))
            
            # Go through termination points for this node and collect them in a list
            for tp in cur_node_data["termination-point"]:
                tp_id = tp["tp-id"]
                if not tp_id.endswith("LOCAL"):
                    tps.append(tp_id.split(":")[-1])

            # Now iterate through the list and push flows to the switch
            # redirecting traffic
            i = 0
            j = 1

            # Write flows enabling traffic to and from the controller
            while i < len(tps):
                flow_id = "ArpArpArp-out-" + tps[i]

                # Create the payload
                # Basics
                payload = self.get_flow_skeleton()
                flow = payload["flow"][0]
                flow["table_id"] = table_id
                flow["priority"] = priority
                flow["id"] = flow_id
                flow["hard-timeout"] = 0
                flow["idle-timeout"] = 0
                flow["instructions"] = {
                    "instruction": [
                        {
                            "order": 0,
                            "apply-actions": {
                                "action": []
                            }
                        }
                    ]
                }

                # Match on some incoming port
                self.add_flow_match(payload, "in-port", node_id + ":" + tps[i])
                eth_type = {
                    "ethernet-type": {
                        "type": "2054"
                    }
                }
                self.add_flow_match(payload, "ethernet-match", eth_type)
                # self.add_flow_match(payload, "ip-match", {"ip-protocol": 1})

                # Redirect to all other ports
                order = 0
                oj = j
                while (j != i):
                    action_type = "output-action"
                    # print("j=" + str(j))
                    action_data = {
                        "output-node-connector": tps[j],
                        "max-length": "65535"
                    }
                    self.add_flow_action(payload, action_type, action_data, order)
                    j = (j+1) % len(tps)
                    order += 1

                action_type = "output-action"
                action_data = {
                        "output-node-connector": "CONTROLLER",
                        "max-length": "65535"
                }
                self.add_flow_action(payload, action_type, action_data, order)
                
                # Match packets from the controller
                # self.add_flow_match(payload, "ipv4-source", self.ctrlr_ip_addr + "/32")

                # Push the flow to the controller
                self.create_flow(node_id, table_id, flow_id, payload)

                # debug
                # print("pushing switch flows")
                # print("i=" + str(i) + "\n\n" + json.dumps(payload, indent=3))
                # print(len(payload["flow"][0]["instructions"]["instruction"][0]["apply-actions"]["action"]))
                i += 1


    
# ==============================================================================
# Flow management API's
# ==============================================================================

    def create_flow(self, node_id, table_id, flow_id, flow_json):
        """
        Create a flow on a table on some node, wait for completion, and
        begin tracking the flow.
        """
        # print("CREATING FLOW {} ".format(flow_id) +
        # "| TABLE {} ".format(table_id) +
         #    "| NODE {}".format(node_id))
        
        # Create the flow
        self._create_flow(node_id, table_id, flow_id, flow_json)

        # # Wait until flow is operational
        # while not self.is_flow_operational(node_id, table_id, flow_id):
        #     # Spam flows (overwriting flows is fine...)
        #     self._create_flow(node_id, table_id, flow_id, flow_json)
            
        #     # pass
        #     fname = sys._getframe().f_code.co_name
        #     print(("{}: flow {} not operational. "
        #            "Retrying...").format(fname, flow_id))

        # Track the newly created flow
        self._track_flow(node_id, table_id, flow_id)
        
    def _create_flow(self, node_id, table_id, flow_id, flow_json):
        """ Helper function to create_flow() """
        
        # Create URL
        url = ("http://{}:8181/restconf/config/".format(self.ctrlr_ip_addr) +
               "opendaylight-inventory:nodes/node/{}/".format(node_id) +
               "flow-node-inventory:table/{}/flow/{}/".format(table_id, flow_id))

        # Push the flow to the switch
        resp = req.put(url, auth=("admin", "admin"),
                       headers=self.head, data=json.dumps(flow_json))


    def delete_flow(self, node_id, table_id, flow_id):
        """ 
        Delete a flow from a table on some node, wait for completion, and
        stop tracking the flow.
        """
        # print("DELETING FLOW {} ".format(flow_id) +
          #    "| TABLE {} ".format(table_id) +
           #   "| NODE {}".format(node_id))
        
        # Delete flow from the node
        self._delete_flow(node_id, table_id, flow_id)

        # # Wait until the flow is operational
        # while self.is_flow_operational(node_id, table_id, flow_id):
        #     # Spam delete flow from the node
        #     self._delete_flow(node_id, table_id, flow_id)
            
        #     # pass
        #     fname = sys._getframe().f_code.co_name
        #     print(("{}: flow {} not operational. "
        #            "Re-checking...").format(fname, flow_id))

        # Stop tracking the newly created flow
        self._untrack_flow(node_id, table_id, flow_id)
            
    def _delete_flow(self, node_id, table_id, flow_id):
        """ Helper function to delete_flow() """
        
        # Create URL
        url = ("http://{}:8181/restconf/config/".format(self.ctrlr_ip_addr) +
               "opendaylight-inventory:nodes/node/{}/".format(node_id) +
               "flow-node-inventory:table/{}/flow/{}/".format(table_id, flow_id))

        # Delete the flow from the switch
        resp = req.delete(url, auth=("admin", "admin"), headers=self.head)
        

    def _track_flow(self, node_id, table_id, flow_id):
        """ Add a flow_id to self.flows. Use in other functions. """
        try:
            self.flows[node_id][table_id].add(flow_id)
        except KeyError:
            try:
                self.flows[node_id][table_id] = set([flow_id])
            except KeyError:
                self.flows[node_id] = {
                    table_id: set([flow_id])
                }

                    
    def _untrack_flow(self, node_id, table_id, flow_id):
        """ Remove a flow_id from self.flows. Use in other functions. """
        try:
            # Remove the flow
            # (set.discard() does not raise KeyError, remove does)
            self.flows[node_id][table_id].remove(flow_id)

            # Delete entry for node and top, if no more flows exist
            # if len(self.flows[top_id][node_id]) == 0:
            #     del self.flows[top_id][node_id]
            #     if len(self.flows[top_id]) == 0:
            #         del self.flows[top_id]
        except KeyError:
            fname = sys._getframe().f_code.co_name
            print(("{} - ERROR: invalid top/node/table/flow_id".format(fname)),
                  file = sys.stderr)
            return -1

    def delete_all_flows(self):
        """ Delete all flows INSTALLED BY FDK """
        for node_id in self.flows:
            for table_id in self.flows[node_id]:
                for flow_id in copy.deepcopy(self.flows[node_id][table_id]):
                    self.delete_flow(node_id, table_id, flow_id)

        # Return a dict with information on any desired flow from a switch
    def get_flow(self, node_id, table_id, flow_id):
        url = ("http://{}:8181/restconf/config/".format(self.ctrlr_ip_addr) +
               "opendaylight-inventory:nodes/node/{}/".format(switch_id) +
               "flow-node-inventory:table/{}/flow/{}/".format(table_id, flow_id))

        resp = req.get(url, auth=("admin", "admin"), headers=self.head)
        data = resp.json()

        return data


    # Return list of all flows for a specific ovs node.
    # Each element is a dictionary containing flow information
    def get_all_flows(self, switch_id):
        url = ("http://{}:8181/restconf/config/".format(self.ctrlr_ip_addr) +
               "opendaylight-inventory:nodes/node/{}/".format(switch_id))

        resp = req.get(url, auth=("admin", "admin"), headers=self.head)
        data = resp.json()
        # print(json.dumps(data, indent=3))

        # Grab list of all flows, return None if there are no flows
        try:
            # returns list of flows for node-id in table 0
            flows = data["node"][0]["flow-node-inventory:table"][0]["flow"]
        except KeyError:
            # print("There are no flows for node: {}".format(switch_id))
            return None

        # print(json.dumps(flows,indent=3))
        return flows

    def is_flow_operational(self, node_id, table_id, flow_id):
        """ 
        DEPRECATED. The operational data store is horribly slow on updating
        flows, so we cannot check it to determine if a flow is operational in a
        timely manner.
        Return True if the flow with id flow_id is found on the specified table
        of the given node. Return False otherwise.
        """

        # Create URL
        url = ("http://{}:8181/restconf/operational/".format(self.ctrlr_ip_addr) +
               "opendaylight-inventory:nodes/node/{}/".format(node_id) +
               "flow-node-inventory:table/{}/flow/{}/".format(table_id, flow_id))

        # Query the flow
        resp = req.get(url, auth=("admin", "admin"), headers=self.head)

        if resp.ok:
            # 200 or other good code detected - operational
            return True
        else:
            # 404 or other erroneous code detected - not operational
            return False

                    
# ==============================================================================
# Flow Building API's (Might make a FlowBuilder class w/ all static methods)
# ==============================================================================

    def add_flow_action(self, flow, action_type, action_data, order):
        """
        Add an action to some flow and return it.
        (incomplete but working for now)
        """

        # Error checking
        try:
            flow["flow"][0]["instructions"]["instruction"][0]["apply-actions"]
        except KeyError:
            fname = sys._getframe().f_code.co_name
            print("{} - ERROR: malformed json\n\n" + json.dumps(flow, indent=3))
            return -1

        # Get action list
        instruction = flow["flow"][0]["instructions"]["instruction"]
        action = instruction[0]["apply-actions"]["action"]

        # Create action
        new_action = {
            "order": order,
            action_type: action_data
        }

        # Add action to list
        action.append(new_action)

        return flow

    def add_flow_match(self, flow, key, value):
        """
        Add a match to the flow. You may need to format the value as a
        dictionary.
        """
        try:
            flow["flow"][0]["match"]
        except KeyError:
            flow["flow"][0]["match"] = {}

        flow["flow"][0]["match"][key] = value

        return flow


    def add_flow_instruction(self, flow, key, value, order):
        """
        Add an instruction to the flow. You may need to format the value as a
        dictionary.
        """ 
        try:
            flow["flow"][0]["instructions"]["instruction"]
        except KeyError:
            flow["flow"][0]["instructions"] = {
                "instruction": [

                ]
            }

        flow["flow"][0]["instructions"]["instruction"].append({
            "order": order,
            key: value
        })

        return flow

    def get_flow_skeleton(self):
        """
        Get a basic flow dictionary, then edit it to your liking.
        """

        flow = {
            "flow": [
                {
                    "strict": False,
                    "installHw": False,
                    "barrier": False,
                    "hard-timeout": 0,
                    "idle-timeout": 0,
                    # Be sure to set table_id, id, priority here
                    "match": {
                        # Examples (see init_flows on how to build this):
                        # "ethernet-match": {
                        #     "ethernet-type": {
                        #         "type": 2048
                        #     }
                        # },
                        # "ip-match": {
                        #     "ip-protocol": 1
                        # }
                        # Other match options (ipv4 src/dst, etc) go here
                    },
                    "instructions": {
                        "instruction": [
                            {
                                "order": 0,
                                "apply-actions": {
                                    "action": [
                                        # Actions go here as dicts. Increment
                                        # order for each one.
                                    ]
                                }
                                # Other instructions go here. Increment order
                                # for each one. Search OpenFlow specs for more info.
                            }
                        ]
                    }
                }
            ]
        }

        return flow

