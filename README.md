# The Fog Development Kit (ODL)

The Fog Development Kit is a comprehensive edge-fog application development platform, intended to simplify and lower the cost of creating edge-fog applications.

Terms: OpenDaylight = ODL, Open vSwitch = OVS

### INSTALLATION

Installation is a multi-step process.
The Fog Development Kit simplifies the process of developing edge-fog applications on a network. As such, the construction and setup of an entire network is required.

You must use:
- OpenFlow switches (with OpenFlow 1.3 + OVSDB support - We recommend OVS)
- A Controller (Runs the FDK and ODL)
- Fog nodes
- Edge devices

##### OpenFlow Switch Config
* It is assumed you can handle the configuration of the network and the OpenFlow Switches.
* For OVS users: You must specify the controller machine as both the controller AND manager of every switch bridge in the topology.
* We provide scripts in `./vm_config/ovs/` as a template for setting up OVS machines, but you must modify them according to your needs. See `./vm_config/ovs/README.md` for more info on this sample configuration process.

##### Controller Config
* Download the FDK onto the machine
* install ODL 0.8.4 and Python3
* In ODL, run: `feature:install odl-l2switch-all odl-restconf-all features-openflowplugin odl-yangtools-common odl-ovsdb-utils odl-l2switch-switch-ui odl-mdsal-all odl-ovsdb-southbound-impl-ui odl-l2switch-switch-rest`
* In the FDK folder, modify the controller IP address in fdk_conf.json.
* Install the following packages in your python environment for FDK: `requests, docker`
* After ODL starts, the FDK can be started by running `python3 fdk.py`

##### Fog Node Config
* Fog nodes must greet the controller, which identify themselves as fog nodes and enabling services to be instantiated on them. See `vm_config/fog/fog.py` for a sample greeting script. This script will also attempt to begin reporting resource utilization to the FDK.
* Fog nodes must also install Docker and configure it to be able to be managed by the controller. See `vm_config/fog/setup.sh` (modify to your needs) and `vm_config/fog/notes.txt` for more details. This step enables remote instantiation of containers on the devicevia Docker Swarm.
* Fog nodes must have Docker images built, which can be instantiated as containers and requested by edge devices with a specific amount of resources. Fog nodes can only have containers instantiated on them after greeting the FDK. Docker images are built by first creating a Dockerfile and then running the `docker build` command with the desired parameters. A sample Dockerfile is provided in `dockerfiles/iperf_app_fog/Dockerfile`. You must give a name (or repository, in Docker terms) to the image, which is then requested by a service request from an edge device


##### Edge Device Config
* You must setup your edge devices to greet the controller. After a successful greeting, it can then run applications. A sample greeting python script can be found in `dockerfiles/host_nodes/greeting.py`
* A sample application script can be found in `iperf_app.py`.


### APPLICATION CREATION

* This details how you can build a basic application, using the provided templates

* Create a sample fog node Docker service and edge device application.

* A sample fog node Docker service can be found in `dockerfiles/iperf_app_fog`.
  Run `docker build` with the appropriate parameters to build a Docker image
  This image name/repository can then be requested by service requests,
  which will instantiate the desired image as a container in the fog
  
* A sample edge device application script can be found in `iperf_app.py`.
  This application:
   - Creates and issues a service request. Parameters for resources and the image/repository name are taken at the command line.
   - If the previously-built iperf_app_fog image is requested (again, this is entered at the command line), an Iperf3 server starts within a containerized service in the fog.
   - Upon success, starts an Iperf3 client that connects to the Fog node IP and port returned in the success response by the FDK.
   - Finally, upon termination or Ctrl-C, the edge device issues a shutdown request, completely terminating the service and de-allocating any associated resources.
   

### EXECUTION SAMPLE

Start ODL, and let it load completely.
Then start the FDK, the edge greeting applications, and the fog greeting applications in any order.
Once an edge device confirms it's greeting has been processed (It will receive an empty ACK message from the FDK upon processing), it can begin issuing service requests and running edge-fog applications.

Then run applications on edge devices that issue service requests and then communicate with that service in the fog.
Each response contains a code indicating FAILURE or SUCCESS.
If SUCCESS is detected, then the desired service is instantiated in the fog.
Contained within the response will be an "ip" and "port" field, which can be used to then communicate with the instantiated service.
Once complete, the application should issue a shutdown request to deallocate the service.

Upon turning off the system, hit Ctrl-C once to begin shutdown in the FDK. Wait until the message "IT IS SAFE TO EXIT" is displayed before completely terminating the program. This will ensure that flows, packet queues, etc. are cleaned up and remove in their entirety.

















