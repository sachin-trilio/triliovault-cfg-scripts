import os
import re
import netaddr
import sys
import subprocess
from charmhelpers.contrib import ansible
from keystoneauth1 import identity as keystone_identity
from keystoneauth1 import session as keystone_session
from keystoneclient.v3 import client as keystone_client

from distutils.spawn import (
    find_executable
)
from charms.reactive import (
    when,
    when_not,
    set_flag,
    hook,
    remove_state,
    set_state,
)
from charmhelpers.core.hookenv import (
    status_set,
    config,
    log,
    ERROR,
    application_version_set,
    resource_get,
    relation_ids,
    relation_get,
    related_units,
)
from charmhelpers.fetch import (
    apt_install,
    apt_update,
)

charm_vm_config = {}
config = config()


def _run_virsh_command(cmd, vmconfig, ignore=False):
    """
    Run virsh command, checking output

    :param: cmd: str: The virsh command to run.
    """
    log_level = ERROR
    if ignore:
        log_level = None
    env = os.environ.copy()
    for key, value in vmconfig.items():
        log('virsh env key:{0} value:{1}'.format(key, value))
        env[key] = str(value)

    try:
        log("execute virsh cmd {0}\n".format(cmd))
        resultstr = subprocess.check_output(cmd, env=env)
    except ValueError:
        log("Error: virsh cmd {0} Failed with error:{1}"
            .format(cmd, resultstr), level=log_level)
        if ignore:
            return
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        log("Error: virsh cmd {0} Failed with error:{1}"
            .format(cmd, e.returncode), level=log_level)
        if ignore:
            return
        sys.exit(1)
    log("virsh cmd result: {0}\n".format(resultstr))
    return resultstr


def validate_ip(ip):
    """Validate TrilioVault IP provided by the user
    TrilioVault IP should not be blank
    TrilioVault IP should have a valid IP address and reachable
    """
    if ip and ip.strip():
        # Not blank
        if netaddr.valid_ipv4(ip):
            # Valid IP address
            return True
        else:
            # Invalid IP address
            return False
    return False


def createbridge(vmconfig):
    _run_virsh_command(
        ['bash', '-c',
         'source ./files/trilio/tvm_install.sh && create_bridge'], vmconfig)
    log("Bridge is successfully created.")


def createvm(vmconfig):
    _run_virsh_command(
        ['bash', '-c',
         'source ./files/trilio/tvm_install.sh && create_vm'], vmconfig)
    log("TrilioVM is successfully created.")


def startvm(vmconfig):
    _run_virsh_command(
        ['bash', '-c',
         'source ./files/trilio/tvm_install.sh && start_vm'], vmconfig)
    log("TrilioVM is successfully started.")


def stopvm(vmconfig):
    _run_virsh_command(
        ['bash', '-c',
         'source ./files/trilio/tvm_install.sh && stop_vm'], vmconfig, True)
    log("TrilioVM is successfully shutdown.")
    return True


def get_vm_ip(vmconfig):
    hosts_ip_list = _run_virsh_command(
        ['bash', '-c',
         'source ./files/trilio/tvm_install.sh && '
         'get_vm_ip_address'], vmconfig)
    return hosts_ip_list.strip()


def install_appliance():
    """Install TrilioVault Appliance VM
    """
    # Read image path from resources attached to the charm
    charm_vm_config['TVM_IMAGE_PATH'] = resource_get('trilioimage')
    # Add the IP address in vmconfig dict
    charm_vm_config['TVM_VIP'] = config['tv-virtual-ip']
    # Read config parameters and add to vmconfig dict
    charm_vm_config['TVM_HOSTNAME'] = config['tvault-hostname']
    charm_vm_config['TVM_NUM_NODES'] = config['tvault-num-nodes']
    charm_vm_config['TVM_MEM'] = config['tvault-memory']
    charm_vm_config['TVM_CPU'] = config['tvault-cpu']

    # Create n/w bridge
    is_bridge_created = createbridge(charm_vm_config)
    if is_bridge_created == 0:
        log("Could not create bridge.")
        return False
    else:
        log("Successfully created bridge.")

    # Create TrilioVault VM
    is_vm_created = createvm(charm_vm_config)
    if is_vm_created == 1:
        log("Could not create {} vm.".format(charm_vm_config['TVM_HOSTNAME']))
        return False
    else:
        log("Successfully created {} vm.".format(
            charm_vm_config['TVM_HOSTNAME']))

    # Start the appliance
    status_set('maintenance', 'Starting...')

    is_vm_started = startvm(charm_vm_config)
    if is_vm_started == 0:
        log("Could not start {} vm.".format(charm_vm_config['TVM_HOSTNAME']))
        return False
    else:
        log("Successfully started {} vm.".format(
            charm_vm_config['TVM_HOSTNAME']))

    charm_vm_config['TVM_HOST_LIST'] = get_vm_ip(charm_vm_config)
    log("HOSTNAMES AND IP ADDRESS LIST --> {}".format(
        charm_vm_config['TVM_HOST_LIST']))

    # Update config parameter tv-controller-nodes
    config['tv-controller-nodes'] = charm_vm_config['TVM_HOST_LIST']
    config['tv-conf-node-ip'] = re.split(
        '=', str(charm_vm_config['TVM_HOST_LIST']))[0]
    log("CONFIG HOSTNAMES AND IP ADDRESS LIST --> {}".format(
        config['tv-controller-nodes']))
    log("TRILIOVAULT NODE IP ADDRESS --> {}".format(
        config['tv-conf-node-ip']))
    # Return True if all conditions passed
    return True


