#!/usr/bin/env python

"""Auto Port Config
This python script will configure interfaces based on the full mac address or OUI (Organizationally Unique Identifier). 
The script can be run remotely, or on the switch itself, it can also be automatically called when a device is plugged 
into the switch using the Event Handler.
"""


from __future__ import print_function
import argparse
import sys
from jsonrpclib import Server
import ssl
import os
import yaml, json

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    # Legacy Python that doesn't verify HTTPS certificates by default
    pass
else:
    # Handle target environment that doesn't support HTTPS verification
    ssl._create_default_https_context = _create_unverified_https_context

switch = Server( "unix:/var/run/command-api.sock")
apply_default_config = False

def main():
    parser = argparse.ArgumentParser(description='Auto Port Config')
    parser.add_argument('-d', '--debug', action='store_true', help='output debug statements')

    interfaceInfo = parser.add_mutually_exclusive_group(required=True)

    interfaceInfo.add_argument('-i', action='store', dest='inter', help='Interface that has changed state')

    dir_path = os.path.dirname(os.path.realpath(__file__))
    parser.add_argument('-c', action='store', dest='config', default=dir_path + '/auto-port.conf', help='File containting the ouis and config to apply. Default is auto-port.conf in same dir as script')
    parser.add_argument('-a', action='store', dest='address', help='The username password and address to the switch. username:password@ipaddress')

    global options
    options = parser.parse_args()

    if options.address:
        global switch 
        switch = Server("https://{}/command-api".format(options.address))

    configs = parse_config_file(options.config)
    if configs == None:
        print("Could not successfully parse the configuration file")
        quit()

    specificConfig = check_interface_macs(options.inter, configs)
    if specificConfig == None:
        # no configuration to apply was found.  we can terminate
        quit()

    # Check if the interface config matches the proposed config
    if check_interface_config(options.inter, specificConfig):
        quit()

    config_interface(specificConfig, options.inter)

def parse_config_file(_config_file):
    """Parses the proposed configuration file

    this function will first attempt to parse the config as yaml
    should that fail it will try parsing as json

    Parameters
    ----------
    _config_file : str
        Path to the configuration file

    Result:
    -------

    Returns None if the config is not available or parseable, or returns
    a dict of the configuration
    """
 
    configs = None
    with open(_config_file, "r") as config_file:
        # let's try to parse this as yml first.  if that fails, let's try json
        try:
            configs = yaml.safe_load(config_file)
            if options.debug:
                print(" - configuration parsed as YAML")
        except:
            try:
                configs = json.load(config_file)
                if options.debug:
                    print(" - configuration parsed as JSON")
            except:
                if options.debug:
                    print(" - configuration was not parsed")

    return configs

"""

"""
def check_interface_macs(_interface, configs):
    """Checks to see if any OUIs or mac addresses are located on an interface

    Pulls all mac address from the mac address table for an interface. 

    Parameters
    ----------
    _interface : str
        The interface to check
    configs : the global parsed configuration

    Returns
    ----------
    The entry from the configuration where the match exists is returned,
    or None if there wasn't a default or match

    This is not a well optimized algorithm.  search each mac address through the    parsed config and stop once we either find an exact match or an oui match.      we'll be looping over the config for each mac on an interface.  generally
    this is a small list, however it may be large depending on what is on a
    port.  we'll do this string wise.  unfortunately we'll match the first
    exact match, but the last oui match if there is overlap
    """

    specificMatch = None
    ouiMatch = None
    defaultMatch = None

    response = runCMD(["show mac address-table interface " + _interface])
    if options.debug:
        print(response)

    for mac_address in response[1]['unicastTable']['tableEntries']:
        mac_address = clean_mac_address(mac_address['macAddress'])
        interfaceOUI = mac_address[0:6]

        if options.debug:
            print(" mac_address: {}, interfaceOUI: {}".format(mac_address, interfaceOUI))

        # search for this mac in and oui in each entry of the config
        for config in configs['configs']:
            for mac in config['macs']:
                mac = clean_mac_address(mac)
                if mac == "*":
                    if options.debug:
                        print(" - found a default section")
                    defaultMatch = config
                if interfaceOUI == mac:
                    if options.debug:
                        print(" - found an oui section")
                    ouiMatch = config
                if mac_address == mac:
                    if options.debug:
                       print(" - found a specific match")
                    # if this is a specific match we can terminate and skip
                    #  any further checks.
                    return config

        if ouiMatch != None:
            return ouiMatch
        else:
            return defaultMatch
            
def check_interface_config(_interface, _int_config):
    """Checks to see if the interface already has the correct config

    Parameters
    ----------
    _interface : str
        The interface to check
    _int_config : list
        What the config of the interace should be

    Returns
    ----------
    Bool. True if the config is the same. False the configs do not match and the interface needs to be configured.
    """

    response = runCMD(["show running-config interfaces  " + _interface], 'text')

    # Clean up config from switch and put it into a list
    config = response[1]["output"].split("\n")
    config = [line.strip().encode("utf-8") for line in config if line]
    del config[:1]

    if set(config) == set(_int_config['config']):
        if options.debug:
            print(" - Configuration looks to be what we're wanting")
        return True
    else:
        if options.debug:
            print(" - Configuration is not what we want")
        return False

def config_interface(_config, _interface):
    """Sets up command to send to the switch to configure the interface.

    Parameters
    ----------
    _config : list
        The config to apply
    _interface : str
        The interface to configure

    """

    if options.debug:
        print(" - setting the configuration")

    runCMD(["configure", "default interface " + _interface, "interface " + _interface] + _config['config'])


def clean_mac_address(mac):
    """Cleans up the mac address. Removes any standard delimiter and converts it to lowercase

    Parameters
    ----------
    mac : str
        The mac address that needs to be sanitized

    Returns
    ----------
    The sanitized mac address
    """

    return mac.replace(':','').replace('.','').replace('-','').strip().lower()

def runCMD(_cmd, _format='json'):
    """Sends a command to the switch.

    Parameters
    ----------
    _cmd : list
        The command to be ran.
    _format : str, optional
        What format do you want in return. Default is json. Some commands like `show run` do not support json, you have to set the 
        format to text for it to work.

    Returns
    ----------
    The output from the switch.
    """

    try:
        if options.debug:
            print(" - running the following commands")
            print(_cmd)

        return switch.runCmds( version = 1, cmds = ["enable"] + _cmd, format=_format)
    except Exception as e:
        print("Error with connecting to switch! Please try again.", e)
        quit()

if __name__ == "__main__":
    if sys.version_info[:2] <= (2, 7):
        input = raw_input
    main()
