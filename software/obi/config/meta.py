from obi.commands import BeamType

from dataclasses import dataclass
import os


@dataclass
class MagCal:
    m_per_fov: dict

    @classmethod
    def from_dict(cls, d:dict):
        return cls(
            m_per_fov = {int(k): float(v) for k,v in d.items()}
        )
    
    def to_dict(self):
        return {str(k): float(v) for k,v in self.m_per_fov.items()}
    
    def to_csv(self):
        s = "Magnification,FOV (m)"
        for k, v in self.m_per_fov.items():
            s += f"\n{k},{v}"
        return s

    @classmethod
    def from_csv(cls, path:str):
        mag_cal_dict = {}
        with open(path,"r") as f:
            data = f.read().split('\n')
            cal_table = data[3:]
            for line in cal_table:
                mag, fov = line.split(",")
                mag_cal_dict.update({mag:fov})
        return cls.from_dict(mag_cal_dict)


@dataclass
class Pinout:
    scan_enable: list[int]
    blank_enable: list[int]
    blank: list[int]

    @classmethod
    def from_dict(cls, d:dict):
        return cls(
            scan_enable=d["scan_enable"],
            blank_enable=d["blank_enable"],
            blank = d["blank"]
        )
    
    def to_dict(self):
        return {
            "scan_enable": self.scan_enable,
            "blank_enable": self.blank_enable,
            "blank": self.blank
        }

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
        if self.pinout is not None:
            pinout=self.pinout.to_dict()
        else:
            pinout={}
        if self.mag_cal is not None:
            mag_cal = {"m_per_fov":self.mag_cal.to_dict()}
        else:
            mag_cal = {}
        return {
            "pinout": pinout,
            "mag_cal": mag_cal
        }
    

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
        toml["beam"]["electron"].update({"type": BeamType.Electron})
        toml["beam"]["ion"].update({"type": BeamType.Ion})
        return cls.from_dict(toml)
    
    def to_toml_file(self, path="microscope.toml"):
        from tomlkit.toml_file import TOMLFile
        from tomlkit.toml_document import TOMLDocument
        toml_file = TOMLFile(path)
        old_toml = toml_file.read()
        #doc = TOMLDocument()
        #doc.update(self.to_dict())
        d = self.to_dict()

        def unpack(from_dict, to_dict):
            print(f"unpack {from_dict=}")
            for key, value in from_dict.items():
                if isinstance(value, dict):
                    print(f"unpack {key=} ({value=})")
                    to_dict[key] = unpack(value, {})
                else:
                    print(f"{key=} : {value=}")
                    if value is not None:
                        to_dict[key] = value
            return to_dict

        print(old_toml.as_string())
        old_toml = unpack(d, old_toml)

        print(old_toml.as_string())
        #toml_file.write(doc)


    def to_dict(self):
        d = {}
        for beam_name, beam_settings in self.beam_settings.items():
            d.update({beam_name:beam_settings.to_dict()})
        return {"beam":d}
        

if __name__ == "__main__":
    scope = ScopeSettings.from_toml_file()
    # m = {
    #     "10": 1.3,
    #     "100": 1.2
    # }
    #mag_cal = MagCal.from_dict(m)
    #scope.beam_settings["electron"].mag_cal = mag_cal
    #scope.to_toml_file()
