import zipfile, re, sys
from xml.etree import ElementTree as ET
p = sys.argv[1]
ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
z = zipfile.ZipFile(p)
root = ET.fromstring(z.read('word/document.xml').decode('utf-8'))
body = root.find('w:body', ns)

def para_text(el):
    return ''.join(t.text or '' for t in el.iter(W+'t'))

out=[]
def walk(el):
    tag = el.tag.split('}')[1]
    if tag=='p':
        txt=para_text(el)
        style=''
        ppr = el.find('w:pPr', ns)
        if ppr is not None:
            ps = ppr.find('w:pStyle', ns)
            if ps is not None: style = ps.get(W+'val') or ''
        prefix=''
        if style and 'Heading' in style:
            prefix='#'*(int(re.sub(r'\D','',style) or 1))+' '
        out.append(prefix+txt)
    elif tag=='tbl':
        for tr in el.findall('w:tr', ns):
            cells=[para_text(tc).replace('\n',' ') for tc in tr.findall('w:tc', ns)]
            out.append('| '+' | '.join(cells)+' |')
        out.append('')
    elif tag=='sdt':
        for c in el: walk(c)

for c in body: walk(c)
text=re.sub(r'\n{3,}','\n\n','\n'.join(out))
sys.stdout.write(text)
