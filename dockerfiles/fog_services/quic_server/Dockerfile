# This file is a part of the The Fog Development Kit (FDK)
#
# Developed by:
# - Colton Powell
# - Christopher Desiniotis
# - Dr. Behnam Dezfouli
# 
# In the Internet of Things Research Lab, Santa Clara University, CA, USA

FROM ubuntu
ADD fog-development-kit /root/fog-development-kit
WORKDIR /root
#RUN apt-get update && \
ENV PATH="${PATH}:/usr/local/go/bin"
RUN apt-get update && \
	DEBIAN_FRONTEND=noninteractive apt-get install -yq python3 python3-pip python3-venv git iperf3 wget libsm6 libxext6 libxrender-dev && \
       yes | /usr/bin/pip3 install requests iperf3 && \
      
	wget https://dl.google.com/go/go1.13.4.linux-amd64.tar.gz && \
	tar -C /usr/local -xzf go1.13.4.linux-amd64.tar.gz && \	
	cd fog-development-kit/dockerfiles/fog_services/quic_server/ && \
	go get github.com/lucas-clemente/quic-go && \
	go build && \
	cp quic_server /tmp/quic_server && \
	cp objectdetection.py /tmp/ && \
	pip3 install --upgrade tensorflow==1.13.1 && \
	pip3 install numpy scipy opencv-python matplotlib h5py keras opencv-python Pillow && \
	pip3 install https://github.com/OlafenwaMoses/ImageAI/releases/download/2.0.2/imageai-2.0.2-py3-none-any.whl && \
	wget https://github.com/OlafenwaMoses/ImageAI/releases/download/1.0/resnet50_coco_best_v2.0.1.h5 && \
	wget https://github.com/fchollet/deep-learning-models/releases/download/v0.2/resnet50_weights_tf_dim_ordering_tf_kernels.h5 && \
	cp resnet50_weights_tf_dim_ordering_tf_kernels.h5 /tmp/ && \
	cp resnet50_coco_best_v2.0.1.h5 /tmp/
WORKDIR /tmp
ENV PORT=4000
ENV FOG_IP=0.0.0.0
CMD /tmp/quic_server
# CMD /usr/bin/python3 /tmp/iperf.py 
