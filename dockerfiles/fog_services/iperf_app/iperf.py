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
import iperf3
import os
import sys
import socket
import subprocess
import time

def main(args):
    server = iperf3.Server()
    server.port = int(os.environ.get("PORT"))
    result = server.run()
    data = {}
    edge_ip = result.json['start']['connected'][0]['remote_host']
    data[edge_ip] = {}
    # data[edge_ip]['bandwidth'] = result.json['end']['sum_received']['bits_per_second']

    # Get individual readings throughout the iperf test
    intervals = result.json['intervals']

    last = intervals.pop()['sum']['bytes'] * 8 # remove last reading, get bits transmitted
    count = len(intervals)
    
    readings = [ ] # store bandwidth for all readings
    for reading in intervals:
        # readings.append(reading['sum']['bits_per_second']) # old

        # Combine last bytes into the other readings (that's what iperf does)
        readings.append(reading['sum']['bytes']*8 + last/count)

    data[edge_ip]['readings'] = readings
    data[edge_ip]['bandwidth'] = sum(readings)/90 # len(readings)
    # ^ len(readings) can be 92 or 93, we discard the last results later and
    # combine them into the readings later.

    #print(result.text)
    #print(json.dumps(result.json, indent=3))
    #print(result.json['end']['sum_received']['bits_per_second'])

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        while True:
            print("Attempting to connect to bandwidth server", file=sys.stderr)
            try:
                s.connect(("127.0.0.1", 20000))
                break
            except BaseException:
                print(("Error connecting to bandwidth server"),
        file=sys.stderr)

        print("Successfully connected to bandwidth server", file=sys.stderr)

        print("Sending json data")
        s.sendall(json.dumps(data).encode())
        print("Successfully sent json data")

if __name__ == "__main__":
    main(sys.argv)
