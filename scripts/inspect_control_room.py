path=r'd:/Python/MyBot/control_room/control_room.py'
with open(path,'r',encoding='utf-8') as f:
    lines=f.readlines()
for i in range(300,336):
    print(i+1, repr(lines[i]))
