# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA


# Notes:
# - run setup2.sh after setting up your 6 interfaces. Modify it if you need more/less.
# - You should run this file within the directory it is found in
# - You must set up variables here according to your needs (search for "CUSTOMIZE" in this file)

yes | apt-get install openssh-client openssh-server openvswitch-switch openvswitch-common git ifupdown emacs25 vim nmap arping traceroute && \

# important; has all of the needed information
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

systemctl disable systemd-networkd.service
