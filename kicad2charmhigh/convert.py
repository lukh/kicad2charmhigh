# This takes a KiCad POS file and converts it to a CharmHigh desktop pick and place work file
# Usage: python convert.py MyBoard.POS
# We need to give this script the position file
# Script pulls in feeder data info from a google spreadsheet
# Script outputs to a static file in the directory where the Pick/Place program can read it
# Written by Nathan at SparkFun

# Usage: python convert.py [file name to convert.pos] [directory that contains credentials.txt with trailing\]
# Output will be a workFile.dpv that needs to be copy/pasted into CHJD_SMT\Files directory

import datetime
import sys
import re

import io
import os
import argparse
import logging

# Used for pulling data from g spreadsheet
import csv
import urllib.request, urllib.error, urllib.parse
from collections import OrderedDict

import pyexcel


from .tools import stof, stoi, clear_utf8_characters, get_feeder, get_working_name, locate_feeder_info
from .filegeneration import *
from .Feeder import Feeder
from .ICTray import ICTray
from .PartPlacement import PartPlacement



def load_feeder_info_from_file(path):
    available_feeders = []
    # Read from local file
    logging.info('Fetching feeder data from: {}'.format(path))
    for row in pyexcel.get_array(file_name=path, start_row=1): # skip header
        if(row[0] != "Stop"):
            # Add a new feeder using these values
            available_feeders.append(Feeder(feeder_ID=row[1],
                device_name=clear_utf8_characters(row[2]),
                stack_x_offset=stof(row[3]),
                stack_y_offset=stof(row[4]),
                height=stof(row[5]),
                speed=stoi(row[6]),
                head=stoi(row[7]),
                angle_compensation=stoi(row[8]),
                feed_spacing=stoi(row[9]),
                place_component=(row[10] == 'Y'),
                check_vacuum=(row[11] == 'Y'),
                use_vision=(row[12] == 'Y'),
                centroid_correction_x=stof(row[13]),
                centroid_correction_y=stof(row[14]),
                aliases=row[15]
                ))
        else:
            break # We don't want to read in values after STOP

    logging.info("Feeder update complete")
    return available_feeders

def load_cuttape_info_from_file(path):
    available_feeders = []
    ic_trays = []
    # Read from local file
    logging.info('Fetching CutTape data from: {}'.format(path))
    for row in pyexcel.get_array(file_name=path, start_row=1): # skip header
        # logging.info("ID {}, {} columns".format(row[1], len(row)))
        if(row[0] != "Stop"):
        # Append to feeder list
            # Add a new feeder using these values
            available_feeders.append(Feeder(feeder_ID=row[1],
                device_name=clear_utf8_characters(row[2]),
                stack_x_offset=0,
                stack_y_offset=0,
                height=stof(row[7]),
                speed=stoi(row[8]),
                head=stoi(row[9]),
                angle_compensation=stoi(row[10]),
                feed_spacing=0,#stoi(row[9]),
                place_component=(row[11] == 'Y'),
                check_vacuum=(row[12] == 'Y'),
                use_vision=(row[13] == 'Y'),
                centroid_correction_x=stof(row[14]),
                centroid_correction_y=stof(row[15]),
                aliases=row[16] if len(row) > 16 else ""
                ))

        # Append to the IC Tray Data
            ic_trays.append(ICTray(feeder_ID=row[1],
                first_IC_center_X=stof(row[3]),
                first_IC_center_Y=stof(row[4]),

                last_IC_center_X=stof(row[3]) + stoi(row[6]) * (stoi(row[5]) - 1),
                last_IC_center_Y=stof(row[4]),
                number_X=stoi(row[5]),
                number_Y=1,
                start_IC=0
            ))
        else:
            break # We don't want to read in values after STOP

    logging.info("Feeder update complete")
    return [available_feeders, ic_trays]

def load_component_info(component_position_file):
    # Get position info from file
    componentCount = 0
    components = []
    with open(component_position_file, encoding='utf-8') as fp:
        line = fp.readline()

        while line:
            if(line[0] != '#'):
                line = re.sub(' +',' ',line) #Remove extra spaces
                token = line.split(' ')
                # Add a new component using these values
                cmp = PartPlacement(componentCount,
                    designator=token[0],
                    value=clear_utf8_characters(token[1]),
                    footprint=token[2],
                    x=stof(token[3]),
                    y=stof(token[4]),
                    rotation=stof(token[5])
                    )
                components.append(cmp)

                
                componentCount = componentCount + 1
            line = fp.readline() # Get the next line

    return components

