import subprocess
import os
import tomllib
import pathlib
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("port")
args = parser.parse_args()


config_path = pathlib.Path("Open-Beam-Interface/microscope.toml").expanduser()
print(f"{config_path=}")
config = tomllib.load(open(config_path, "rb") )
pinout = config["pinout"]
pin_args = []
for pin_name in pinout:
    pin_num = pinout.get(pin_name)
    pin_args += ["--pin-"+pin_name, str(pin_num)]
endpoint_arg = ["tcp::" + args.port]
glasgow_cmd = ["glasgow", "run", "open_beam_interface", "-V", "5"] + pin_args + endpoint_arg

env = os.environ._data
env.update({"GLASGOW_OUT_OF_TREE_APPLETS":"I-am-okay-with-breaking-changes"})
subprocess.Popen(glasgow_cmd,env=env)
subprocess.Popen(["obi_gui", "--config_path", config_path, args.port])

