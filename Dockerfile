FROM tensorflow/tensorflow:2.1.0-gpu

# Use New Zealand mirrors
RUN sed -i 's/archive/nz.archive/' /etc/apt/sources.list

RUN apt update

# Set timezone + locale to Auckland
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get install -y locales tzdata
RUN locale-gen en_NZ.UTF-8
RUN dpkg-reconfigure locales
RUN echo "Pacific/Auckland" > /etc/timezone
RUN dpkg-reconfigure -f noninteractive tzdata
ENV LANG en_NZ.UTF-8
ENV LANGUAGE en_NZ:en

# Install python + pip
RUN apt install -y python3-dev python3-pip
RUN python3 -m pip install --upgrade pip

# Install python packages
COPY requirements.txt /root/requirements.txt
RUN pip3 install -r /root/requirements.txt
