# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA

ovs-vsctl add-br br0 && \

# Add interfaces to the OVS bridge (CUSTOMIZE)
ovs-vsctl add-port br0 ens33 && \
ovs-vsctl add-port br0 ens38 && \
ovs-vsctl add-port br0 ens39 && \
ovs-vsctl add-port br0 ens40 && \
ovs-vsctl add-port br0 ens41 && \
ovs-vsctl add-port br0 ens42 && \

# IMPORTANT
# Specify protocols
ovs-vsctl set bridge br0 protocols=OpenFlow13,OpenFlow10 && \

# enable stp
ovs-vsctl set bridge br0 stp_enable=true && \

# The IP address of your SDN controller (CUSTOMIZE)
ctrlr_ip_addr=$(echo "192.168.122.190") && \

# Set the IP and give network connectivity (Only for convenient docker copypasta setup)
# ip_digit=$(echo "$HOSTNAME"| awk -F"-" '{print $2}') && \
# ip_addr=$(echo "192.168.122.19$ip_digit") && \
# ip addr add "$ip_addr/24" dev br0 && \
    
# Enter your controller IP address here instead of 192.168.122.190
ovs-vsctl set-controller br0 tcp:$ctrlr_ip_addr:6633 && \

# get server pid
ovsdb_server_pid=$(top -bn1 | grep "ovsdb-server" | awk '{print $1;}') && \

# Set manager (should be your controller, for our project):

# Passive mode
ovs-vsctl set-manager tcp:$ctrlr_ip_addr:6640 && \

# Active
# ovs-vsctl set-manager ptcp:6640

# Use ovs-appctl to contact ovsdb-server and allow connection from the controller:

# Passive mode:
ovs-appctl -t /var/run/openvswitch/ovsdb-server.$ovsdb_server_pid.ctl \
    	   ovsdb-server/add-remote tcp:$ctrlr_ip_addr:6640

# IMPORTANT END

# Active mode (Cant get this to work)
# ovs-appctl -t /var/run/openvswitch/ovsdb-server.$ovsdb_server_pid.ctl \
# 	   ovsdb-server/add-remote db:Open_vSwitch,Open_vSwitch,manager_options

