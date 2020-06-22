
import os
import datetime

from .tools import stof, stoi, clear_utf8_characters, get_feeder, get_working_name

def add_header(f, outfile, component_position_file):
    d = datetime.datetime.now()

    f.write("separated\n")
    f.write("FILE,{}\n".format(os.path.basename(outfile)))
    f.write("PCBFILE,{}\n".format(os.path.basename(component_position_file)))
    f.write("DATE,{:02d}/{:02d}/{:02d}\n".format(d.year, d.month, d.day))
    f.write("TIME,{:02d}:{:02d}:{:02d}\n".format(d.hour, d.minute, d.second))
    f.write("PANELYPE,0\n")

def add_feeders(f, feeders):
    # Output used feeders
    f.write("\n")
    f.write("Table,No.,ID,DeltX,DeltY,FeedRates,Note,Height,Speed,Status,SizeX,SizeY,HeightTake,DelayTake\n")

    station_number = 0
    for feeder in feeders:
        if feeder.count_in_design != 0 and feeder.feeder_ID != "NoMount":

            # Mount value explanation:
            # 0b.0000.0ABC
            # A = 1 = Use Vision
            # A = 0 = No Vision
            # B = 1 = Use Vacuum Detection
            # B = 0 = No Vacuum Detection
            # C = 1 = Skip placement
            # C = 0 = Place this component
            # Example: 3 = no place, vac, no vis
            mount_value = 0
            if feeder.place_component == False:
                mount_value += 1
            if feeder.check_vacuum == True:
                mount_value += 2
            if feeder.use_vision == True:
                mount_value += 4


            f.write('Station,{},{},{:.8g},{:.8g},{},{},{:.8g},{},{},{:.8g},{:.8g},{},{}\n'.format(
                station_number,
                feeder.feeder_ID,
                feeder.stack_x_offset,
                feeder.stack_y_offset,
                feeder.feed_spacing,
                feeder.device_name,
                feeder.height,
                feeder.speed,
                mount_value,    # Status
                feeder.component_size_x,
                feeder.component_size_y,
                0,  # HeightTake
                0,  # DelayTake
                ))

            station_number = station_number + 1

def add_batch(f):
    # Batch is where the user takes multiple copies of the same design and mounts them
    # into the machine at the same time.
    # Doing an array is where you have one PCB but X number of copies panelized into an array

    # If you are doing a batch then the header is
    # PANELYPE,0
    # If you are doing an array then the header is
    # PANELYPE,1
    # Typo is correct.

    # When there is a batch of boards it looks like this
    f.write("\n")
    f.write("Table,No.,ID,DeltX,DeltY\n")
    f.write("Panel_Coord,0,1,0,0\n")

    # When you define an array you get this:
    # Table,No.,ID,IntervalX,IntervalY,NumX,NumY
    #  IntervalX = x spacing. Not sure if this is distance between array
    #  NumX = number of copies in X direction
    # Panel_Array,0,1,0,0,2,2

    # If you have an X'd out PCB in the array you can add a skip record.
    # When you add a skip, you get another
    # Panel_Array,1,4,0,0,2,2 # Skip board #4 in the array
    # This doesn't quite make sense but skips will most likely NOT be automated (user will input an X'd out board during job run)

def add_components(f, components, feeders, include_newskip):
    # Example output
    # Table,No.,ID,PHead,STNo.,DeltX,DeltY,Angle,Height,Skip,Speed,Explain,Note
    # EComponent,0,1,1,1,16.51,12.68,0,0.5,6,0,C4, 0.1uF

    f.write("\n")
    f.write("Table,No.,ID,PHead,STNo.,DeltX,DeltY,Angle,Height,Skip,Speed,Explain,Note,Delay\n")

    record_ID = 1
    record_number = 0

    for cmp in components:
        if cmp.feeder_ID == "NoMount":
            continue # Do not include NoMount components in the DPV file

        if cmp.feeder_ID == "NewSkip":
            if not include_newskip:
                continue # No not include NewSkip components unless explicitly asked
            cmp.place_component = False

        working_name = get_working_name(cmp, feeders)

        # 0b.0000.0ABC
        # A = 1 = Use Vision
        # A = 0 = No Vision
        # B = 1 = Use Vacuum Detection
        # B = 0 = No Vacuum Detection
        # C = 1 = Skip placement
        # C = 0 = Place this component
        # Example: 3 = no place, vac, no vis
        mount_value = 0
        if cmp.place_component == False:
            mount_value += 1
        if cmp.check_vacuum == True:
            mount_value += 2
        if cmp.use_vision == True:
            mount_value += 4

        f.write('EComponent,{},{},{},{},{:.8g},{:.8g},{:.4g},{:.8g},{},{},{},{},{}\n'.format(
            record_number,
            record_ID,
            cmp.head,
            cmp.feeder_ID if cmp.feeder_ID != "NewSkip" else 99,
            float(cmp.x),
            float(cmp.y),
            float(cmp.rotation),
            float(cmp.height),
            mount_value,
            cmp.speed,
            cmp.designator,
            working_name,
            0   # Delay
            ))

        record_number += 1
        record_ID += 1

def add_ic_tray(f, ic_trays):
    # Add any IC tray info
    f.write("\n")
    f.write("Table,No.,ID,CenterX,CenterY,IntervalX,IntervalY,NumX,NumY,Start\n")

    for idx, tray in enumerate(ic_trays):
        f.write("ICTray,{},{},{},{},{},{},{},{},{}\n".format(
            idx,
            tray.feeder_ID,
            tray.first_IC_center_X,
            tray.first_IC_center_Y,
            tray.last_IC_center_X,
            tray.last_IC_center_Y,
            tray.number_X,
            tray.number_Y,
            tray.start_IC
        ))


def add_PCB_calibrate(f, fiducials):
    # Flags to say what type and if calibration of the board has been done
    f.write("\n")
    f.write("Table,No.,nType,nAlg,nFinished\n")

    # nType: 0 = use components as calibration marks, 1 = use marks as calibration marks
    # nFinished: ? 0 = you haven't cal'd a board, 1 = you have cal'd the board
    calib_type = 0
    if (len(fiducials) >= 2):
        calib_type = 1

    f.write("PcbCalib,0,{},0,0\n".format(calib_type))


def add_fiducials(f, fiducials):
    # Adds the fiducials or mark information about this board or panel
    # If 2 or more fiducials are detected (designator starts with FID) then they
    # are automatically added. User can still change these later within the CharmHigh
    # software
    # TODO if more than 3 fiducials are detected, select the fiducials to use based on their position (ex: panels)
    f.write("\n")
    f.write("Table,No.,ID,offsetX,offsetY,Note\n")

    if (len(fiducials) >= 2):
        for i in range(min(len(fiducials), 3)):
            f.write("CalibPoint,{},0,{},{},Mark{}\n".format(i, fiducials[i].x, fiducials[i].y, i+1))


def add_calibration_factor(f):
    # Add the calibration factor. This is all the offsets calculated when the
    # PCB is calibrated. We don't have to set anything here because the program
    # will calculate things after user calibrates the PCB.

    f.write("\n")
    f.write("Table,No.,DeltX,DeltY,AlphaX,AlphaY,BetaX,BetaY,DeltaAngle\n")
    f.write("CalibFator,0,0,0,0,0,1,1,0\n") # Typo is required

