# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA


FROM ubuntu
ADD iperf.py /tmp/iperf.py
WORKDIR /root
RUN apt-get update && \
	DEBIAN_FRONTEND=noninteractive apt-get install -yq python3 python3-pip python3-venv iperf3 && \
	yes | /usr/bin/pip3 install requests iperf3
CMD /usr/bin/python3 /tmp/iperf.py
