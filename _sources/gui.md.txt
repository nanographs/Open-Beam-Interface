# OBI GUI
All of the following instructions should be run in the directory `Open-Beam-Interface/software`.
## Installation
Install the dependencies for the GUI:
```
pdm lock -G gui
pdm install -G gui
```

## Running the GUI
Launch the OBI server:
```
pdm run launch
```
In a separate thread (open another terminal window), launch the GUI:
```
pdm run gui
```