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
import os
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

def request_shutdown(fog_information, ctrlr_ip_addr, ctrlr_port,
                     req_total_overhead, start_time):

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

        fog_information["req_total_overhead"] = req_total_overhead

        # continue sending shutdown request until it is granted
        while True:
            print("Sending shutdown request. . .")
            s.sendall(json.dumps(fog_information).encode())
            print("Successfully sent: \n{}".format(json.dumps(fog_information, indent=3)))
            resp = s.recv(1024)
            total_overhead = time.time() - start_time
            resp = json.loads(resp.decode())
            # check if shutdown request was granted
            if resp["resp-code"] == 0:
                response = {}
                response["shutdown_total_overhead"] = total_overhead
                response["req_id"] = fog_information["req_id"]
                s.sendall(json.dumps(response).encode())
                return

# All params are passed to the go process using environment variables
def start_quic_client(fog_information, ctrlr_ip, ctrlr_port,
                      total_overhead, start_time):
    cmd = [os.environ["HOME"] + "/fog-development-kit/test/quic_client/quic_client"]
    proc = subprocess.Popen(cmd)
    proc.communicate()[0]

    start_time = time.time()
    request_shutdown(fog_information, ctrlr_ip, ctrlr_port, total_overhead, start_time)
    
    return

# All params are passed to the go process using environment variables
def start_test_quic_client(fog_information, ctrlr_ip, ctrlr_port,
                           total_overhead, start_time):
    cmd = [os.environ["HOME"] + "/fog-development-kit/test/test_quic_client/test_quic_client"]
    proc = subprocess.Popen(cmd)
    proc.communicate()[0]

    start_time = time.time()
    request_shutdown(fog_information, ctrlr_ip, ctrlr_port, total_overhead, start_time)
    
    return

# time limit in seconds
def send_data_to_fog(edge_request, fog_information, ctrlr_ip, ctrlr_port, time_limit=None,
                     total_overhead=None, iperf_duration=10):
    fog_ip = fog_information["ip"]
    fog_port = fog_information["port"]
    proto_num = edge_request["proto_num"]
    
    if proto_num != 6 and proto_num != 17:
        print("Error: protocol number " + str(proto_num) + " detected. " +
              "Must be 6 (TCP) or 17 (UDP).")

    # Default duration if it is not specified.
    if(iperf_duration is None):
        iperf_duration = 10

    # Run iperf successfully once
    return_code = 1
    while (return_code is not 0):
        cmd = ["iperf3","-t", str(iperf_duration),
               "-p", str(fog_port), "-c", str(fog_ip)]

        # Use UDP if protocol number is 17 and specify the desired bandwidth so
        # no/few packets are lost.
        if proto_num == 17:
            cmd.append("-u")
            cmd.append("-b")
            cmd.append(str(edge_request["bandwidth"]))
            
        proc = subprocess.Popen(cmd)
        proc.communicate()[0]
        return_code = proc.returncode
        if return_code is not 0:
            time.sleep(0.5)

    # request shutdown after iperf completes successfully
    start_time = time.time()
    request_shutdown(fog_information, ctrlr_ip, ctrlr_port, total_overhead, start_time)

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

def do_nothing(sleep_duration, fog_information, ctrlr_ip, ctrlr_port,
               total_overhead=None):
    if sleep_duration is None:
        sleep_duration = 10

    time.sleep(sleep_duration)
    start_time = time.time()
    request_shutdown(fog_information, ctrlr_ip, ctrlr_port, total_overhead, start_time)
