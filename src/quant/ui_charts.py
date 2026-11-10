"""Theme-aware terminal plots on a real time axis."""
from datetime import datetime, timezone
import math
from rich.text import Text
from textual.widgets import Static
from .ui_theme import palette, CYAN, MUTED, GREEN, RED

def line_plot(points, markers, width, height, window, color=CYAN, muted=MUTED, positive=GREEN, negative=RED):
    """Braille subcell lines; no interpolation across >5s gaps."""
    width=max(12,width);height=max(3,height)
    if not points:
        return Text('Waiting for recorded samples',style=muted)
    end=points[-1][0];start=end-window
    points=[p for p in points if start<=p[0]<=end and math.isfinite(p[1])]
    visible_marks=[m for m in markers if start<=m[0]<=end]
    values=[y for _,y in points]+[v for _,v,_ in visible_marks]
    if not values:return Text('No samples in window',style=muted)
    low,high=min(values),max(values)
    pad=max((high-low)*.06,abs(high)*1e-8,1e-5)
    low-=pad;high+=pad
    pw,ph=width*2,height*4
    pixels=set()
    def xy(t,y):
        return min(pw-1,max(0,round((t-start)/window*(pw-1)))),min(ph-1,max(0,round((high-y)/(high-low)*(ph-1))))
    previous=None
    for t,v in points:
        x,y=xy(t,v);pixels.add((x,y))
        if previous and 0<=t-previous[0]<=5:
            _,px,py=previous
            steps=max(abs(x-px),abs(y-py),1)
            for i in range(steps+1):pixels.add((round(px+(x-px)*i/steps),round(py+(y-py)*i/steps)))
        previous=(t,x,y)
    dots=((1,8),(2,16),(4,32),(64,128))
    marks={}
    for t,v,side in visible_marks:
        x,y=xy(t,v);marks[(x//2,y//4)]=('B',positive) if side=='BUY' else ('S',negative)
    out=Text()
    label_rows={0,height-1,round((height-1)/3),round(2*(height-1)/3)}
    for row in range(height):
        value=high-(high-low)*row/max(1,height-1)
        out.append(('%10.4f │ '%value) if row in label_rows else '           │ ',style=muted)
        for col in range(width):
            marker=marks.get((col,row))
            if marker:
                out.append(marker[0],style='bold '+marker[1]);continue
            bits=0
            for dy in range(4):
                for dx in range(2):
                    if (col*2+dx,row*4+dy) in pixels:bits|=dots[dy][dx]
            out.append(chr(0x2800+bits) if bits else ' ',style=color)
        if row<height-1:out.append('\n')
    out.append('\n             '+datetime.fromtimestamp(start,timezone.utc).strftime('%H:%M'))
    out.append(' '*max(1,width-14)+datetime.fromtimestamp(end,timezone.utc).strftime('%H:%M')+' UTC',style=muted)
    return out


class Plot(Static):
    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        self.points=[];self.markers=[];self.window=180;self.color='accent'

    def render(self):
        colors=palette(self.app)
        return line_plot(self.points,self.markers,max(12,self.content_size.width-14),
                         max(3,self.content_size.height-2),self.window,colors[self.color],colors['muted'],colors['positive'],colors['negative'])
