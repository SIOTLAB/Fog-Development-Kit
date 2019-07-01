# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA


# Build from parent directory with the command:
# docker build -f edge_node/Dockerfile --no-cache -t <container_name>:<tag>

# Format: /usr/bin/python3 greeting.py <Controller IP address> <Fog or Edge>
# Colton's Version:
/usr/bin/python3 /etc/init.d/greeting.py 192.168.122.51 Fog

# Chris' Version:

