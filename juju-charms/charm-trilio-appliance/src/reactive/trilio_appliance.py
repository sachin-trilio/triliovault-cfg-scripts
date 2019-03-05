import os
import re
import netaddr
import sys
import subprocess

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
)
from charmhelpers.fetch import (
    apt_install,
    apt_update,
)

charm_vm_config = {}


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
    _run_virsh_command(
        ['bash', '-c',
         'source ./files/trilio/tvm_install.sh && '
         'get_vm_ip_address'], vmconfig)


def install_appliance():
    """Install TrilioVault Appliance VM
    """
    # Read image path from resources attached to the charm
    charm_vm_config['TVM_IMAGE_PATH'] = resource_get('trilioimage')
    # Add the IP address in vmconfig dict
    charm_vm_config['TVM_VIP'] = config('tvault-vip')
    # Read config parameters and add to vmconfig dict
    # charm_vm_config['TVM_IMAGE_PATH'] = config('tvault-image-path')
    charm_vm_config['TVM_HOSTNAME'] = config('tvault-hostname')
    charm_vm_config['TVM_NUM_NODES'] = config('tvault-num-nodes')
    # charm_vm_config['TVM_DNS'] = config('tvault-dns')
    # charm_vm_config['TVM_NETMASK'] = config('tvault-netmask')
    # charm_vm_config['TVM_GATEWAY'] = config('tvault-gateway')
    charm_vm_config['TVM_MEM'] = config('tvault-memory')
    charm_vm_config['TVM_CPU'] = config('tvault-cpu')
    # charm_vm_config['TVM_BRIDGE'] = config('tvault-bridge')

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
        get_vm_ip(charm_vm_config)

    # Return True if all conditions passed
    return True


@when_not('trilio-appliance.installed')
def install_trilio_appliance():

    status_set('maintenance', 'Installing...')

    # Validate TrilioVault IP
    if not validate_ip(config('tvault-vip')):
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
    charm_vm_config['TVM_HOSTNAME'] = config('tvault-hostname')

    # Call the script to stop and uninstll TrilioVault Appliance
    uninst_ret = stopvm(charm_vm_config)

    if uninst_ret:
        # Uninstall was successful
        # Remove the state "stopping" since it's done
        remove_state('trilio-appliance.stopping')
