import math
from pathlib import Path

from probe import probe
from project import Project
from util import ffmpeg


def contact_sheet(project: Project, video: Path) -> Path:
    settings, safe = project.style["review"], project.style["safe_zone"]
    columns = settings["columns"]
    rows = math.ceil(probe(video)["duration"] / columns)
    font = project.font_file(project.style["captions"]["font_file"])
    unsafe_zones = (
        f"drawbox=x=0:y=ih*{1 - safe['bottom']}:w=iw:h=ih*{safe['bottom']}:color=red@0.25:t=fill,"
        f"drawbox=x=iw*{1 - safe['right']}:y=0:w=iw*{safe['right']}:h=ih*{1 - safe['bottom']}:color=red@0.25:t=fill"
    )
    stamp = (f"drawtext=fontfile='{font}':text='%{{pts\\:hms}}':x=8:y=8:fontsize=h/24:"
             "fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=4")
    output = video.with_suffix(".sheet.png")
    ffmpeg("-i", video, "-vf",
           f"fps=1,scale={settings['frame_width']}:-2,{unsafe_zones},{stamp},tile={columns}x{rows}:padding=4:color=black",
           "-frames:v", 1, output)
    return output
