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

# Obsolete now
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
        docker_port = "2375"
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
    
    # What if this disconnects??
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        #s.setblocking(False)
        timeout = 2
        while True:
            # Make connection to controller
            print("Attempting to connect to {}".format(ctrlr_ip_addr))
    
            try:
                s.connect((ctrlr_ip_addr, ctrlr_port))
            except ConnectionRefusedError:
                time.sleep(1)
                continue

            print("Attempting to greet {}".format(ctrlr_ip_addr))
            # Attempt to send greeting
            s.sendall(json.dumps(data).encode())
            # If timeout occurs before receiving ack retry 
            ready = select.select([s], [], [])
            if ready[0] != []:
                s.recv(1024)    # discard ack
                print("Greeting successful. Exiting.")
                return
            else:
                s.close()
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                time.sleep(2)
                

def get_cpu_util():
    p1 = subprocess.Popen(["top","-b","-d1","-n1"], stdout=subprocess.PIPE)      # Run top
    p2 = subprocess.Popen(["grep","-i","%CPU(s)"], stdin=p1.stdout, stdout=subprocess.PIPE)  # filter cpu utilization
    p1.stdout.close()
    cpu_util_str = p2.communicate()[0].decode("utf-8")
    cpu_util_flds = cpu_util_str.split(",")
    idle_pct = float(cpu_util_flds[3].strip().split(" ")[0])
    wait_pct = float(cpu_util_flds[4].strip().split(" ")[0])
    cpu_util = round(100.0 - idle_pct - wait_pct, 2)
    return cpu_util

# Return available RAM in MB
def get_RAM_usage():
    p1 = subprocess.Popen(["free", "-m"], stdout=subprocess.PIPE) # Get memory statistics in MB 
    p2 = subprocess.Popen(["grep","Mem:"], stdin=p1.stdout, stdout=subprocess.PIPE) # Get physical memory stats
    p1.stdout.close()
    RAM_usage_str = p2.communicate()[0].decode("utf-8")
    # Mem: <total> <used> <free> <shared> <buff/cache> <available>
    RAM_usage_flds = RAM_usage_str.split()
    available_RAM = float(RAM_usage_flds[6])
    return available_RAM
    
# Return free disk space in MB
def get_disk_usage():
    p1 = subprocess.Popen(["df", "-h"], stdout=subprocess.PIPE) # Get disk usage statistics 
    p2 = subprocess.Popen(["grep","/$"], stdin=p1.stdout, stdout=subprocess.PIPE) # Get total disk usage
    p1.stdout.close()
    disk_usage_str = p2.communicate()[0].decode("utf-8")
    # <file system> <available> <used> <free> <percentage used> <mounted on>
    disk_usage_flds = disk_usage_str.split()
    free_disk_str = disk_usage_flds[3]
    
    # remove units (i.e. K/M/G)
    # convert to MB
    if free_disk_str.endswith("G"):
        free_disk = float(free_disk_str[:-1])*1000
    elif free_disk_str.endswith("K"):
        free_disk = float(free_disk_str[:-1])/1000
    else:
        free_disk = float(free_disk_str[:-1])
        
    return free_disk

# Send SDN controller resource statistics for cpu, ram, and disk
def report_resources(ctrlr_ip_addr, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # If cannot connect to server, return and retry sending greeting message
        try:
            s.connect((ctrlr_ip_addr, port))
        except ConnectionRefusedError:
            return

        print("Connection to {} successful\n".format(ctrlr_ip_addr))
        while True:
            cpu = get_cpu_util()
            ram = get_RAM_usage()
            disk = get_disk_usage()
            print("Attempting to send resource statistics:\n")
            # if sending data fails, return and retry sending greeting message
            try:
                s.sendall("{} {} {}".format(cpu,ram,disk).encode())
            except (ConnectionResetError, TimeoutError, BrokenPipeError):
                return
            time.sleep(5)

# Use this function for test scripts
def test():
    host_type = "Test"
    hostname = get_hostname()
    docker_port = "2375"
    node_id = get_node_id("ens33")
    data = {
        "docker_port": docker_port,
        "hostname": hostname,
        "host_type": host_type,
        "node_id": node_id
    }
    print(json.dumps(data, indent=3))
    cpu = get_cpu_util()
    ram = get_RAM_usage()
    disk = get_disk_usage()
    print("CPU: {} RAM: {}, DISK: {}".format(cpu,ram,disk))
    
def main(args):

    ctrlr_greeting_port = 65433    # port for greeting server
    ctrlr_cpu_util_port = 65432    # port for cpu-util server
    host_types = set(["Fog", "Edge"])

    if len(args) != 4:
        print("Usage: python3 fog.py <Controller IP address> <Fog or Edge> <interface>",
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

   
    '''
    while(1):
        greeting(ctrlr_ip_addr, ctrlr_greeting_port, host_type, interface)
        report_resources(ctrlr_ip_addr, ctrlr_cpu_util_port)
    '''

    # FOR TESTING ONLY SEND GREETING ONCE
    greeting(ctrlr_ip_addr, ctrlr_greeting_port, host_type, interface)
    report_resources(ctrlr_ip_addr, ctrlr_cpu_util_port)

if __name__ == "__main__":
    main(sys.argv)