@hook('identity-admin-relation-joined')
def get_keystone_admin():
    try:
        rid = relation_ids('identity-admin')[0]
        units = related_units(rid)
        rdata = relation_get(rid=rid, unit=units[0])
        auth = keystone_identity.Password(
            auth_url='{}://{}:{}/'.format(
                         rdata.get('service_protocol'),
                         rdata.get('service_hostname'),
                         rdata.get('service_port')),
            user_domain_name=rdata.get('service_user_domain_name'),
            username=rdata.get('service_username'),
            password=rdata.get('service_password'),
            project_domain_name=rdata.get('service_project_domain_name'),
            project_name=rdata.get('service_tenant_name'),
            )
        sess = keystone_session.Session(auth=auth)

        keystone = keystone_client.Client(session=sess)
        dm = keystone.endpoints.list(
              keystone.services.list(name='dmapi')[0].id)
        ks = keystone.endpoints.list(
              keystone.services.list(name='keystone')[0].id)
        dm_endpoints = {}
        for i in dm:
            dm_endpoints[i.interface] = i.url

        keystone_endpoints = {}
        for i in ks:
            keystone_endpoints[i.interface] = i.url

        roles_list = keystone.roles.list()
        roles = [i.name for i in roles_list]

        config['tv-os-username'] = rdata.get('service_username')
        config['tv-os-password'] = rdata.get('service_password')
        config['tv-os-domain-id'] = keystone.domains.list(
                                     name=rdata.get(
                                      'service_user_domain_name'))[0].id
        config['tv-os-tenant-name'] = rdata.get('service_tenant_name')
        config['tv-os-region-name'] = rdata.get('service_region')
        config['tv-keystone-admin-url'] = keystone_endpoints.get('admin')
        config['tv-keystone-public-url'] = keystone_endpoints.get('public')
        config['tv-dm-endpoint'] = dm_endpoints.get('internal')
        config['tv-os-trustee-role'] = config['tv-os-trustee-role']\
            if config['tv-os-trustee-role'] else roles[0]
        config.save()
        log("get_keystone_admin: Retrieved admin info")
    except Exception as ex:
        log("get_keystone_admin: Retrieval of admin info failed")
        log(ex)


def configure_appliance():
    log("Starting configuration...")
    status_set('maintenance', 'configuring tvault...')
    try:
        get_keystone_admin()
        ansible.apply_playbook('site.yaml')
        status_set('active', 'Ready...')
    except Exception as e:
        log("ERROR:  {}".format(e))
        log("Check the ansible log in TrilioVault to find more info")
        status_set('blocked', 'configuration failed')


@when_not('trilio-appliance.installed')
def install_trilio_appliance():

    status_set('maintenance', 'Installing...')

    # Validate TrilioVault IP
    if not validate_ip(re.split("/", config['tv-virtual-ip'])[0]):
        # IP address is invalid
        # Set status as blocked and return
        status_set(
            'blocked',
            'Invalid IP address, please provide correct IP address')
        application_version_set('Unknown')
        return

    # Check image path from resources attached to the charm
    if not resource_get('trilioimage'):
        status_set(
            'blocked',
            'Trilioimage resource not available, please provide the image')
        application_version_set('Unknown')
        return

    log("Installing dependent packages")
    dependencies = 'genisoimage qemu-kvm libvirt-bin bridge-utils '\
                   'virtinst cpu-checker'
    apt_update(fatal=True)
    apt_install(dependencies.split(), fatal=True)
    if (find_executable('virsh') is None or
            find_executable('qemu-img') is None):
        status_set('blocked',
                   "Missing virtualization binaries: cannot deploy service"
                   " {}".format(charm_vm_config['TVM_HOSTNAME']))
        return

    # Call install handler to install the packages
    if install_appliance():
        # Install was successful
        # Configure the TrilioVault Appliance
        configure_appliance()
        status_set('active', 'Ready...')
        tv_version = re.search(
            r'\d.\d.\d*', charm_vm_config['TVM_IMAGE_PATH']).group()
        application_version_set(tv_version)
        # Add the flag "installed" since it's done
        set_flag('trilio-appliance.installed')
    else:
        # Install failed
        status_set('blocked', 'Trilio VM installation failed.....retry..')


@hook('stop')
def stop_handler():

    # Set the user defined "stopping" state when this hook event occurs.
    set_state('trilio-appliance.stopping')


@when('trilio-appliance.stopping')
def stop_trilio_appliance():

    status_set('maintenance', 'Stopping...')

    # Set hostname
    charm_vm_config['TVM_HOSTNAME'] = config['tvault-hostname']

    # Call the script to stop and uninstll TrilioVault Appliance
    uninst_ret = stopvm(charm_vm_config)

    if uninst_ret:
        # Uninstall was successful
        # Remove the state "stopping" since it's done
        remove_state('trilio-appliance.stopping')
