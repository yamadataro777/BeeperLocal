# Xヘッダー（1500x500）を作る。実行: python3 make_header.py
from PIL import Image, ImageDraw, ImageFont
import math
S=2; W,H=1500*S,500*S
F='/System/Library/Fonts/'
def font(name,size,idx=0): return ImageFont.truetype(F+name,size*S,index=idx)
mincho=font('ヒラギノ明朝 ProN.ttc',70,1)
g6=lambda s: font('ヒラギノ角ゴシック W6.ttc',s)
g3=lambda s: font('ヒラギノ角ゴシック W3.ttc',s)
bg='#14171c'; ink='#f3efe6'; red='#d9482b'; red2='#b93a22'; mute='#8b93a1'; sub='#c9c4b8'; line='#5b6472'; card='#1c2027'
im=Image.new('RGB',(W,H),bg); d=ImageDraw.Draw(im)
def t(x,y,s,f,c,sp=0):
    cx=x*S
    for ch in s:
        d.text((cx,y*S),ch,font=f,fill=c); cx+=d.textlength(ch,font=f)+sp*S
t(112,62,'連絡に追われない朝を、AIと作る',g6(22),red,2)
t(108,104,'連絡の仕事を、',mincho,ink,1)
t(108,188,'AIに任せる。',mincho,ink,1)
t(112,286,'その日の場面と作り方を、毎朝8時に。チャットで仕事をする人へ',g3(23),sub)
x=420; y=418
for s,f,c in [('Macアプリ ',g3(21),mute),('Fubako（文箱）',g6(21),ink),(' 開発中　｜　2026.12.1 発売予定',g3(21),mute)]:
    d.text((x*S,y*S),s,font=f,fill=c); x+=d.textlength(s,font=f)/S
ox,oy=900,56
def rr(x,y,w,h,r,fill=None,outline=None,width=1): d.rounded_rectangle([(ox+x)*S,(oy+y)*S,(ox+x+w)*S,(oy+y+h)*S],r*S,fill=fill,outline=outline,width=width*S)
for (x,y,l1,l2) in [(6,20,70,104),(30,112,96,60),(6,204,86,104)]:
    rr(x,y,150,62,14,fill=card,outline=line,width=2)
    for yy,l in [(22,l1),(40,l2)]:
        d.rounded_rectangle([(ox+x+22)*S,(oy+y+yy-2)*S,(ox+x+22+l)*S,(oy+y+yy+2)*S],2*S,fill=mute)
def bez(p0,p1,p2,p3,n=60):
    return [tuple((1-u)**3*a+3*(1-u)**2*u*b+3*(1-u)*u*u*c+u**3*e for a,b,c,e in zip(p0,p1,p2,p3)) for u in [i/n for i in range(n+1)]]
def dotted(pts,gap=9):
    acc=0; prev=pts[0]
    for p in pts[1:]:
        acc+=math.dist(prev,p); prev=p
        if acc>=gap:
            acc=0; d.ellipse([(ox+p[0]-1.4)*S,(oy+p[1]-1.4)*S,(ox+p[0]+1.4)*S,(oy+p[1]+1.4)*S],fill=line)
dotted(bez((166,51),(210,51),(214,128),(250,136)))
dotted(bez((166,235),(210,235),(214,158),(250,150)))
dotted([(190+i,143) for i in range(0,58)])
dotted([(412+i,143) for i in range(0,50)])
rr(256,84,150,34,6,fill=red); rr(264,122,134,84,6,fill=red2)
d.line([((ox+331)*S,(oy+84)*S),((ox+331)*S,(oy+206)*S)],fill=ink,width=3*S)
d.ellipse([(ox+331-11)*S,(oy+120-11)*S,(ox+331+11)*S,(oy+120+11)*S],fill=ink)
d.ellipse([(ox+331-7)*S,(oy+120-7)*S,(ox+331+7)*S,(oy+120+7)*S],fill=bg)
cx,cy,r=510,143,40; pts=[]
for i in range(4):
    a=math.pi/2*i-math.pi/2; pts.append((cx+r*math.cos(a),cy+r*math.sin(a)))
    b=a+math.pi/4; pts.append((cx+r*0.22*math.cos(b),cy+r*0.22*math.sin(b)))
d.polygon([((ox+px)*S,(oy+py)*S) for px,py in pts],fill=ink)
im.resize((1500,500),Image.LANCZOS).save('header.png')
