#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os.path

MPATH = "44'/77'/"
WIF_PREFIX = 212 # 212 = d4
MAGIC_BYTE = 30
TESTNET_WIF_PREFIX = 239
TESTNET_MAGIC_BYTE = 139
DEFAULT_PROTOCOL_VERSION = 70913
MINIMUM_FEE = 0.0001    # minimum PIV/kB
starting_width = 1033
starting_height = 785
log_File = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lastLogs.html')