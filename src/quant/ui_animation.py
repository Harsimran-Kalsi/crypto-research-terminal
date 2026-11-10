"""Decorative ambient renderers, independent of research and execution."""
import math
from rich.text import Text
from textual.widgets import Static
from .ui_theme import palette

class Orbit(Static):
    """Ambient sculptures, strictly decorative; no relation to signal or worker health."""
    phase=0.
    enabled=True
    variant=0
    NAMES=('Trefoil','Orbitals','Wave lattice')

    def on_mount(self):
        self.set_interval(.1,self.animate)

    def animate(self):
        if self.enabled and self.display:
            self.phase+=.055
            self.refresh()

    def on_click(self,event):
        if event.button in (1,3):
            self.app.action_cycle_animation(1)
            event.stop()

    def render(self):
        colors=palette(self.app)
        if not self.enabled:return Text('Animation paused · A to resume',style=colors['muted'])
        w=max(12,min(36,self.content_size.width));h=max(3,self.content_size.height)
        pw,ph=w*2,h*4
        pixels={};a=self.phase
        for i in range(420):
            t=i*2*math.pi/420
            if self.variant==0:
                x=(2+math.cos(3*t))*math.cos(2*t)
                y=(2+math.cos(3*t))*math.sin(2*t)
                z=math.sin(3*t)
            elif self.variant==1:
                ring=i//140;t=(i%140)*2*math.pi/140
                u,v=2.7*math.cos(t),2.7*math.sin(t)
                x,y,z=((u,v,0),(0,u,v),(v,0,u))[ring]
            else:
                x=(i%28)/27*5.4-2.7;y=(i//28)/14*5.4-2.7
                z=.65*math.sin(2*x+a*2)+.45*math.cos(2*y-a*2)
            x,z=x*math.cos(a)+z*math.sin(a),-x*math.sin(a)+z*math.cos(a)
            y,z=y*math.cos(.65)+z*math.sin(.65),-y*math.sin(.65)+z*math.cos(.65)
            px=round((x/3.5+.5*2)/2*(pw-1));py=round((y/3.5+1)/2*(ph-1))
            # Give the curves a little thickness at sub-character resolution.
            for dx,dy in ((0,0),(-1,0),(1,0),(0,-1),(0,1)):
                qx,qy=px+dx,py+dy
                if 0<=qx<pw and 0<=qy<ph:
                    pixels[(qx,qy)]=max(z,pixels.get((qx,qy),-10))
        dots=((1,8),(2,16),(4,32),(64,128));out=Text()
        for r in range(h):
            for c in range(w):
                bits=0;depth=-10
                for dy in range(4):
                    for dx in range(2):
                        key=(c*2+dx,r*4+dy)
                        if key in pixels:bits|=dots[dy][dx];depth=max(depth,pixels[key])
                density=bin(bits).count('1')
                glyph=('█' if density==8 else '▓') if density>=6 and depth>0 else chr(0x2800+bits) if bits else ' '
                out.append(glyph,style=colors['accent'] if depth>0 else colors['muted'])
            out.append('\n')
        return out
