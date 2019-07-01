# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA

import socket
import threading
import topology

class Manager:
    """
    Manager is a wrapper class for the other Manager classes used to achieve
    maximum code-reuse
    """
    
    def __init__(self, mgrs, head, ctrlr_ip_addr):
        self.mgrs = mgrs                   # Refs to other Managers (see fdk.py)
        self.ctrlr_ip_addr = ctrlr_ip_addr # IP Address of controller
        self.head = head                   # HTTP Header

        # Socket storage. key=Socket-description, value=socket
        # Ex: socks["greeting"] stores greeting serv socket (in TopologyManager)
        # ALL OPENED SOCKETS SHOULD BE STORED HERE SO shutdown() CAN CLEANLY
        # CLOSE THEM.
        self.socks = {}

        # Thread storage. key=Thread-description, value=socket
        # Example: threads["cpu_util"] stores thread runnning cpu_util serv (in
        # ResourceManager)
        # ALL OPENED THREADS (that don't die on their own) SHOULD BE STORED
        # HERE SO shutdown() CAN CLEANLY CLOSE THEM
        self.threads = {}
        
    def shutdown(self):
        """
        shutdown() performs a clean shutdown of the Manager object by shutting
        down any open sockets and other resources.
        """

        # Close all sockets
        for sock_type in self.socks:
            self.socks[sock_type].shutdown(socket.SHUT_WR)
            self.socks[sock_type].close()
        
        del self.socks

        # Close all running threads (Going to rework this, for now just Ctrl-C
        # to kill them
        # for thread_type in self.threads:
        #     self.threads[thread_type].close()

        # del self.threads

    
            

        # self.mgrs["top"].shutdown()
