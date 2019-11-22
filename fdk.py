# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA

import flow_manager
import resource_manager
import topology_manager

import json
import sys
import time
import signal

# TEMPORARY: Run startup script and set global variables here.
config_file = "fdk_conf.json"

# Read config file
with open(config_file, "r") as f:
    config_data = json.load(f)

# Parse config data to pass to our objects
try:
    ctrlr_ip_addr = config_data["ctrlr_ip_addr"]
    head = config_data["yang_json_header"]
except KeyError:
    print("Error parsing config file {}".format(config_file), sys.stderr)
    exit(0)

def main():
    """
    Main entry point to FDK
    """
    
    # Create the managers
    mgrs = {}
    flow_mgr = flow_manager.FlowManager(mgrs, head, ctrlr_ip_addr)
    top_mgr = topology_manager.TopologyManager(mgrs, head, ctrlr_ip_addr, 40000000)
    res_mgr = resource_manager.ResourceManager(mgrs, head, ctrlr_ip_addr)
    
    mgrs["flow"] = flow_mgr
    mgrs["top"] = top_mgr
    mgrs["res"] = res_mgr
    # Modify the mgrs dict so every Manager can access each other
    
    # Signal Interrupt Handler
    def handler(sig, frame):
        print("\n\n\n=======================\n\n\n")
        print("HANDLING SHUTDOWN")
        print("\n\n\n=======================\n\n\n")

        for mgr_type in mgrs:
            try:
                mgrs[mgr_type].shutdown()
            except BaseException:
                pass

        print("\n\n\n=======================\n\n\n")
        print("IT IS SAFE TO EXIT")
        print("\n\n\n=======================\n\n\n")
        
        sys.exit(0)

    # Initialize FDK
    top_mgr.update_topology()
    top_mgr.init_link_qos()

    # Register signal interrupt
    signal.signal(signal.SIGINT, handler)

    # Start threads
    top_mgr.start_greeting_server()
    top_mgr.start_unserviced_greeting_handler()
    top_mgr.start_topology_update_thread()
    # res_mgr.start_fog_util() # EXPERIMENTAL
    res_mgr.start_link_util("flow:1", 10.0)
    res_mgr.start_edge_requests()
    res_mgr.start_shutdown_requests()
    # flow_mgr.init_topology(1000, 100, 0)
    print("Started servers")

    # Print nodes in topology
    while True:
        time.sleep(5)
        # print(("\n\n ========================================"
        #        "======================================== \n\n"))

        # for top_id in top_mgr.tops:
        #     cur_top = top_mgr.tops[top_id]

        #     for node_id in cur_top.nodes:
        #         node = cur_top.nodes[node_id]
        #         print(str(node) + "\n")

        # print(("\n\n ========================================"
        #        "======================================== \n\n"))
        time.sleep(5)
    

if __name__ == "__main__":
    main()
