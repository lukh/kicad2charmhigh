from .Feeder import Feeder
from .ICTray import ICTray
from .PartPlacement import PartPlacement


# Convert string to float, default to 0.0
def stof(s, default=0.0):
    try:
        return float(s)
    except ValueError:
        return default

# Convert string to integer, default 0
def stoi(s, default=0):
    try:
        return int(s)
    except ValueError:
        return default

def clear_utf8_characters(str):
    str = str.replace('μ','u')
    str = str.replace('Ω','Ohm')
    return str


def get_working_name(component, feeders):
    # Given a comp ID, return the easy to read name that will be displayed in the software
    # Resolves part to any aliases that may exist
    feeder_ID = locate_feeder_info(component, feeders)

    if feeder_ID == "NoMount": return feeder_ID
    if feeder_ID == "NewSkip": return component.component_name()

    for feeder in feeders:
        if feeder_ID == feeder.feeder_ID:
            return feeder.device_name

def get_feeder(feeder_ID, feeders):
    # Given the feeder ID, return the associated Feeder object
    for feeder in feeders:
        if(feeder.feeder_ID == feeder_ID):
            return feeder
    return Feeder()


def locate_feeder_info(component, feeders):
    # Given a component ID, try to find its name in the available feeders
    # Search the feeder list of aliases as well
    # Returns the ID of the feeder

    component_name = component.component_name()

    for feeder in feeders:
        if component_name == feeder.device_name:
            return feeder.feeder_ID

        elif component_name in feeder.aliases:
            return feeder.feeder_ID


    # If it's not in the feeders look to see if it's a non-mountable device
    # Get the aliases then split them
    nonmount_devices = feeders[-1].aliases.split(':')

    if component_name in nonmount_devices:
        return "NoMount"

    #If we still can't find it mark it as a new feeder but with skip/don't mount
    return "NewSkip"
