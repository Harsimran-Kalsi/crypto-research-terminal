"""Small terminal plots on an actual time axis, with explicit missing buckets."""
import math
from rich.text import Text


def chart(points, markers=(), width=68, height=6, window=180):
    canvas=[[' ']*width for _ in range(height)]
    if not points:
        return Text('Waiting for samples',style='dim')
    end=points[-1][0];start=end-window
    visible=[(t,y) for t,y in points if start<=t<=end and math.isfinite(y)]
    low=min(y for _,y in visible);high=max(y for _,y in visible)
    pad=max((high-low)*.05,abs(high)*1e-8,1e-6)
    low-=pad;high+=pad
    def position(t,y):
        x=min(width-1,max(0,int((t-start)/window*(width-1))))
        r=min(height-1,max(0,round((high-y)/(high-low)*(height-1))))
        return r,x
    # Last observation per time bucket; no interpolation through data gaps.
    buckets={}
    for t,y in visible:
        r,x=position(t,y);buckets[x]=r
    for x,r in buckets.items():canvas[r][x]='•'
    for t,y,side in markers:
        if start<=t<=end and low<=y<=high:
            r,x=position(t,y);canvas[r][x]='B' if side=='BUY' else 'S'
    result=Text()
    for r,row in enumerate(canvas):
        label=high-(high-low)*r/(height-1)
        result.append('%11.4f │ '%label,style='dim')
        for cell in row:
            result.append(cell,style='bold green' if cell=='B' else 'bold red' if cell=='S' else 'cyan')
        result.append('\n')
    result.append('             '+('─'*width)+'\n',style='dim')
    result.append('             −%ss%snow\n'%(window,' '*(max(1,width-9))),style='dim')
    result.append('             B buy / S sell · blank buckets = no sample',style='dim')
    return result
