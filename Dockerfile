FROM nvidia/cuda:10.0-cudnn7-devel-ubuntu18.04

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

# Create user 'kaimahi' to create a home directory
RUN useradd kaimahi
RUN mkdir -p /kaimahi/
WORKDIR /kaimahi/

# These two lines are needed to run unoconv
RUN chown -R kaimahi /kaimahi
ENV HOME /kaimahi

# Add kaimahi to sudo group
RUN apt update && apt install -y sudo
RUN echo "kaimahi:kaimahi" | chpasswd && adduser kaimahi sudo

# Install python + pip
RUN apt install -y python3-dev python3-pip
RUN python3 -m pip install --upgrade pip

# Install python packages
COPY requirements.txt /root/requirements.txt
RUN pip3 install -r /root/requirements.txt
