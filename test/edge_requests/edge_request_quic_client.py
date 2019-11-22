# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA

import socket
import sys
import json
import time
import subprocess
import random
import os
from edge_req_lib import *

def main(args):
    ctrlr_port_requests = 65434
    ctrlr_port_shutdown = 65435

    if len(args) < 3:
        print("Usage: python3 edge_request_iperf.py <Controller IP address> "
              "<interface> OPTIONAL: <cpu> <mem> <disk> <bandwidth> <image> "
              "<iperf-duration> <transport_protocol_num> <exposed_service_port>", file=sys.stderr)

    ctrlr_ip_addr = args[1]

    if not is_valid_ip_addr(ctrlr_ip_addr):
        print("Controller IP address is not valid. Exiting.",
              file=sys.stderr) 
        sys.exit(-1)

    edge_node_id = get_node_id(args[2])

    # simple request
    request = {}
    request["node_id"] = edge_node_id
    request["image"] = "testapp"
    request["cpu"] = 50 # 50% 
    request["ram"] = 20 # 20 MB
    request["disk"] = 20 # 20 MB
    request["bandwidth"] = 10000000 # 10 Mb/s
    request["proto_num"] = 6 # TCP transport protocol
    request["service_port"] = 12345 # container port used for communications

    # specific iperf execution time, default is 10 seconds
    iperf_duration = 10
    
# get optional parameters
    if len(args) >= 4:
        request["cpu"] = int(args[3])
    if len(args) >= 5:
        request["ram"] = int(args[4])
    if len(args) >= 6:
        request["disk"] = int(args[5])
    if len(args) >= 7:
        request["bandwidth"] = int(args[6])
    if len(args) >= 8:
        request["image"] = args[7]
    if len(args) >= 9:
        iperf_duration = int(args[8])
    if len(args) >= 10:
        request["proto_num"] = int(args[9])
    if len(args) >= 11:
        request["service_port"] = int(args[10])

    start_time = time.time()
    resp = make_request(ctrlr_ip_addr, ctrlr_port_requests, request)
    total_overhead = time.time() - start_time

    os.environ["FOG_IP"] = str(resp["ip"])
    os.environ["PORT"] = str(resp["port"])
    
    # repeat request until request is granted
    while(resp["resp-code"] != 0):
        print("Request denied: {}".format(resp["failure-msg"]),
              file=sys.stderr)
        print("Sending the request again...")
        time.sleep(0.5)
        start_time = time.time()
        resp = make_request(ctrlr_ip_addr, ctrlr_port_requests, request)
        total_overhead = time.time() - start_time

    print("Request successful. IP: {} PORT: {}".format(resp["ip"],
                                                       resp["port"]), file=sys.stderr)

    # Send total overhead in shutdown request
    try:
        start_quic_client(resp, ctrlr_ip_addr, ctrlr_port_shutdown,
                          total_overhead, start_time)
    except KeyboardInterrupt:
        start_time = time.time()
        request_shutdown(resp, ctrlr_ip_addr, ctrlr_port_shutdown,
                         total_overhead, start_time)
        sys.exit(0)
        
if __name__ == "__main__":
    main(sys.argv)
    
