# A little Python3 app, which queries Ring products and integrates
# them with Fhem
#
# v 1.0.12

import json
import time
import fhem
import getpass
from pathlib import Path
import logging
import threading
import _thread
import sys  # import sys package, if not already imported
from ring_doorbell import Ring, Auth
from oauthlib.oauth2 import MissingTokenError
from _thread import start_new_thread, allocate_lock
import argparse
import pprint

parser = argparse.ArgumentParser(description='Script that polls Ring.com API and informs FHEM in case of dings or motions.')
parser.add_argument('--2fa', dest='twofa', help='the 2fa code')
parser.add_argument('--ring-user', dest='ring_user', help='the ring username')
parser.add_argument('--ring-pass', dest='ring_pass', help='the ring password')
parser.add_argument('--fhem-ip', dest='fhem_ip', help='the fhem ip')
parser.add_argument('--fhem-port', dest='fhem_port', help='the fhem telnet port')
parser.add_argument('--log-level', dest='log_level', help='the log level')
parser.add_argument('--fhem-path', dest='fhem_path', help='the fhem path for video downloads')
parser.add_argument('--ring-poll-frequency', dest='ring_poll_frequency', help='the frequency to poll ring.com')
parser.add_argument('--fhem-readings-updates', dest='fhem_readings_updates', help='the number of seconds to always update fhem readings')

args = parser.parse_args()


cache_file = Path("ring_token.cache")


# CONFIG
if(not args.ring_user): args.ring_user = 'user@foo.bar'
if(not args.ring_pass): args.ring_pass = 'password'
if(not args.fhem_ip): args.fhem_ip   = '127.0.0.1'
if(not args.fhem_port): args.fhem_port = 7072 # Telnet Port
if(not args.log_level): args.log_level = logging.INFO
elif(args.log_level == "DEBUG"): args.log_level = logging.DEBUG
elif(args.log_level == "ERROR"): args.log_level = logging.ERROR
else: args.log_level = loggging.INFO
if(not args.fhem_path): args.fhem_path = '/opt/fhem/www/ring/' # for video downloads
if(not args.ring_poll_frequency): args.ring_poll_frequency = 2 # Poll every x seconds
if(not args.fhem_readings_updates): args.fhem_readings_updates = 120 # fhem readngs alle x Sek. aktualisieren

# thread-related VARs
# checkForVideoRunning = False # safeguard against race-condition

# LOGGING
logger = logging.getLogger('ring_doorbell.doorbot')
logger.setLevel(args.log_level)

# create file handler which logs even debug messages
fh = logging.FileHandler('ring.log')
fh.setLevel(logging.DEBUG)

# create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
fh.setFormatter(formatter)

# add the handlers to the logger
logger.addHandler(fh)
logger.addHandler(ch)

logger = logging.getLogger('fhem_ring')
logger.setLevel(args.log_level)
logger.addHandler(ch)
logger.addHandler(fh)


# Connecting to RING.com
def token_updated(token):
    cache_file.write_text(json.dumps(token))

def otp_callback():
    if(args.twofa): 
        auth_code = args.twofa
        print("Use 2FA code: " + auth_code)
    else: auth_code = input("Ring 2FA code: ")
    return auth_code

if cache_file.is_file():
    auth = Auth("MyProject/1.0", json.loads(cache_file.read_text()), token_updated)
else:
    if(args.ring_user): username = args.ring_user
    else: username = input("Ring Username: ")
    if(args.ring_pass): password = args.ring_pass
    else: password = getpass.getpass("Ring Password: ")
    auth = Auth("MyProject/1.0", None, token_updated)
    try:
        auth.fetch_token(username, password)
    except MissingTokenError:
        auth.fetch_token(username, password, otp_callback())

myring = Ring(auth)
myring.update_data()


fh = fhem.Fhem(args.fhem_ip, args.fhem_port)

def sendFhem(str):
    logger.debug("sending: " + str)
    global fh
    fh.send_cmd(str)

