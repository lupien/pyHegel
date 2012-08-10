#!/bin/bash
# This script is needed because the shebang line (#!) can only have
# one argument in linux. Here I need two.

#pyHegel=${0%pyHegel.sh}pyHegel.py
pyHegel=`dirname "$0"`/pyHegel.py

ipython --pylab -i "$pyHegel"
