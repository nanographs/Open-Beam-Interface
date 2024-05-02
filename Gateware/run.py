import subprocess
import os
import tomllib
import pathlib
import argparse
import sys


parser = argparse.ArgumentParser()
parser.add_argument("port")
parser.add_argument('-c', '--config_path', required=False, 
                    #expand paths starting with ~ to absolute
                    type=lambda p: pathlib.Path(p).expanduser(), 
                    help='path to microscope.toml')
parser.add_argument('-s','--script_path', required=False, 
                    #expand paths starting with ~ to absolute
                    type=lambda p: pathlib.Path(p).expanduser(), 
                    help='path to python script to execute in OBI applet')
args = parser.parse_args()

pin_args = []
if args.config_path:
    print(f"loading config from {args.config_path}")
    config = tomllib.load(open(args.config_path, "rb") )
    if hasattr(config, "pinout"):
        pinout = config["pinout"]
        for pin_name in pinout:
            pin_num = pinout.get(pin_name)
            pin_args += ["--pin-"+pin_name, str(pin_num)]

endpoint_arg = []
if args.port:
    endpoint_arg += ["tcp::" + args.port]

env = os.environ._data
env.update({"GLASGOW_OUT_OF_TREE_APPLETS":"I-am-okay-with-breaking-changes"})


def run():
    if args.script_path:
        glasgow_cmd = ["glasgow", "script", args.script_path, "open_beam_interface", "-V", "5"] + pin_args + endpoint_arg
    else:
        glasgow_cmd = ["glasgow", "run", "open_beam_interface", "-V", "5"] + pin_args + endpoint_arg
    glasgow = subprocess.Popen(glasgow_cmd,env=env, stdin=sys.stdin)
    glasgow.communicate()

