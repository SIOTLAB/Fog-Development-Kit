#!/usr/bin/python3

# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA

import json
import re
import subprocess
import sys
import socket
import select
import time


def get_hostname():
    # Get hostname
    hostname_proc = subprocess.Popen(["hostname"], stdout=subprocess.PIPE)
    hostname = hostname_proc.communicate()[0].decode("utf-8").strip()
    return hostname


def get_container_id():
    # Get docker container id
    cat_proc = subprocess.Popen(["cat", "/proc/self/cgroup"],
                                stdout=subprocess.PIPE)
    grep_proc = subprocess.Popen(["grep", "cpu:"],
                                 stdout=subprocess.PIPE,
                                 stdin=cat_proc.stdout)
    output = grep_proc.communicate()[0].decode("utf-8")
    container_id = output.split("/")
    container_id = container_id[len(container_id)-1][:12]  # id is last element
    return container_id

# Get MAC address on eth0 and construct the node_id based on it
def get_node_id(interface):
    ifconfig_proc = subprocess.Popen(["ifconfig", interface],
                                     stdout=subprocess.PIPE)
    grep_proc = subprocess.Popen(["grep", "ether"],
                                 stdin=ifconfig_proc.stdout,
                                 stdout=subprocess.PIPE)
    node_id = grep_proc.communicate()[0].decode("utf-8").split()[1].strip()
    return "host:" + node_id


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

def greeting(ctrlr_ip_addr, ctrlr_port, host_type, interface):
    try:
        hostname = get_hostname()
        docker_port = None        # docker port only applies to fog nodes
        node_id = get_node_id(interface)
    except BaseException:
        print(("Error getting hostname or container id. Exiting."),
              file=sys.stderr)
        sys.exit(-1)

    data = {
        "docker_port": docker_port,
        "hostname": hostname,
        "host_type": host_type,
        "node_id": node_id
    }

    print(json.dumps(data, indent=3))

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        timeout = 2
        while True:
            print("Attempting to connect to {}".format(ctrlr_ip_addr))
            try:
                s.connect((ctrlr_ip_addr, ctrlr_port))
                break
            except BaseException:
                time.sleep(1)

        print("Attempting to greet {}".format(ctrlr_ip_addr))
        # Attempt to send greeting
        s.sendall(json.dumps(data).encode())
        # If timeout occurs before receiving ack retry
        ready = select.select([s], [], [])
        if ready[0] != []:
            s.recv(1024)
            print("Greet successful. Exiting.")
            return
        else:
            s.close()
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            time.sleep(2)

# Use this function for test scripts
def test():
    host_type = "Test"
    hostname = get_hostname()
    docker_port = None
    node_id = get_node_id()
    data = {
        "docker_port": docker_port,
        "hostname": hostname,
        "host_type": host_type,
        "node_id": node_id
    }
    print(json.dumps(data, indent=3))


def main(args):

    ctrlr_port = 65433             # The port used by the server
    host_types = set(["Fog", "Edge"])

    if len(args) != 4:
        print("Usage: python3 greeting.py <Controller IP address> <Fog or Edge> <interface>",
              file=sys.stderr)
        sys.exit(-1)

    ctrlr_ip_addr = args[1]
    
    if not is_valid_ip_addr(ctrlr_ip_addr):
        print("Controller IP address is not valid. Exiting.",
              file=sys.stderr)
        sys.exit(-1)

    host_type = args[2]

    if host_type not in host_types:
        print(("Host Type is not valid. Exiting."),
              file=sys.stderr)
        sys.exit(-1)

    interface = args[3]
    
    greeting(ctrlr_ip_addr, ctrlr_port, host_type, interface)
    
    sys.exit(0)

if __name__ == "__main__":
    main(sys.argv)
