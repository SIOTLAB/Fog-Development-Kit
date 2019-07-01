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

# Get MAC address on <interface> and construct the node_id based on it
def get_node_id(interface):
    ifconfig_proc = subprocess.Popen(["ifconfig", interface],
                                     stdout=subprocess.PIPE)
    grep_proc = subprocess.Popen(["grep", "ether"],
                                 stdin=ifconfig_proc.stdout,
                                 stdout=subprocess.PIPE)
    node_id = grep_proc.communicate()[0].decode("utf-8").split()[1].strip()
    return "host:" + node_id


def make_request(ctrlr_ip_addr, ctrlr_port, request):

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Try to connect to controller, exit if can't connect
        print("Attempting to connect to controller", file=sys.stderr)
        try:
            s.connect((ctrlr_ip_addr, ctrlr_port))
        except (ConnectionRefusedError, OSError):
            print(("Error connecting to controller"), file=sys.stderr)
            sys.exit(-1)

        print("Successfully connected to {}".format(ctrlr_ip_addr), file=sys.stderr)

        # Send request
        print("Sending request. . .")
        s.sendall(json.dumps(request).encode())
        print("Successfully sent: \n{}".format(json.dumps(request, indent=3)))
        resp = s.recv(1024)
        resp = json.loads(resp.decode())
        return resp

def request_shutdown(fog_information, ctrlr_ip_addr, ctrlr_port):
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        while True:
            # Try to connect to controller
            print("Attempting to connect to controller", file=sys.stderr)
            try:
                s.connect((ctrlr_ip_addr, ctrlr_port))
                break
            except (ConnectionRefusedError, OSError):
                print(("Error connecting to controller"), file=sys.stderr)
                time.sleep(1)

        print("Successfully connected to {}".format(ctrlr_ip_addr), file=sys.stderr)

        # continue sending shutdown request until it is granted
        while True:
            print("Sending shutdown request. . .")
            s.sendall(json.dumps(fog_information).encode())
            print("Successfully sent: \n{}".format(json.dumps(fog_information, indent=3)))
            resp = s.recv(1024)
            resp = json.loads(resp.decode())
            # check if shutdown request was granted
            if resp["resp-code"] == 0:
                return
    
# time limit in seconds
def send_data_to_fog(fog_information, ctrlr_ip, ctrlr_port, time_limit=None):
    fog_ip = fog_information["ip"]
    fog_port = fog_information["port"]

    # Run iperf successfully once
    return_code = 1
    while (return_code is not 0):
        proc = subprocess.Popen(["iperf3", "-p", str(fog_port), "-c", str(fog_ip)])
        proc.communicate()[0]
        return_code = proc.returncode
        if return_code is not 0:
            time.sleep(0.5)

    # request shutdown after iperf completes successfully
    request_shutdown(fog_information, ctrlr_ip, ctrlr_port)
    
# Test a string to see if it is a valid ip address
def is_valid_ip_addr(addr):
    addr = addr.split(".")
    if len(addr) != 4:
        return False

    for num in addr:
        try:
            num = int(num)  # ValueError if this is not an int
            if num < 0 or num > 255:
                raise ValueError
        except ValueError:
            return False

    return True

def main(args):
    ctrlr_port_requests = 65434
    ctrlr_port_shutdown = 65435

    if len(args) < 3:
        print("Usage: python3 edge_requests.py <Controller IP address> <interface> OPTIONAL: <cpu> <mem> <disk> <bandwidth> <image>", file=sys.stderr)

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

    # Issue a request for the desired service in request["image"] to be instantiated
    resp = make_request(ctrlr_ip_addr, ctrlr_port_requests, request)

    # repeat request until request is granted (if there is a failure)
    while(resp["resp-code"] != 0):
        print("Request denied: {}".format(resp["failure-msg"]),
              file=sys.stderr)
        print("Sending the request again...")
        time.sleep(0.5)
        resp = make_request(ctrlr_ip_addr, ctrlr_port_requests, request)

    print("Request successful. IP: {} PORT: {}".format(resp["ip"],
                                                       resp["port"]), file=sys.stderr)

    # Attempt to start an Iperf client to communicate with the desired service
    # in the fog, which sends a shutdown request after 10 seconds.
    # Similarly, send a shutdown request if Ctrl-C is detected during this time.
    try:
        send_data_to_fog(resp, ctrlr_ip_addr, ctrlr_port_shutdown)
    except KeyboardInterrupt:
        request_shutdown(resp, ctrlr_ip_addr, ctrlr_port_shutdown)
        sys.exit(0)
        
if __name__ == "__main__":
    main(sys.argv)
    
