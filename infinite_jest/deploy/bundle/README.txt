INFINITE JEST - offline install bundle
======================================

This folder has everything the Raspberry Pi needs. No internet is needed on the Pi.

ON THE PI (screen + keyboard, or ssh from the Mac):

  1. Plug this USB stick into one of the Pi's blue USB ports.
  2. Type this one line and press Enter:

       sudo mount -L IJ /mnt && sudo bash /mnt/IJ-BUNDLE/INSTALL.sh

     If it says "can't find LABEL=IJ", the stick has another name. Use:

       sudo mount /dev/sda1 /mnt && sudo bash /mnt/IJ-BUNDLE/INSTALL.sh

     (and if THAT says "wrong fs type", try /dev/sda2 instead of /dev/sda1)

  3. Wait. The first time takes 20 to 40 minutes (it compiles the language
     model program for the Pi). It ends with a health check and a summary.
  4. sudo umount /mnt     then pull the stick out.

LATER, to put new code on the Pi (fast, keeps everything else):

       sudo mount -L IJ /mnt && sudo bash /mnt/IJ-BUNDLE/INSTALL.sh --code-only

IF SOMETHING GOES WRONG: the installer copies its log into IJ-BUNDLE/logs/ on
this stick. Open it on the Mac or give it to Claude.

What's in here: manifest.json (what and which versions), debs/ (system
packages for Raspberry Pi OS trixie and/or bookworm), src/ (llama.cpp source),
models/ (the language model), code/ (the show).
