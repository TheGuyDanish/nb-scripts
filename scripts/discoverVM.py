##############################################
# DiscoverVM.py
# By Oliver Møller
# https://github.com/theguydanish
##############################################
# This script is intended for use with NetBox
# and was developed with NetBox 2.6.3.
# https://github.com/theguydanish/nbscripts
# https://github.com/netbox-community/netbox
##############################################
# TODO:
# Script stops on duplicate VM names and can
# thus only run once for an environemnt.
# Filtering based on VMware clusters.
##############################################

from django.utils.text import slugify
from extras.scripts import *
from virtualization.models import *
from virtualization.constants import *
from dcim.models import Interface
from dcim.constants import *
from ipam.models import IPAddress

from pyVmomi import vim
from pyVim.connect import SmartConnectNoSSL, Disconnect

import atexit
import json

vmdata = {}

class discoverVMs(Script):
    script_name = "Discover VMs"
    script_description = "Discover VMs from a vCenter and add to NetBox."
    script_fields = ['vcenter_host', 'vcenter_user', 'vcenter_password']

    vcenter_host = StringVar(
        description="vCenter Hostname"
    )
    vcenter_user = StringVar(
        description="vCenter Username"
    )
    vcenter_password = StringVar(
        description="vCenter Password"
    )
    cluster = ObjectVar(
        description="Cluster to add VMs to",
        queryset=Cluster.objects.filter(
            type__name='ESXi'
        )
    )
    
    def run(self, data):
        host=data['vcenter_host']
        user=data['vcenter_user']
        password=data['vcenter_password']
        vmCount = 0
        ipCount = 0
        intCount = 0

        si = SmartConnectNoSSL(host=host,user=user,pwd=password,port=int(443))
        if si:
            self.log_success("Connected to vCenter!")

        if not si:
            self.log_failure("Couldn't connect to vCenter with the given credentials.")
            return -1

        atexit.register(Disconnect, si)

        content = si.RetrieveContent()
        children = content.rootFolder.childEntity
        for child in children:
            dc = child
            vmdata[dc.name] = {}
            clusters = dc.hostFolder.childEntity
            for cluster in clusters:
                self.log_info(f"Found Cluster: {cluster}")
                vmdata[dc.name][cluster.name] = {}
                hosts = cluster.host
                for host in hosts:
                    self.log_info(f"Found Host: {host}")
                    hostname = host.summary.config.name
                    vmdata[dc.name][cluster.name][hostname] = {}
                    vms = host.vm
                    self.log_info(f"DC Name: {vmdata[dc.name]}")
                    self.log_info(f"Cluster Name: {vmdata[dc.name][cluster.name]}")
                    for vm in vms:
                        newVM = VirtualMachine(
                            name=vm.summary.config.name,
                            cluster=data['cluster'],
                            status=DEVICE_STATUS_ACTIVE,
                            vcpus=str(vm.summary.config.numCpu),
                            memory=vm.summary.config.memorySizeMB,
                            disk=str(int(float("%.2f" % (vm.summary.storage.committed / 1024**3))))
                        )
                        newVM.save()
                        vmResult = VirtualMachine.objects.get(name=vm.summary.config.name)
                        self.log_success("Created new VM: {}".format(newVM))
                        vmCount = vmCount+1
                        nics = {}
                        num = 1
                        for nic in vm.guest.net:
                            if nic.network:
                                if nic.ipConfig is not None and nic.ipConfig.ipAddress is not None:
                                    ipconf = nic.ipConfig.ipAddress
                                    i = 0
                                    for ip in ipconf:
                                        if ":" not in ip.ipAddress:
                                            ipv4c = f"{ip.ipAddress}/{ip.prefixLength}"
                                            nicDescription=nic.network
                                            nicName = f"NIC{num}"
                                            newInt = Interface(
                                                virtual_machine=vmResult,
                                                name=nicName,
                                                description=nicDescription,
                                                type=IFACE_TYPE_VIRTUAL,
                                                mac_address=nic.macAddress
                                            )
                                            newInt.save()
                                            intCount=intCount+1
                                            intResult = Interface.objects.get(name=nicName,mac_address=nic.macAddress)
                                            self.log_info(f"Created new interface: {newInt} - {nic.macAddress}")
                                            newIP = IPAddress(
                                                family='4',
                                                address=ipv4c,
                                                description=f"{vm.summary.config.name} - {nicName}",
                                                interface=intResult
                                            )
                                            newIP.save()
                                            ipCount = ipCount+1
                                            num = num+1
                                            self.log_info(f"Created new IP: {newIP} - {nicName} - {nicDescription}")
                                    i = i+1

        self.log_info(f"Created {vmCount} VMs, {ipCount} IPs, and {intCount} interfaces.")
