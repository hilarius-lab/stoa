"""Generate the monochrome H3 shell assets and packed panel byte buffers."""
from pathlib import Path
import os
from PIL import Image, ImageDraw, ImageFont

OUT=Path(__file__).resolve().parents[1]/"assets"
LW,LH=480,800
W,H=800,480

def font(size,bold=False):
    windows=Path(os.environ.get("WINDIR",""))/"Fonts"
    name="segoeuib.ttf" if bold else "segoeui.ttf"
    return ImageFont.truetype(windows/name,size)

def packed(image):
    pixels=image.load();result=bytearray()
    for y in range(H):
        for bx in range(W//8):
            value=0
            for bit in range(8):
                if pixels[bx*8+bit,y]: value|=0x80>>bit
            result.append(value)
    return bytes(result)

def blank():
    """The operating screens are empty backgrounds.

    Status bar, header row and cards are rendered live on the device since the
    H3/H4 drawing layer exists. The previous versions of these files carried a
    pre-rendered mock dashboard, which then showed through underneath whatever
    the firmware drew on top. They also embedded glyphs from a Microsoft system
    face, which the blank version avoids entirely.
    """
    return Image.new("1",(LW,LH),1).rotate(90,expand=True)

for name in ("ready","recording","memo_saved","error"):
    image=blank()
    image.save(OUT/f"{name}.png")
    (OUT/f"{name}.bin").write_bytes(packed(image))
    print(name,"(blank)")

def startup(title,text):
    image=Image.new("1",(LW,LH),1);d=ImageDraw.Draw(image)
    d.text((24,56),"SMART NOTEBOOK",font=font(18,True),fill=0)
    d.line((24,92,456,92),fill=0,width=2)
    d.text((24,132),title,font=font(34,True),fill=0)
    d.multiline_text((24,198),text,font=font(19),fill=0,spacing=10)
    d.line((24,744,456,744),fill=0,width=1)
    d.text((24,760),"Bitte einen Moment warten.",font=font(14),fill=0)
    return image.rotate(90,expand=True)

startup_assets={
    "connecting":startup("Wird gestartet","Speicher, Mikrofon und Netzwerk\nwerden vorbereitet."),
    "connected":startup("Verbunden","Das Notebook ist online.\nDas Dashboard wird geladen."),
    "saved":startup("Gespeichert","Die Einrichtung wurde uebernommen.\nDas Geraet startet anschliessend neu."),
}
# sleep.png/.bin are deliberately NOT generated here: that screen is a
# hand-designed image, packed from an arbitrary source PNG with
# tools/pack_image_asset.py. Regenerating everything in this script must not
# silently overwrite it with a placeholder.

setup_image=Image.new("1",(LW,LH),1);d=ImageDraw.Draw(setup_image)
d.text((24,40),"NOTEBOOK EINRICHTEN",font=font(25,True),fill=0)
d.text((24,86),"1. WLAN-QR scannen",font=font(18,True),fill=0)
d.rectangle((24,122,220,318),outline=0,width=1)
d.text((24,342),"2. Webseiten-QR scannen",font=font(18,True),fill=0)
d.rectangle((24,378,220,574),outline=0,width=1)
d.text((24,610),"Oder: http://192.168.4.1",font=font(16),fill=0)
d.text((24,650),"Hotspot-Passwort:",font=font(15),fill=0)
d.line((24,742,456,742),fill=0,width=1)
startup_assets["setup"]=setup_image.rotate(90,expand=True)
for name,image in startup_assets.items():
    image.save(OUT/f"{name}.png")
    (OUT/f"{name}.bin").write_bytes(packed(image))
    print(name)