def link_components(components, feeders, offset, mirror_x, board_width):
    for cmp in components:
        #componentName = cmp.component_name()

        # Find this component in the available feeders if possible
        cmp.feeder_ID = locate_feeder_info(cmp, feeders)

        # Find the associated feeder
        feeder = get_feeder(cmp.feeder_ID, feeders)

        # Correct tape orientation (mounted 90 degrees from the board)
        cmp.rotation = cmp.rotation - 90

        # Add an angle compensation to this component (feeder by feeder)
        cmp.rotation = cmp.rotation + feeder.angle_compensation

        # Correct rotations to between -180 and 180
        if(cmp.rotation < -180):
            cmp.rotation = cmp.rotation + 360
        elif(cmp.rotation > 180):
            cmp.rotation = cmp.rotation - 360

        # Mirror rotation if needed
        if(mirror_x):
            cmp.rotation = -cmp.rotation

        # There are some components that have a centroid point in the wrong place (Qwiic Connector)
        # If this component has a correction, use it
        if(cmp.rotation == -180.0):
            cmp.x = cmp.x + feeder.centroid_correction_y
            cmp.y = cmp.y + feeder.centroid_correction_x
        elif(cmp.rotation == 180.0): # Duplicate of first
            cmp.x = cmp.x + feeder.centroid_correction_y
            cmp.y = cmp.y + feeder.centroid_correction_x
        elif(cmp.rotation == -90.0):
            cmp.y = cmp.y + feeder.centroid_correction_y
            cmp.x = cmp.x + feeder.centroid_correction_x
        elif(cmp.rotation == 0.0):
            cmp.x = cmp.x - feeder.centroid_correction_y
            cmp.y = cmp.y - feeder.centroid_correction_x
        elif(cmp.rotation == 90.0):
            cmp.y = cmp.y - feeder.centroid_correction_y
            cmp.x = cmp.x - feeder.centroid_correction_x

        # Assign pick head, speed and other feeder parameters
        cmp.head = feeder.head
        cmp.place_component = feeder.place_component
        cmp.check_vacuum = feeder.check_vacuum
        cmp.use_vision = feeder.use_vision

        # Add any global corrections (offset)
        cmp.y = cmp.y + offset[1]
        cmp.x = cmp.x + offset[0]

        # Add the board width if the file should be mirrored along x
        if (mirror_x):
            cmp.x = cmp.x + board_width


def find_fiducials(components):
    fiducials = []
    # Detect all components whose designator begins with FID and add it to the fiducials list
    for c in components:
        if c.designator.startswith('FID'):
            fiducials.append(c)
    return fiducials


def generate_bom(output_file, components, include_unassigned_components):
    # Generate bom file with feeder_ID info
    # Useful to order components not on the machine
    logging.info("Building BOM file...")
    make_reference = lambda c: (c.footprint, c.value, c.feeder_ID)
    c_dict = OrderedDict() # "ref": [c, c, ...]

    # group components by value_package
    for c in components:
        ref = make_reference(c)
        if ref not in c_dict:
            c_dict[ref] = []

        c_dict[ref].append(c)


    # build data
    out_array = [ [ "Id", "Designator", "Package", "Designator/Value", "Quantity", "AutoMounted", "Feeder Type"] ]
    index = 0
    for c_ref in c_dict:
        comp_list = c_dict[c_ref]
        if not include_unassigned_components and c_ref[2] == "NoMount":
            logging.info("Ignoring {} - {}".format(",".join([str(c.designator) for c in comp_list]), c_ref[0]))
            continue
        if c_ref[2] not in ["NewSkip", "NoMount"]:
            auto_mounted = "True"
            feeder_type = "Feeder" if int(c_ref[2]) < 80 else "Cut Tape"
        else:
            auto_mounted = "False"
            feeder_type = ""
        out_array.append([index, ",".join([str(c.designator) for c in comp_list]), c_ref[0], c_ref[1], len(comp_list), auto_mounted, feeder_type])
        
        index += 1

    pyexcel.save_as(array=out_array, dest_file_name=output_file)
    logging.info("")
    logging.info("Wrote output at {}".format(output_file))


def configure_log(basepath, basename):
    output_log = os.path.join(basepath, 'output', "{basename}.log".format(basename=basename))
    logger = logging.getLogger()

    formatter = logging.Formatter('%(message)s')

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)

    fh = logging.FileHandler(output_log)
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)

    # add ch to logger
    logger.addHandler(ch)
    logger.addHandler(fh)

