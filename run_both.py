import subprocess
import os
import tomllib
import pathlib

config_path = pathlib.Path("microscope.toml").expanduser()
config = tomllib.load(open(config_path, "rb") )
pinout = config["pinout"]
pin_args = []
for pin_name in pinout:
    pin_num = pinout.get(pin_name)
    pin_args += ["--pin-"+pin_name, str(pin_num)]
glasgow_cmd = ["glasgow", "run", "open_beam_interface", "-V", "5"] + pin_args + ["tcp::2223"]

env = os.environ._data
env.update({"GLASGOW_OUT_OF_TREE_APPLETS":"I-am-okay-with-breaking-changes"})
subprocess.Popen(glasgow_cmd,env=env)
subprocess.Popen(["obi_gui", "--config-path", config_path])

