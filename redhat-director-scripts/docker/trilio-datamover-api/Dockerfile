FROM registry.access.redhat.com/rhosp13/openstack-nova-api
MAINTAINER TrilioData shyam.biradar@trilio.io

LABEL name="rhosp13/openstack-nova-api-triliodata-plugin" \
      maintainer="shyam.biradar@trilio.io" \
      vendor="TrilioData" \
      version="3.1.0" \
      release="3.1" \
      summary="Red Hat OpenStack Platform 13.0 nova-api TrilioData trilio-datamover-api" \
      description="Red Hat OpenStack Platform 13.0 nova-api TrilioData trilio-datamover-api"


# switch to root and install a custom RPM, etc.
USER root


##Install datamover packages
ADD trilio.repo /etc/yum.repos.d/
RUN yum install dmapi -y
RUN mkdir -p /var/log/dmapi/
RUN chown -R nova:nova /var/log/dmapi/
RUN mkdir -p /var/cache/dmapi/
RUN chown nova:nova /var/cache/dmapi/
RUN rm -f /etc/yum.repos.d/trilio.repo

##Copy license file
RUN mkdir /licenses
COPY licensing.txt /licenses

##Become nova user for further operations
USER nova