def main(component_position_file, feeder_config_file, cuttape_config_files, output_folder=None, basename=None, include_newskip=False, offset=[0, 0], mirror_x=False, board_width=0, bom_output_file=None, mounted_list_output=None):
    logging.getLogger().setLevel(logging.INFO)
    
    # basic file verification
    if not os.path.isfile(component_position_file):
        logging.error("{} is not an existing file".format(component_position_file))
        sys.exit(-1)

    if output_folder is None:
        basepath = os.path.dirname(os.path.abspath(component_position_file))
    else:
        basepath = output_folder

    if basename is None:
        basename = "{date}-{basename}".format(date=datetime.datetime.now().strftime("%Y%m%d-%H%M%S"), basename=os.path.splitext(os.path.basename(component_position_file))[0])

    os.makedirs(os.path.join(basepath, 'output'), exist_ok=True)

    configure_log(basepath, basename)

    outfile_bom = os.path.join(basepath, 'output', "{basename}-bom.csv".format(basename=basename))
    mounted_list_output_file = os.path.join(basepath, 'output', "{basename}-mounted-designators.txt".format(basename=basename))

    # Get position info from file
    components = load_component_info(component_position_file)
    components_bom = []
    

    # Load all known feeders from file
    if feeder_config_file is not None:
        feeders_info = load_feeder_info_from_file(feeder_config_file)

    if cuttape_config_files is not None:
        feeders_configs = [[os.path.splitext(os.path.basename(cuttape_config_file))[0], load_cuttape_info_from_file(cuttape_config_file)] for cuttape_config_file in cuttape_config_files]
        feeders_configs[0][0] = "feeders_and_" + feeders_configs[0][0]
        feeders_configs[0][1][0] = feeders_info + feeders_configs[0][1][0]
    else:
        feeders_configs = [["Feeders", [feeders_info, []]]]

    for (cuttape_name, (feeders, ic_trays)) in feeders_configs:
        outfile_dpv = os.path.join(basepath, 'output', "{basename}-{cuttape_name}.dpv".format(basename=basename, cuttape_name=cuttape_name))

        logging.info("")
        logging.info("===============================================")
        logging.info(".............Job: %s..............", cuttape_name)
        link_components(components, feeders, offset, mirror_x, board_width)

        # Detect fiducials in the components list
        fiducials = find_fiducials(components)

        # Mark all the available feeders that have a component in this design
        for cmp in components:
            for feeder in feeders:
                if feeder.feeder_ID == cmp.feeder_ID:
                    feeder.count_in_design += 1

        logging.info("")
        logging.info("Components to mount:")
        for comp in [c for c in components if c.feeder_ID not in ['NoMount', 'NewSkip']]:
            logging.info(comp)

        logging.info("")
        logging.info("Used Feeders:")
        for feeder in feeders:
            if feeder.count_in_design != 0 and feeder.feeder_ID != "NoMount":
                logging.info(feeder)

        logging.info("")
        logging.info("Fiducials:")
        for fid in fiducials:
            logging.info("{}: \t{}\t{}".format(fid.designator, fid.x, fid.y))


        # Output to machine recipe file
        with open(outfile_dpv, 'w', encoding='utf-8', newline='\r\n') as f:
            add_header(f, outfile_dpv, component_position_file)

            add_feeders(f, feeders)

            add_batch(f)

            add_components(f, components, feeders, include_newskip)

            add_ic_tray(f, ic_trays)

            add_PCB_calibrate(f, fiducials)

            add_fiducials(f, fiducials)

            add_calibration_factor(f)

        logging.info("")
        logging.info('Wrote output to {}'.format(outfile_dpv))

        components_bom += [c for c in components if c.feeder_ID not in ['NoMount', 'NewSkip']]
        components = [c for c in components if c.feeder_ID in ['NoMount', 'NewSkip']]

    logging.info("")
    logging.info("Components Not Mounted:")
    for comp in components:
        logging.info(comp)

    components_bom += components

    if bom_output_file == True:
        generate_bom(outfile_bom, components_bom, include_newskip)

    if mounted_list_output == True:
        with open(mounted_list_output_file, 'w') as mnt_cmp_file :
            mounted_des_list = [c.designator for c in components_bom if c.feeder_ID not in ['NoMount', 'NewSkip']]
            mnt_cmp_file.write(",".join(mounted_des_list))
            mnt_cmp_file.write("\n")
        logging.info('Wrote output to {}'.format(mounted_list_output_file))
        

def cli():
    parser = argparse.ArgumentParser(description='Process pos files from KiCAD to this nice, CharmHigh software')
    parser.add_argument('component_position_file', type=str, help='KiCAD position file in ASCII')

    parser.add_argument('--feeder-config-file', type=str, help='Feeder definition file. Supported file formats : csv, ods, fods, xls, xlsx,...')
    parser.add_argument("--cuttape-config-files", type=str, nargs='+', help='Cut Tape Definition file(s). Supported file formats : csv, ods, fods, xls, xlsx,...')

    parser.add_argument('--output-folder', type=str, help='Output folder. default: $PWD(component-file)/output')
    parser.add_argument('--basename', type=str, help='basename for output files')

    parser.add_argument('--bom-file', action="store_true", help='Output BOM file. Generate a BOM with feeder info / NotMounted')
    parser.add_argument('--mounted-list-output', action="store_true", help='writes mounted designator in the file, separated by comma')


    parser.add_argument('--include-unassigned-components', action="store_true", help='Include in the output file the components not associated to any feeder. By default these components will be assigned to feeder 99 and not placed but can still be manually assigned to a custom tray.')

    parser.add_argument('--offset', nargs=2, type=float, default=[0, 0], metavar=('x', 'y'), help='Global offset added to every component.')

    mirror_group = parser.add_argument_group("Processing bottom component files")
    mirror_group.add_argument('--mirror-x', action="store_true", help='Mirror components along X axis. Useful when processing a file with components mounted on the bottom.')

    mirror_group.add_argument('--board-width', type=float, help='Board width in mm. Use in conjunction with --mirror-x to make sure the components are aligned to the bottom left side.')

    args = parser.parse_args()

    main(args.component_position_file, args.feeder_config_file, args.cuttape_config_files, args.output_folder, args.basename, args.include_unassigned_components, args.offset, args.mirror_x, args.board_width, args.bom_file, args.mounted_list_output)


if __name__ == '__main__':
    cli()