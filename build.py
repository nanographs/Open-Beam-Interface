import subprocess
import os
import tomllib
import pathlib
import argparse
import time

config_path = pathlib.Path("Open-Beam-Interface/microscope.toml").expanduser()
print(f"{config_path=}")
config = tomllib.load(open(config_path, "rb") )
pinout = config["pinout"]
pin_args = []
for pin_name in pinout:
    pin_num = pinout.get(pin_name)
    pin_args += ["--pin-"+pin_name, str(pin_num)]

glasgow_cmd = ["glasgow", "build", "--rev", "C3", "open_beam_interface"] + pin_args


env = os.environ._data
env.update({"GLASGOW_OUT_OF_TREE_APPLETS":"I-am-okay-with-breaking-changes"})

glasgow = subprocess.Popen(glasgow_cmd,env=env)

