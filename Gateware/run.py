import subprocess
import os
import tomllib
import pathlib
import argparse
import sys


parser = argparse.ArgumentParser()

parser.add_argument('-c', '--config_path', required=False, 
                    #expand paths starting with ~ to absolute
                    type=lambda p: pathlib.Path(p).expanduser(), 
                    help='path to microscope.toml')
subparsers = parser.add_subparsers(title='mode',
                                description='valid obi modes',
                                help='server: launch server at port [PORT]. \n \
                                    script: read script from path /path/to/script')
parser_script = subparsers.add_parser('script')
parser_script.add_argument('script_path',
                    #expand paths starting with ~ to absolute
                    type=lambda p: pathlib.Path(p).expanduser(), 
                    help='path to python script to execute in OBI applet')
parser_script.set_defaults(script=True, server=False)
parser_server = subparsers.add_parser('server')
parser_server.add_argument("port")
parser_server.set_defaults(script=False, server=True)

args = parser.parse_args()

pin_args = []
transform_args = []
if hasattr(args, "config_path"):
    print(f"loading config from {args.config_path}")
    config = tomllib.load(open(args.config_path, "rb") )
    if "pinout" in config:
        pinout = config["pinout"]
        for pin_name in pinout:
            pin_num = pinout.get(pin_name)
            pin_args += ["--pin-"+pin_name, str(pin_num)]
    if "transforms" in config:
        transforms = config["transforms"]
        transform_args += ["--" + x for x in transforms if transforms.get(x) == True]



endpoint_arg = []
if hasattr(args, "server"):
    endpoint_arg += ["tcp::" + args.port]

env = os.environ._data
env.update({"GLASGOW_OUT_OF_TREE_APPLETS":"I-am-okay-with-breaking-changes"})


def run():
    if hasattr(args, "script"):
        glasgow_cmd = ["glasgow", "script", args.script_path, "open_beam_interface", "-V", "5"] + pin_args + transform_args + endpoint_arg
    elif hasattr(args, "server"):
        glasgow_cmd = ["glasgow", "run", "open_beam_interface", "-V", "5"] + pin_args + transform_args + endpoint_arg
    else:
        print("""Choose mode: obi_run script or obi_run server\n
                Examples:\n
                Script mode: obi_run script --config_path path/to/microscope.toml --script_path /path/to/script\n
                Server mode: obi_run server --config_path path/to/microscope.toml 2224""")
        quit()
    glasgow = subprocess.Popen(glasgow_cmd,env=env, stdin=sys.stdin)
    glasgow.communicate()

if __name__ == "__main__":
    run()