def askFhemForReading(dev, reading):
    logger.debug("ask fhem for reading " + reading + " from device " + dev)
    return fh.get_dev_reading(dev, reading)

def askFhemForAttr(dev, attr, default):
    logger.debug("ask fhem for attribute "+attr+" from device "+dev+" (default: "+default+")")
    fh.send_cmd('{AttrVal("'+dev+'","'+attr+'","'+default+'")}')
    data = fh.sock.recv(32000)
    return data

def setRing(str, dev):
    sendFhem('set Ring_' + dev.name.replace(" ","") + ' ' + str)

def attrRing(str, dev):
    sendFhem('attr Ring_' + dev.name.replace(" ","") + ' ' + str)

def srRing(str, dev):
    sendFhem('setreading Ring_' + dev.name.replace(" ","") + ' ' + str)

num_threads = 0
thread_started = False
lock = allocate_lock()

def getDeviceInfo(dev):
    # dev.update()
    logger.info("Updating device data for device '"+dev.name+"' in FHEM...")
    # from generc.py
    srRing('name ' + str(dev.name), dev)
    srRing('id ' + str(dev.device_id), dev)
    srRing('family ' + str(dev.family), dev)
    srRing('model ' + str(dev.model), dev)
    srRing('address ' + str(dev.address), dev)
    srRing('firmware ' +str(dev.firmware), dev)
    srRing('latitude ' + str(dev.latitude), dev)
    srRing('longitude ' + str(dev.longitude), dev)
    srRing('kind ' + str(dev.kind), dev)
    srRing('timezone ' + str(dev.timezone), dev)
    srRing('WifiName ' + str(dev.wifi_name), dev)
    srRing('WifiRSSI ' + str(dev.wifi_signal_strength), dev)
    srRing('WifiCategory ' + str(dev.wifi_signal_category), dev)
    # from doorbot.py
    srRing('Model ' + str(dev.model), dev)
    srRing('battery ' + str(dev.battery_life), dev)
    srRing('doorbellType ' + str(dev.existing_doorbell_type), dev)
    srRing('subscribed ' + str(dev.subscribed), dev)
    srRing('ringVolume ' + str(dev.volume), dev)
    srRing('connectionStatus ' + str(dev.connection_status), dev)

def pollDevices(devices):
    logger.info("Polling for events")

    waitsec = 0
    while 1:
        for poll_device in devices:
            try:
                myring.update_dings()
                logger.debug("Polling for events with '" + poll_device.name + "'.")
                logger.debug("Connection status '" + poll_device.connection_status + "'.")

                if myring.dings_data:
                    getDeviceInfo(poll_device)
                    dingsEvent = myring.dings_data[0]
                    logger.debug("Dings: " + str(myring.dings_data))
                    logger.debug("State: " + str(dingsEvent["state"]))
                    logger.info("Alert detected at '" + poll_device.name + "'.")
                    logger.debug("Alert detected at '" + poll_device.address + "' via '" + poll_device.name + "'.")
                    alertDevice(poll_device,dingsEvent,str(dingsEvent["state"]))
                time.sleep(args.ring_poll_frequency)
                # reset wait counter
                waitsec = 0
            except Exception as inst:
                logger.debug("No connection to Ring API, still trying...")
            waitsec += 1
            if waitsec > 600:
                logger.debug("Giving up after " + str(waitsec) + "seconds.")
                break

def downloadLatestDingVideo(doorbell,lastAlertID,lastAlertKind):
    logger.debug("Trying to download latest Ding-Video")
    videoIsReadyForDownload = None
    waitsec = 1
    while (videoIsReadyForDownload is None):
        try:
            logger.debug("MP4 save path: "+str(args.fhem_path)+ 'last_'+str(lastAlertKind)+'_video.mp4')
            doorbell.recording_download(
                doorbell.last_recording_id,
                filename=str(args.fhem_path) + 'last_'+str(lastAlertKind)+'_video.mp4',
                override=True)
            logger.debug("Got "+str(doorbell.last_recording_id)+" video for Event "+str(lastAlertID)+
                " from Ring api after "+str(waitsec)+"s")
            videoIsReadyForDownload = True
            srRing('lastDingVideo ' + args.fhem_path + 'last_'+str(lastAlertKind)+'_video.mp4', poll_device)
        except Exception as inst:
            logger.debug("Still waiting for event "+str(lastAlertID)+" to be ready...")
        time.sleep(1)
        waitsec += 1
        if (waitsec > 240):
            logger.debug("Stop trying to find history and video data")
            break

