to install out-of-tree glasgow applet, after installing glasgow:
```
pipx inject glasgow Open-Beam-Interface/Gateware
```

to install obi_run entrypoint:
```
pipx install Open-Beam-Interface/Gateware
```

to run:
```
obi_run [port] --config-path path/to/microscope.toml 
```

to run as script:
```
obi_run [port] --config-path path/to/microscope.toml --script_path path/to/script.py
```
