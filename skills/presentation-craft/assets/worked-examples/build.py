"""Rebuild editable SVG examples. All figures and organizations are fictional."""
from pathlib import Path
from html import escape
import json
R=Path(__file__).resolve().parent

def text(x,y,value,size=28,fill='#142b3b',weight='normal'):
    return f'<text x="{x}" y="{y}" font-family="Arial,sans-serif" font-size="{size}" fill="{fill}" font-weight="{weight}">'+''.join(f'<tspan x="{x}" dy="{0 if i==0 else size*1.35}">{escape(t)}</tspan>' for i,t in enumerate(value.split('\n')))+'</text>'
def rect(x,y,w,h,c):return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}"/>'
def line(x,y,X,Y,c='#376b73',width=3,arrow=False):
    marker = 'url(#arrow)' if arrow else 'none'
    return f'<path d="M{x} {y}L{X} {Y}" stroke="{c}" stroke-width="{width}" fill="none" marker-end="{marker}"/>'
def save(name,body):
    (R/(name+'.svg')).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">'+'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="#376b73"/></marker></defs>'+rect(0,0,1280,720,'#f4f1e9')+body+text(50,687,'Учебный пример · все данные вымышлены',16,'#61717a')+'</svg>')
data=[{'id':'decision','question':'Что выбрать при ограничении срока 7 дней?','facts':{'А':[80,10,12],'Б':[95,5,24],'В':[110,3,12]},'units':['тыс. ₽','дней','месяцев гарантии'],'change':'Одинаковые показатели поставлены в общие строки; срок сопоставлен с условием.'},
{'id':'mechanism','question':'Когда заявка возвращается заявителю?','facts':['Заявка','Проверка комплектности','Не хватает документов → уточнение','Комплект полный → решение'],'change':'Добавлены условие развилки и обратная связь, сохранены обе ветви.'},
{'id':'fund-flows','question':'Кто кому и что передаёт при финансировании проекта?','facts':[
    {'from':'Пайщики','to':'ЗПИФ','label':'Оплата паёв'},
    {'from':'ЗПИФ','to':'Пайщики','label':'Паи'},
    {'from':'ЗПИФ','to':'Проектная компания','label':'Вклад в капитал'},
    {'from':'Проектная компания','to':'ЗПИФ','label':'Дивиденды'},
    {'from':'Банк','to':'Проектная компания','label':'Кредит'},
    {'from':'Проектная компания','to':'Банк','label':'Погашение и проценты'},
],'change':'У встречных потоков появились отдельные маршруты и подписи рядом с линиями.'},
{'id':'project','question':'Что именно сделала команда для музея?','facts':['Задача: подготовить цифровые описания 24 экспонатов','Работа: сверка карточек, съёмка, редактура описаний','Результат: 24 проверенные карточки за 6 недель'],'change':'Свойства команды заменены описанием её работы и подтверждённого результата.'},
{'id':'learning','question':'Как вычислить цену после скидки 20%?','facts':['Исходная цена 1000 ₽','20% от 1000 = 200 ₽','1000 − 200 = 800 ₽','Попробуй: исходная цена 1500 ₽, скидка 20%; ответ 1200 ₽'],'change':'Правило показано на вычислении; добавлены новая попытка и проверка.'}]
(R/'materials.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
# Comparison: identical underlying facts, different arrangement.
save('decision-before',text(50,90,'Предложения поставщиков',48)+''.join(text(55+i*410,210,f'{k}\nЦена: {v[0]} тыс. ₽\nСрок: {v[1]} дней\nГарантия: {v[2]} месяцев',28) for i,(k,v) in enumerate(data[0]['facts'].items()))+text(50,540,'Нужно получить поставку не позднее 7 дней',30))
b=text(50,80,'Срок исключает предложение А',48)+text(50,130,'Условие: поставка не позднее 7 дней',25)
for j,(label,vals) in enumerate([('Цена, тыс. ₽',[80,95,110]),('Срок, дней',[10,5,3]),('Гарантия, мес.',[12,24,12])]):
 y=285+j*105;b+=line(50,y+40,1230,y+40,'#b9c5c5',1)+text(50,y,label,27)
 for i,val in enumerate(vals):b+=text(470+i*260,y,str(val),44,'#ad3d2f' if j==1 and i==0 else '#142b3b')
for i,k in enumerate(['А','Б','В']):b+=text(470+i*260,200,k,36,weight='bold')
b+=text(50,625,'Б дешевле В на 15 тыс. ₽, В быстрее на 2 дня',28);save('decision-after',b)
save('mechanism-before',text(50,90,'Обработка заявки',48)+text(55,235,'Заявитель\nДокументы',32)+text(460,235,'Проверка\nкомплектности',32)+text(900,235,'Решение',32)+text(50,500,'При нехватке документов требуется уточнение',29))
b=text(50,80,'Неполная заявка возвращается на уточнение',44)+rect(55,265,270,100,'#dce8e6')+text(80,325,'Заявка',36)+rect(450,265,350,100,'#164a55')+text(475,325,'Все документы?',34,'white')+rect(955,265,270,100,'#dce8e6')+text(980,325,'Решение',34)+line(325,315,445,315,arrow=True)+line(800,315,950,315,arrow=True)+text(835,290,'да',24)+line(625,365,625,500)+line(625,500,190,500)+line(190,500,190,370,arrow=True)+text(670,440,'нет',24)+text(230,550,'Уточнение и дополнение',27)
save('mechanism-after',b)

# Both versions use the same participants and six flows.
flow_facts = next(example['facts'] for example in data if example['id'] == 'fund-flows')
participants = {
    'Пайщики': (50, 255, 230, 168, 'Пайщики'),
    'ЗПИФ': (505, 255, 200, 168, 'ЗПИФ'),
    'Проектная компания': (970, 255, 260, 168, 'Проектная\nкомпания'),
    'Банк': (505, 535, 200, 90, 'Банк'),
}


def connector(points, bidirectional=False):
    path = 'M' + ' L'.join(f'{x} {y}' for x, y in points)
    start_marker = ' marker-start="url(#arrow)"' if bidirectional else ''
    return f'<path d="{path}" stroke="#376b73" stroke-width="3" fill="none"{start_marker} marker-end="url(#arrow)"/>'


def flow_diagram(routes, bidirectional=False):
    diagram = text(50, 88, 'Финансирование проекта через ЗПИФ', 48)
    for x, y, width, height, label in participants.values():
        diagram += rect(x, y, width, height, '#dce8e6')
        baseline = y + height / 2 + (12 if '\n' not in label else -12)
        diagram += text(x + 24, baseline, label, 33, weight='bold')
    for points, labels in routes:
        diagram += connector(points, bidirectional)
        for index, x, y in labels:
            diagram += text(x, y, flow_facts[index]['label'], 22)
    return diagram


save('fund-flows-before', flow_diagram([
    ([(280, 340), (505, 340)], [(0, 310, 301), (1, 310, 327)]),
    ([(705, 340), (970, 340)], [(2, 730, 301), (3, 730, 327)]),
    ([(705, 580), (1100, 580), (1100, 423)], [(4, 727, 541), (5, 727, 567)]),
], bidirectional=True))

save('fund-flows-after', flow_diagram([
    ([(280, 308), (505, 308)], [(0, 310, 295)]),
    ([(505, 379), (280, 379)], [(1, 310, 366)]),
    ([(705, 308), (970, 308)], [(2, 730, 295)]),
    ([(970, 379), (705, 379)], [(3, 730, 366)]),
    ([(705, 556), (1030, 556), (1030, 423)], [(4, 727, 543)]),
    ([(1180, 423), (1180, 616), (705, 616)], [(5, 727, 603)]),
]))

save('project-before',text(50,90,'О нашей команде',48)+text(50,220,'Опытные специалисты\nКомплексный подход\nВысокое качество\nИндивидуальное решение',36)+text(50,570,'Музей · цифровой каталог',30))
save('project-after',text(50,85,'Цифровой каталог: 24 экспоната за 6 недель',44)+text(50,180,'Задача музея',24,'#526873')+text(50,225,'Подготовить проверенные\nцифровые описания',35)+rect(50,305,760,270,'#dce8e6')+text(80,355,'Работа команды',24)+text(80,410,'Сверка карточек\nСъёмка экспонатов\nРедактура описаний',34)+text(900,345,'24',130,'#164a55')+text(900,405,'карточки',32)+text(900,510,'6 недель',46)+text(50,625,'Результат: сведения собраны и проверены для каталога',26))
save('learning-before',text(50,90,'Проценты и скидки',48)+text(50,220,'Чтобы вычислить скидку, нужно умножить\nисходную цену на процент скидки,\nразделить на сто и вычесть результат\nиз исходной цены.',34)+text(50,540,'При скидке 20% товар стоит дешевле',32))
save('learning-after',text(50,80,'Скидка 20%: сначала находим сумму скидки',43)+text(50,190,'Исходная цена',25)+text(50,260,'1000 ₽',68)+rect(50,310,850,80,'#164a55')+text(78,365,'1000 × 20 / 100 = 200 ₽',43,'white')+rect(730,310,170,80,'#d88b41')+text(50,470,'1000 − 200 = 800 ₽',58)+text(50,555,'Попробуй: цена 1500 ₽, скидка 20%. Сколько платить?',29)+text(50,625,'Проверка: скидка 300 ₽; платить 1200 ₽',26,'#526873'))