def getLastCaptureVideoURL(doorbell,lastAlertID,lastAlertKind):
    videoIsReadyForDownload = None
    waitsec = 1
    while (videoIsReadyForDownload is None):
        try:
            lastCaptureURL = doorbell.recording_url(lastAlertID)
            logger.debug("Got video captureURL for Event "+str(lastAlertID)+
                " from Ring api after"+str(waitsec)+"s")
            videoIsReadyForDownload = True
            srRing('lastCaptureURL ' + str(lastCaptureURL), doorbell)
            downloadLatestDingVideo(doorbell,lastAlertID,lastAlertKind)
        except Exception as inst:
            logger.debug("Still waiting for event "+str(lastAlertID)+" to be ready...")
            time.sleep(1)
        waitsec += 1
        if (waitsec > 240):
            logger.debug("Stop trying to find history and video data")
            break

def alertDevice(poll_device,dingsEvent,alert):
    # global checkForVideoRunning
    lastAlertID = str(dingsEvent["id"])
    lastAlertKind = str(dingsEvent["kind"])
    logger.debug("lastAlertID:"+str(lastAlertID))
    logger.debug("lastAlertKind:"+str(lastAlertKind))

    srRing('lastAlertDeviceID ' + str(poll_device.device_id), poll_device)
    srRing('lastAlertDeviceName ' + str(poll_device.name), poll_device)
    srRing('lastAlertSipTo ' + str(dingsEvent["sip_to"]), poll_device)
    srRing('lastAlertSipToken ' + str(dingsEvent["sip_token"]), poll_device)


    if (lastAlertKind == 'ding'):
        logger.debug("Signalling ring to FHEM")
        setRing('ring', poll_device)
        srRing('lastAlertType ring', poll_device)
    elif (lastAlertKind == 'motion'):
        logger.debug("Signalling motion to FHEM")
        srRing('lastAlertType motion', poll_device)
        setRing('motion', poll_device)

    _thread.start_new_thread(getLastCaptureVideoURL,(poll_device,lastAlertID,lastAlertKind))

def fhemReadingsUpdate(dev,sleepForSec):
    # fhem device update loop
    while 1:
        myring.update_data()
        getDeviceInfo(dev)
        downloadSnapshot(dev)
        time.sleep(sleepForSec)

def downloadSnapshot(dev):
    # don't let snapshot ever be undefined
    snapshot = False
    try:
        snapshot = dev.get_snapshot()
        if snapshot:
            logger.debug("Snapshot: " + str(snapshot))
            open(args.fhem_path + 'snap.png', "wb").write(snapshot)
    except Exception as inst:
        logger.debug(inst)
        logger.info(dev.name + " has no connection to ring API, continueing... ")
        logger.info("Snapshot: " + str(snapshot))

# GATHERING DEVICES
devs = myring.devices()
logger.debug("Devices: " + str(devs))
all_devices = list(devs['stickup_cams']+devs['doorbots']+devs['authorized_doorbots'])
logger.info("Found " + str(len(all_devices)) + " devices.")
logger.debug(all_devices)

# Start readings update threads
for t in all_devices:
    # start background fhemReadingsUpdate
    t.update_health_data()
    _thread.start_new_thread(fhemReadingsUpdate,(t,args.fhem_readings_updates))


# START POLLING DEVICES
count = 1
while count<6:  # try 5 times
    try:
        while 1:
            pollDevices(all_devices)

    except Exception as inst:
        logger.error("Unexpected error:" + str(inst))
        logger.error("Exception occured. Retrying...")
        time.sleep(5)
        if count == 5:
            raise

        count += 1
