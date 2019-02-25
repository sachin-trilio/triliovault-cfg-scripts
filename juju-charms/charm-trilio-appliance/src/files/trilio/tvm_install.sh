#!/bin/bash

LOG_TERMINAL=0

logger()
{
    if [ $LOG_TERMINAL -eq 1 ]; then
        echo $1
    else
        juju-log $1
    fi
}


check_env()
{
    logger "TVM_IP: ${TVM_IP}"
    logger "TVM_IMAGE_PATH: ${TVM_IMAGE_PATH}"
    logger "TVM_HOSTNAME: ${TVM_HOSTNAME}"
    logger "TVM_DNS: ${TVM_DNS}"
    logger "TVM_NETMASK: ${TVM_NETMASK}"
    logger "TVM_GATEWAY: ${TVM_GATEWAY}"
    logger "TVM_MEM: ${TVM_MEM}"
    logger "TVM_CPU: ${TVM_CPU}"
    logger "TVM_BRIDGE: ${TVM_BRIDGE}"
}

setvars()
{
	BASE_DIR="/var/lib/libvirt/images/${imageFile}"
	mkdir -p ${BASE_DIR}
	USER_DATA="${BASE_DIR}/user-data"
	META_DATA="${BASE_DIR}/meta-data"
	TVAULT_ISO="${BASE_DIR}/tvault"
	MEM=${TVM_MEM}
	CPUs=${TVM_CPU}
	BRIDGE=${TVM_BRIDGE}
	imageTargetLoc="${BASE_DIR}"
	mkdir -p ${imageTargetLoc}
}

cleanUp()
{
	rm -f ${TVAULT_ISO}.iso ${USER_DATA} ${META_DATA}
	rm -f ${imageTargetLoc}/${imageFile}.tar.gz
	sync && echo 3 > /proc/sys/vm/drop_caches
}

setFileData()
{
        cat > /tmp/tmp_interfacs << _EOF_
auto lo
iface lo inet loopback

auto ${iface}
iface ${iface} inet manual

auto ${TVM_BRIDGE}
iface ${TVM_BRIDGE} inet static
    bridge_stp off
    bridge_waitport 0
    bridge_fd 0
    bridge_ports ${iface}
    address ${ip}
    netmask ${TVM_NETMASK}
    gateway ${TVM_GATEWAY}
_EOF_
}

create_bridge()
{
    DEFAULT_ETH=$(ip route | grep default | awk '{ print $5 }') 
    if [ ${DEFAULT_ETH} == ${TVM_BRIDGE} ]; then
        logger "bridge is already created"
        return 0
    fi

    cat /etc/network/interfaces | grep address
    if [ $? -eq 1 ]; then
        ifile=/etc/network/interfaces.d/*.cfg
    else
        ifile=/etc/network/interfaces
    fi

    ip=`cat ${ifile} | grep address | awk '{print $2}'`
    iface=`cat ${ifile} | grep static | awk '{print $2}'`

    setFileData

    cp /tmp/tmp_interfacs /etc/network/interfaces

    # Check if bridge is created
    DEFAULT_ETH=$(ip route  | grep default | awk '{ print $5 }') 
    if [ ${DEFAULT_ETH} == ${TVM_BRIDGE} ]; then
        logger "Bridge is created"
        return 0
    else
        logger "Failed to create bridge"
        
        # Reboot if bridge is not added
        # ifdown -a ; ifup -a
        reboot

        return 1
    fi

}

extractAndCopy()
{
	cp ${TVM_IMAGE_PATH} ${imageTargetLoc}
	cd ${imageTargetLoc}
	tar xzf ${imageFile}.tar.gz
}

setUserData()
{
	cat > ${USER_DATA} << _EOF_
preserve_hostname: False
hostname: ${TVM_HOSTNAME}
_EOF_
}

setMetaData()
{
	cat > ${META_DATA} << _EOF_
instance-id: ${TVM_HOSTNAME}
network-interfaces: |
  auto ens3
  iface ens3 inet static
  address ${TVM_IP}
  netmask ${TVM_NETMASK}
  gateway ${TVM_GATEWAY}
  dns-nameservers ${TVM_DNS}
hostname: ${TVM_HOSTNAME}
_EOF_
}

# Returns 0 if VM is not running
is_vm_running()
{
    local run=$(sudo virsh list --all | grep ${TVM_HOSTNAME} | awk '{print $NF}')
    if [ "$run" == "running" ]; then
        return 1
    else
        return 0
    fi
}

# Returns 0 if VM is not created
is_vm_created()
{
    if [ `/usr/bin/virsh list --all | grep -c ${TVM_HOSTNAME}` -eq 1 ]; then
        return 1
    else
        return 0
    fi
}

create_vm()
{
    logger "Check if ${TVM_HOSTNAME} vm already exists"

    if [ `/usr/bin/virsh list --all | grep -c ${TVM_HOSTNAME}` -eq 1 ]; then
        logger "vm is already created"
        return
    fi

    # Image file path, Host Name, IP Address
    imageFile=`ls ${TVM_IMAGE_PATH} | awk -F'/' '{print $NF}' | cut -d"." -f1-4`
    # Set env variables
    setvars
    # Set User data and meta data
    setUserData
    setMetaData
    # Extract and copy
    logger "Extract and copy the image"
    extractAndCopy
    # create ISO
    logger "Create ISO image"
    genisoimage -output ${TVAULT_ISO}.iso -volid cidata -joliet -rock ${USER_DATA} ${META_DATA} > /dev/null 2>&1
    # Create Trilio VM using iso img
    logger "Create Trilio VM using iso img"
    virt-install --import --name ${TVM_HOSTNAME} --memory $MEM --vcpus $CPUs --disk ${imageTargetLoc}/${imageFile},format=qcow2,bus=virtio --disk ${TVAULT_ISO}.iso,device=cdrom --network  bridge=${BRIDGE},model=virtio --os-type=linux --noautoconsole
    sleep 15
    virsh change-media ${TVM_HOSTNAME} hda --eject --config
    # Cleanup
    cleanUp

    is_vm_created
    if [ $? -eq 0 ]; then
        logger "Created Trilio vm"
        exit 1
    fi
}

# Start the VM
start_vm()
{
    logger "Get Trilio vm state"
    state="`sudo virsh dominfo ${TVM_HOSTNAME} | awk '/State:/' | cut -d: -f 2 | tr -d ' '`"
    case $state in
        running)   logger "${TVM_HOSTNAME} is already runnning"
                   ;;
        shut*)     logger "need to start ${TVM_HOSTNAME}"
                   /usr/bin/virsh start ${TVM_HOSTNAME}
                   if [ $? -eq 1 ]; then
                       logger "Error: Trilio vm is shutdown but couldn't restart it"
                       exit 1
                   fi
                   ;;
        *)         logger "Unknown state($state) of ${TVM_HOSTNAME}"
                   ;;
    esac
}


# Stop, undefine the VM
stop_vm()
{
    is_vm_running
    if [ $? -eq 1 ]; then
        logger "Shutting down Trilio vm"
        /usr/bin/virsh shutdown ${TVM_HOSTNAME}
        sleep 5
    fi

    is_vm_running
    if [ $? -eq 1 ]; then
        logger "Destroying Trilio vm"
        /usr/bin/virsh destroy ${TVM_HOSTNAME}
    fi
    /usr/bin/virsh undefine ${TVM_HOSTNAME}
}


export -f logger create_bridge create_vm stop_vm start_vm is_vm_created is_vm_running 
