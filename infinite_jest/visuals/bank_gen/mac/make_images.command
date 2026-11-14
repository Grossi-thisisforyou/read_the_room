#!/usr/bin/env bash
# Double-click this file in Finder to paint images for the INFINITE JEST bank.
# (The first time, macOS may say it can't be opened: right-click it, choose
# Open, then Open again. Run install_mac.sh once before.)
cd "$(dirname "$0")" || exit 1
echo "INFINITE JEST: paint images on this Mac"
echo
printf "How many images? [300] "
read -r n
n="${n:-300}"
case "$n" in *[!0-9]*|"") echo "That's not a number."; read -r -p "Press Return to close."; exit 1;; esac
printf "Also make the 16:9, grey and cut-out versions? [y/N] "
read -r pp
extra=()
case "$pp" in y|Y|yes) extra+=(--postprocess);; esac
echo
./generate_mac.sh --count "$n" "${extra[@]+"${extra[@]}"}"
echo
read -r -p "Finished. Press Return to close this window."
