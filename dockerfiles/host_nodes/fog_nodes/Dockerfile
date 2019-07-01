# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA


FROM ubuntu
COPY .bashrc /root/
WORKDIR /root
COPY greeting.py /etc/init.d/
COPY fog.sh /etc/init.d/ 
RUN \
# update package list and install programs
	apt-get update && \
	DEBIAN_FRONTEND=noninteractive apt-get install -yq software-properties-common \
	curl ssh git wget python3 python3-pip python3-venv iperf3 \
	net-tools man iputils-ping gnupg && \
# python packages (should come after .bashrc stuff)
	yes | /usr/bin/pip3 install netmiko napalm requests xmltodict pyaml pyang ncclient && \
	chmod +x /etc/init.d/fog.sh && \
	ln -s /etc/init.d/fog.sh /etc/rc0.d/S01fog.sh && \
	ln -s /etc/init.d/fog.sh /etc/rc1.d/S01fog.sh && \
	ln -s /etc/init.d/fog.sh /etc/rc2.d/S01fog.sh && \
	ln -s /etc/init.d/fog.sh /etc/rc3.d/S01fog.sh && \
	ln -s /etc/init.d/fog.sh /etc/rc4.d/S01fog.sh && \
	ln -s /etc/init.d/fog.sh /etc/rc5.d/S01fog.sh && \
	ln -s /etc/init.d/fog.sh /etc/rc6.d/S01fog.sh 
ENTRYPOINT service fog.sh start & /bin/bash





