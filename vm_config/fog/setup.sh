#!/bin/bash

# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA


# Install docker
apt-get update && \
apt-get --assume-yes install \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg-agent \
    software-properties-common && \
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add - && \
add-apt-repository --yes \
   "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
   $(lsb_release -cs) \
   stable" && \
apt-get --assume-yes install docker-ce docker-ce-cli containerd.io && \

# Configure remote access to docker daemon
mkdir /etc/systemd/system/docker.service.d/ && \
cp ./override.conf /etc/systemd/system/docker.service.d/ && \
systemctl daemon-reload && \
systemctl restart docker.service && \

# Install other packages
apt-get --assume-yes install openssh-client openssh-server git ifupdown emacs25 vim python3 nmap arping traceroute && \

# Set up ssh and network configuration
# modify interfaces file to your needs
cp ./interfaces /etc/network/interfaces && \
cp ./sshd_config /etc/ssh/sshd_config && \
systemctl enable ssh.service && \
# systemctl disable NetworkManager.service # Only for Ubuntu Desktop; not Ubuntu Server

# Disable netplan 
systemctl stop systemd-networkd.socket systemd-networkd networkd-dispatcher systemd-networkd-wait-online && \
systemctl disable systemd-networkd.socket systemd-networkd networkd-dispatcher systemd-networkd-wait-online && \
systemctl mask systemd-networkd.socket systemd-networkd networkd-dispatcher systemd-networkd-wait-online && \
apt-get --assume-yes purge nplan netplan.io && \

# Setup our usual networking service (uses /etc/network/interfaces)
systemctl unmask networking && \
systemctl enable networking && \
systemctl restart networking && \

systemctl disable systemd-networkd.service && \

# Set up fog service
cp ./fog.service /etc/systemd/system/ && \
cp ./fog.py /usr/src && \
chmod +x fog.sh && \
cp ./fog.sh /usr/bin && \
systemctl enable fog.service


