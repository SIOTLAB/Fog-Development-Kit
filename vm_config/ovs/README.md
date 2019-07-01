This directory contains all of the necessary files needed to setup an OpenVSwitch Virtual Machine.

First configure the VM to have the appropriate vNIC's.
By default, we support 6 vNIC's per OVS with these scripts.

Then modify setup.sh and setup2.sh to your needs.
For example, specify different port names, a different controller ip address, etc. in these files to configure the devices to your needs.

See setup2.sh for more info on the vNIC's, and modify the file according to your config.
Similarly, modify the provided interfaces file (/etc/network/interfaces) and sshd_config (/etc/ssh/sshd_config) file accordingly.

Then look through setup.sh and setup2.sh and make any necessary modifications (refer to comments)

Enable Promiscuous mode for the vNIC's of these VM's.

Finally, on the Open vSwitch:
- run setup.sh
- run setup2.sh (after the vNICs have been added to the VM)