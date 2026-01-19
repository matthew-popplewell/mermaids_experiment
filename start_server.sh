#!/bin/bash
# start_server.sh

echo 'Cleaning up old processes...'
sudo killall -9 indiserver 2>/dev/null || true
pkill -9 indiserver
pkill -9 indi_staradventurergti_telescope

echo 'Starting INDI Server for 4 GTi mounts...'

# Use the -n flag immediately following each driver binary call
# Ensure there are NO quotes around the driver and its name together
# indiserver -v \
#   indi_staradventurergti_telescope -n Mount_1 \
#   indi_staradventurergti_telescope -n Mount_2 \
#   indi_staradventurergti_telescope -n Mount_3 \
#   indi_staradventurergti_telescope -n Mount_4
indiserver -v indi_staradventurergti_telescope