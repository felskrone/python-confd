#!/bin/bash

NMAP=/usr/bin/nmap
DEVICE=<your_device>

while getopts ":s:g:a:" opt; do
  case $opt in
    a)
      SERVICEIP=("${SERVICEIP[@]}" "$OPTARG");
      ;;
    g)
      GATEWAY="$OPTARG";
      ;;
    s)
      STATE="$OPTARG";
      ;;

    \?)
      echo "Invalid option: -$OPTARG" >&2
      exit 1
      ;;
    :)
      echo "Option -$OPTARG requires an argument." >&2
      exit 1
      ;;
  esac
done

if [ -z $STATE ]; then
        STATE="UNDEFINED"
fi

# send "gratuitous" Ping
for IP in "${SERVICEIP[@]}"
do
        ${NMAP} -sP -e ${DEVICE} -S ${IP} ${GATEWAY}
done
