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

setvars()
{
	BASE_DIR="/var/lib/libvirt/images/${imageFile}"
	mkdir -p ${BASE_DIR}
	USER_DATA="${BASE_DIR}/user-data"
	META_DATA="${BASE_DIR}/meta-data"
	TVAULT_ISO="${BASE_DIR}/tvault"
	MEM=${TVM_MEM}
	CPUs=${TVM_CPU}
	BRIDGE=$(ip route | grep default | awk '{ print $5 }')
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

auto br-${iface}
iface br-${iface} inet static
    bridge_stp off
    bridge_waitport 0
    bridge_fd 0
    bridge_ports ${iface}
    address ${ip}
    gateway ${gateway}
    dns-nameservers 8.8.8.8
_EOF_
}

create_bridge()
{
    DEFAULT_ETH=$(ip route | grep default | awk '{print $5}') 
    if [[ ${DEFAULT_ETH} == "br-"* ]]; then
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
    gateway=`cat ${ifile} | grep gateway | awk '{print $2}'`

    setFileData

    cp /tmp/tmp_interfacs /etc/network/interfaces

    # Check if bridge is created
    DEFAULT_ETH=$(ip route | grep default | awk '{print $5}') 
    if [[ ${DEFAULT_ETH} == "br-"* ]]; then
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
  iface ens3 inet dhcp
hostname: ${TVM_HOSTNAME}
_EOF_
}

# setMetaData()
# {
# 	cat > ${META_DATA} << _EOF_
# instance-id: ${TVM_HOSTNAME}
# network-interfaces: |
#   auto ens3
#   iface ens3 inet static
#   address ${TVM_IP}
#   netmask ${TVM_NETMASK}
#   gateway ${TVM_GATEWAY}
#   dns-nameservers ${TVM_DNS}
# hostname: ${TVM_HOSTNAME}
# _EOF_
# }

# Returns 1 if VM is not running
is_vm_running()
{
    for i in $(seq 1 $TVM_NUM_NODES);do
        local run=$(sudo virsh list --all | grep ${TVM_HOSTNAME}-$i | awk '{print $NF}')
        if [ "$run" != "running" ]; then
            return 1
        fi
    done
    # Return 0 if all Tfilio VMs are running
    return 0
}

# Returns 1 if VM is not created
is_vm_created()
{
    for i in $(seq 1 $TVM_NUM_NODES);do
        if [ `/usr/bin/virsh list --all | grep -c ${TVM_HOSTNAME}-$i` -ne 1 ]; then
            return 1
        fi
    done
    # Return 0 if all Tfilio VMs are created
    return 0
}

create_vm()
{
    for i in $(seq 1 $TVM_NUM_NODES);do
        logger "Check if ${TVM_HOSTNAME}-$i vm already exists"

        if [ `/usr/bin/virsh list --all | grep -c ${TVM_HOSTNAME}-$i` -eq 1 ]; then
            logger "vm is already created"
            return
        fi

        ORIG_HOSTNAME=${TVM_HOSTNAME}
        TVM_HOSTNAME=${TVM_HOSTNAME}-$i

        # Image file path, Host Name, IP Address
        imageFile=`ls ${TVM_IMAGE_PATH} | awk -F'/' '{print $NF}' | cut -d"." -f1-4`
        imageFile=$imageFile-$i

        # Set env variables
        setvars
        # Set User data and meta data
        setUserData
        setMetaData

        # Reset the imageFile name
        imageFile=`ls ${TVM_IMAGE_PATH} | awk -F'/' '{print $NF}' | cut -d"." -f1-4`

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
        TVM_HOSTNAME=${ORIG_HOSTNAME}
    done

    sleep 30

    is_vm_created
    if [ $? -eq 0 ]; then
        logger "Created Trilio VMs"
        exit 0
    fi
}

# Start the VM
start_vm()
{
    for i in $(seq 1 $TVM_NUM_NODES);do
        logger "Get Trilio vm state"
        state="`sudo virsh dominfo ${TVM_HOSTNAME}-$i | awk '/State:/' | cut -d: -f 2 | tr -d ' '`"
        case $state in
            running)   logger "${TVM_HOSTNAME}-$i is already runnning"
                       ;;
            shut*)     logger "need to start ${TVM_HOSTNAME}-$i"
                       /usr/bin/virsh start ${TVM_HOSTNAME}-$i
                       if [ $? -eq 1 ]; then
                           logger "Error: Trilio vm is shutdown but couldn't restart it"
                           exit 1
                       fi
                       ;;
            *)         logger "Unknown state($state) of ${TVM_HOSTNAME}-$i"
                       ;;
        esac
    done

}


# Stop, undefine the VM
stop_vm()
{
    for i in $(seq 1 $TVM_NUM_NODES);do
        local run=$(sudo virsh list --all | grep ${TVM_HOSTNAME}-$i | awk '{print $NF}')
        if [ "$run" == "running" ]; then
            logger "Shutting down Trilio vm"
            /usr/bin/virsh shutdown ${TVM_HOSTNAME}-$i
            sleep 5
        fi

        logger "Destroying Trilio vm"
        /usr/bin/virsh destroy ${TVM_HOSTNAME}-$i
        /usr/bin/virsh undefine ${TVM_HOSTNAME}-$i
    done
}


get_vm_ip_address()
{
    for i in $(seq 1 $TVM_NUM_NODES);do
        vm_mac=$(virsh domiflist ${TVM_HOSTNAME}-$i |grep br- |grep -o -E "([0-9a-f]{2}:){5}([0-9a-f]{2})")
   
        vm_nw=$(ip route | grep default | awk '{print $3}' | cut -d "." -f1-3)    
        # Sweep ping
        for j in {1..254} ;do (ping $vm_nw.$j -c 1 -w 5  >/dev/null && echo "$vm_nw.$j" &) ;done > /dev/null 2>&1
        vm_ip=$(arp -a | grep $vm_mac | cut -d " " -f2 | sed 's/[(),]//g')
        # Exit if IP address is not retrieved
        if [ x$vm_ip = "x" ]; then
             exit 1
        fi

        if [ $i -gt 1 ]; then
             tvm_host_list="${tvm_host_list},"
        fi
        tvm_host_list="${tvm_host_list}${vm_ip}=${TVM_HOSTNAME}-$i"
    done
    # Return a string of hostnames and IP Addresses    
    echo $tvm_host_list
}

export -f logger create_bridge create_vm stop_vm start_vm is_vm_created is_vm_running get_vm_ip_address
