# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA

# Run from just outside the FDK folder.
# This is so that the FDK can be copied to the edge device

FROM ubuntu
COPY fog-development-kit/dockerfiles/host_nodes/edge_devices/.bashrc /root/
WORKDIR /root
COPY fog-development-kit/dockerfiles/host_nodes/edge_devices/greeting.py /etc/init.d/
COPY fog-development-kit/dockerfiles/host_nodes/edge_devices/edge.sh /etc/init.d/ 
ADD fog-development-kit /root/fog-development-kit/

RUN \
# update package list and install programs
	apt-get update && \
	DEBIAN_FRONTEND=noninteractive apt-get install -yq software-properties-common \
	curl ssh git wget python3 python3-pip python3-venv iperf3 \
	man iputils-ping gnupg emacs vim && \
	apt install net-tools && \
# python packages (should come after .bashrc stuff)
	yes | /usr/bin/pip3 install netmiko napalm requests xmltodict pyaml pyang ncclient && \
	chmod +x /etc/init.d/edge.sh && \
	ln -s /etc/init.d/edge.sh /etc/rc0.d/S01edge.sh && \
	ln -s /etc/init.d/edge.sh /etc/rc1.d/S01edge.sh && \
	ln -s /etc/init.d/edge.sh /etc/rc2.d/S01edge.sh && \
	ln -s /etc/init.d/edge.sh /etc/rc3.d/S01edge.sh && \
	ln -s /etc/init.d/edge.sh /etc/rc4.d/S01edge.sh && \
	ln -s /etc/init.d/edge.sh /etc/rc5.d/S01edge.sh && \
	ln -s /etc/init.d/edge.sh /etc/rc6.d/S01edge.sh && \
	wget https://dl.google.com/go/go1.13.4.linux-amd64.tar.gz && \
	tar -C /usr/local -xzf go1.13.4.linux-amd64.tar.gz && \
	go get github.com/lucas-clemente/quic-go


ENTRYPOINT service edge.sh start & /bin/bash
