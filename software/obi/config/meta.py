from obi.commands import BeamType

from dataclasses import dataclass
import os

@dataclass
class MagCal:
    """
    A collection of magnification calibration points

    Properties
        path (str): Path to .csv file containing calibration record
        m_per_fov(dict): Map of magnifications and corresponding field of view measurements
    """
    path:str
    m_per_fov: dict

    @classmethod
    def from_csv(cls, path:str):
        """
        Create a new MagCal object from a .csv file. 
        The .csv file must be in the format saved by the Magnification Calibration GUI:
        ```
        Beam, {beam type}
        Date, {datetime}
        Magnification, FOV size
        {magnification}, {fov size}
        ```

        Args:
            path (str): Path to .csv file containing calibration record

        Returns:
            MagCal
        """
        mag_cal_dict = {}
        with open(path,"r") as f:
            data = f.read().split('\n')
            cal_table = data[3:]
            for line in cal_table:
                mag, fov = line.split(",")
                mag_cal_dict.update({int(mag):float(fov)})
        return cls(
            path = path,
            m_per_fov = mag_cal_dict
        )
    
    def to_csv(self):
        """
        Format data suitably for saving for a csv file.
        Data must be processed by adding a suitable header before saving.

        Returns:
            str
        """
        s = "Magnification,FOV (m)"
        for k, v in self.m_per_fov.items():
            s += f"\n{k},{v}"
        return s


@dataclass
class Pinout:
    """
    Pinout for the digital IO available in Glasgow ports A and B.

    Properties:
        scan_enable (list): Pins that when active cause the OBI scan signal to override a microscope's internal scan signal
        blank_enable (list): Pins that when active cause the OBI blanking signal to override a microscope's internal blank signal
        blank: (list): Pins that when active (and enabled by blank_enable) cause a beam to blank
    """
    scan_enable: list[int]
    blank_enable: list[int]
    blank: list[int]

    @classmethod
    def from_dict(cls, d:dict):
        scan_enable=None
        blank_enable = None
        blank = None
        if "scan_enable" in d:
            scan_enable=d["scan_enable"]
        if "blank_enable" in d:
            blank_enable=d["blank_enable"]
        if "blank" in d:
            blank=d["blank"]
        return cls(
            scan_enable=scan_enable,
            blank_enable=blank_enable,
            blank = blank
        )
    
    def to_dict(self):
        d = {}
        if self.scan_enable is not None:
            d.update({"scan_enable": self.scan_enable})
        if self.blank_enable is not None:
            d.update({"blank_enable": self.blank_enable})
        if self.blank is not None:
            d.update({"blank": self.blank})
        return d

@dataclass
class BeamSettings:
    type: BeamType
    pinout: Pinout
    mag_cal: MagCal

    @classmethod
    def from_dict(cls, d:dict):
        type = BeamType.NoBeam
        pinout = None
        mag_cal = None
        if "type" in d:
            type = d["type"]
        if "pinout" in d:
            pinout = Pinout.from_dict(d["pinout"]) 
        if "mag_cal_path" in d:
            path = d["mag_cal_path"]
            if os.path.isfile(path):
                print(f"loading calibration from {path}")
                mag_cal = MagCal.from_csv(path)
            else:
                print(f"unable to load calibration from {path}")
        return cls(
            type = type,
            pinout = pinout,
            mag_cal = mag_cal
        )
    
    def to_dict(self):
        d = {}
        if self.pinout is not None:
            d.update({"pinout":self.pinout.to_dict()})
        if self.mag_cal is not None:
            d.update({"mag_cal_path":self.mag_cal.path})
        return d

@dataclass
class ScopeSettings:
    beam_settings: dict({str: BeamSettings})

    @classmethod
    def from_dict(cls, d:dict):
        beams = {}
        for beam_name, beam_dict in d["beam"].items():
            beams.update({beam_name: BeamSettings.from_dict(beam_dict)})
        return cls(
            beam_settings = beams
        )
    
    @classmethod
    def from_toml_file(cls, path="microscope.toml"):
        from tomlkit.toml_file import TOMLFile
        toml_file = TOMLFile(path)
        toml = toml_file.read()
        if "beam" in toml:
            if "electron" in toml["beam"]:
                toml["beam"]["electron"].update({"type": BeamType.Electron})
            if "ion" in toml["beam"]:
                toml["beam"]["ion"].update({"type": BeamType.Ion})
        return cls.from_dict(toml)
    
    def to_toml_file(self, path="microscope.toml"):
        from tomlkit.toml_file import TOMLFile
        from tomlkit.toml_document import TOMLDocument
        from tomlkit.container import Container
        from tomlkit.items import Item
        toml_file = TOMLFile(path)
        old_toml = toml_file.read()
        d = self.to_dict()

        def unpack(from_dict, to_dict):
            for key, value in from_dict.items():
                if key in to_dict:
                    if isinstance(value, dict):
                        old_value = to_dict[key]
                        new_value = unpack(value, old_value)
                        to_dict.update({key:new_value})
                    else:
                        if value is not None:
                            old_value = to_dict[key]
                            if old_value != value:
                                to_dict.update({key:value})
                else:
                    to_dict.update({key:value})
            return to_dict

        new_toml = unpack(d, old_toml)
        print(new_toml.as_string())
        ## FIXME: saving output back to the toml file to be enabled pending further testing
        #toml_file.write(doc)


    def to_dict(self):
        d = {}
        for beam_name, beam_settings in self.beam_settings.items():
            d.update({beam_name:beam_settings.to_dict()})
        return {"beam":d}
        

if __name__ == "__main__":
    scope = ScopeSettings.from_toml_file()
    scope.beam_settings["electron"].mag_cal = MagCal.from_csv("/Users/isabelburgos/Open-Beam-Interface/software/magelectron.csv")
    scope.beam_settings["electron"].pinout.scan_enable = [8]
    scope.to_toml_file()