This directory contains all necessary files needed to setup a fog node running on a VM.

In `interfaces` (/etc/network/interfaces) modify the networking configuration.

In `fog.sh` configure the following:
- the ip address of your SDN controller 
- the network interface in which the node is sending out its messages on
  (i.e. ens33 or eth0)
  
Run `chmod +x setup.sh && sudo ./setup.sh` to fully setup/configure the fog instance.

A fog service is set up so that the fog node will greet the SDN controller, associating itself as a fog node. 
After a successful greeting, the fog node will continually report its resource usage (cpu,ram,disk) to the SDN controller.