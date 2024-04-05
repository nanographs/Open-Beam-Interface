import subprocess
import os
import tomllib

config = tomllib.load(open("microscope.toml", "rb") )
pinout = config["pinout"]
pin_args = []
for pin_name in pinout:
    pin_num = pinout.get(pin_name)
    pin_args += ["--pin-"+pin_name, str(pin_num)]
glasgow_cmd = ["glasgow", "run", "open_beam_interface", "-V", "5"] + pin_args + ["tcp::2223"]
print(glasgow_cmd)

env = os.environ._data
env.update({"GLASGOW_OUT_OF_TREE_APPLETS":"I-am-okay-with-breaking-changes"})
subprocess.Popen(glasgow_cmd,env=env)
subprocess.Popen(["obi_gui", "--config-path", "microscope.toml"])

