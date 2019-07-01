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
RUN \
# update package list and install programs
	apt-get update && \
	DEBIAN_FRONTEND=noninteractive apt-get install -yq software-properties-common \
	curl ssh git openjdk-8-jdk wget emacs vim python3 python3-pip python3-venv \
	net-tools man iputils-ping gnupg && \
	export MAVEN_OPTS="-Xms256m -Xmx512m" && \
	export JAVA_HOME="/usr/lib/jvm/java-8-openjdk-amd64" && \
# python packages (should come after .bashrc stuff)
	yes | /usr/bin/pip3 install netmiko napalm requests xmltodict pyaml pyang ncclient && \
# install odl stuff + cisco's gui app
	wget https://nexus.opendaylight.org/content/groups/public/org/opendaylight/integration/distribution-karaf/0.3.0-Lithium/distribution-karaf-0.3.0-Lithium.tar.gz && \
	tar zxvf distribution-karaf-0.3.0-Lithium.tar.gz && \
	curl -sL https://deb.nodesource.com/setup_8.x | bash - && \
# install nodejs (dependent on curl above)
	DEBIAN_FRONTEND=noninteractive apt-get install -yq nodejs && \
	git clone https://github.com/CiscoDevNet/OpenDaylight-Openflow-App.git && \
	export MY_IP_ADDR=$(ifconfig eth0 | grep 'inet addr' | cut -d: -f2 | awk '{print $1}') && \
	export SED_STR="s/localhost/${MY_IP_ADDR}/g" && \
	sed -i "${SED_STR}" ./OpenDaylight-Openflow-App/ofm/src/common/config/env.module.js && \
	npm install -g grunt-cli && \
	cd distribution-karaf-0.3.0-Lithium; ./bin/karaf & \
	sleep 10 && \
	./bin/client -u karaf "feature:install odl-restconf-all odl-openflowplugin-all odl-l2switch-all odl-mdsal-all odl-yangtools-common odl-ovsdb-southbound-impl-ui"
ENTRYPOINT cd distribution-karaf-0.3.0-Lithium; ./bin/karaf & /bin/bash





