import json
import copy
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/presentation-craft/scripts'))
import pptx_review as pr
import pptx_layout as pl
from test_pptx_review import deck,pack,change,rels,P,A,R


def shape(ident,x,y,w,h,text='Text',size=24,font='Main',rotation=0):
    sz=f' sz="{int(size*100)}"' if size else ''
    family=f'<a:latin typeface="{font}"/>' if font else ''
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{ident}" name="Object {ident}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm rot="{rotation}"><a:off x="{int(x*12700)}" y="{int(y*12700)}"/><a:ext cx="{int(w*12700)}" cy="{int(h*12700)}"/></a:xfrm></p:spPr>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr{sz}>{family}</a:rPr><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>')

class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.file=self.root/'deck.pptx'
    def tearDown(self):self.temp.cleanup()
    def make(self,shapes):
        deck(self.file,('test',))
        def edit(parts):
            root=pr.xml(parts['ppt/presentation.xml']);sz=root.find('p:sldSz',pr.NS);sz.set('cx',str(720*12700));sz.set('cy',str(405*12700));parts['ppt/presentation.xml']=pr.ET.tostring(root)
            parts['ppt/slides/slide1.xml']=(f'<p:sld xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}"><p:cSld><p:spTree>{shapes}</p:spTree></p:cSld></p:sld>').encode()
        change(self.file,self.root/'new.pptx',edit);self.file.write_bytes((self.root/'new.pptx').read_bytes())
    def rules(self,**kw):return [f['rule'] for f in pl.audit(self.file,**kw)['findings']]
    def test_bounds_and_tolerance(self):
        self.make(shape(1,-0.2,10,100,30));self.assertNotIn('out_of_bounds',self.rules())
        self.make(shape(1,-3,10,100,30));self.assertIn('out_of_bounds',self.rules())
    def test_rotated_bounds(self):
        self.make(shape(1,10,1,200,20,rotation=90*60000));self.assertIn('out_of_bounds',self.rules())
    def test_text_overlap_and_touch(self):
        self.make(shape(1,10,10,100,30)+shape(2,20,20,100,30));self.assertIn('suspicious_overlap',self.rules())
        self.make(shape(1,10,10,100,30)+shape(2,110,10,100,30));self.assertNotIn('suspicious_overlap',self.rules())
    def test_background_and_contained_text_not_overlap(self):
        self.make(shape(1,0,0,720,405,text='')+shape(2,10,10,100,30));self.assertNotIn('suspicious_overlap',self.rules())
    def test_rotated_intersection_not_just_bounding_box(self):
        a=[(0,0),(10,10),(9,11),(-1,1)]
        b=[(0,4),(10,14),(9,15),(-1,5)]
        self.assertEqual(pl.area(pl.intersection(a,b)),0)
    def test_group_coordinate_scaling(self):
        group='<p:grpSp><p:grpSpPr><a:xfrm><a:off x="127000" y="127000"/><a:ext cx="2540000" cy="2540000"/><a:chOff x="0" y="0"/><a:chExt cx="1270000" cy="1270000"/></a:xfrm></p:grpSpPr>'+shape(1,10,10,100,30,size=8)+'</p:grpSp>'
        self.make(group);self.assertNotIn('small_text',self.rules())
        self.assertNotIn('out_of_bounds',self.rules())
    def test_hidden_group_is_skipped(self):
        group='<p:grpSp><p:nvGrpSpPr><p:cNvPr id="99" hidden="1"/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1270000" cy="1270000"/><a:chOff x="0" y="0"/><a:chExt cx="1270000" cy="1270000"/></a:xfrm></p:grpSpPr>'+shape(1,-10,10,100,30,size=8)+'</p:grpSp>'
        self.make(group);r=pl.audit(self.file)
        self.assertFalse(r['findings']);self.assertEqual(r['coverage_gaps']['hidden_objects_skipped'],1)

    def test_later_picture_covering_text_is_suspicious(self):
        pic='<p:pic><p:nvPicPr><p:cNvPr id="2"/></p:nvPicPr><p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="9144000" cy="5143500"/></a:xfrm></p:spPr></p:pic>'
        self.make(shape(1,10,10,100,30)+pic);self.assertIn('suspicious_overlap',self.rules())
        self.make(pic+shape(1,10,10,100,30));self.assertNotIn('suspicious_overlap',self.rules())

    def test_small_font_and_config(self):
        self.make(shape(1,10,10,100,30,size=10))
        self.assertIn('small_text',self.rules());self.assertNotIn('small_text',self.rules(min_font_size=9))
    def test_autofit_scale(self):
        self.make(shape(1,10,10,100,30,size=20).replace('<a:bodyPr/>','<a:bodyPr><a:normAutofit fontScale="50000"/></a:bodyPr>'))
        self.assertIn('small_text',self.rules())
    def test_allowed_and_rare_fonts(self):
        self.make(shape(1,10,10,100,30,text='Main text '*30)+shape(2,10,100,100,30,text='X',font='Odd'))
        r=pl.audit(self.file);self.assertEqual(r['summary']['font_deviation'],1)
        self.assertNotIn('font_deviation',self.rules(allowed_fonts=['Main','Odd']))
        self.assertIn('font_deviation',self.rules(allowed_fonts=['Main']))
    def test_missing_styles_are_coverage_not_clean(self):
        self.make(shape(1,10,10,100,30,size=None,font=None))
        r=pl.audit(self.file);self.assertEqual(r['coverage_gaps']['runs_without_font'],1);self.assertEqual(r['coverage_gaps']['runs_without_size'],1)
    def test_inherited_placeholder_geometry_and_theme(self):
        s=shape(1,10,10,100,30,size=None,font=None)
        root=pr.xml(s.replace('<p:sp>',f'<p:sp xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}">').encode())
        root.find('p:spPr',pr.NS).clear();nv=root.find('p:nvSpPr/p:nvPr',pr.NS);pr.ET.SubElement(nv,'{'+P+'}ph',{'idx':'7'})
        self.make(pr.ET.tostring(root).decode())
        def add(parts):
            parts['ppt/slides/_rels/slide1.xml.rels']=rels([('layout','slideLayout','../slideLayouts/layout.xml')])
            lay=shape(5,-5,10,100,30,size=None,font=None).replace('<p:nvPr/>','<p:nvPr><p:ph idx="7" type="title"/></p:nvPr>')
            parts['ppt/slideLayouts/layout.xml']=(f'<p:sldLayout xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree>{lay}</p:spTree></p:cSld></p:sldLayout>').encode()
            parts['ppt/slideLayouts/_rels/layout.xml.rels']=rels([('master','slideMaster','../slideMasters/master.xml')])
            parts['ppt/slideMasters/master.xml']=(f'<p:sldMaster xmlns:p="{P}" xmlns:a="{A}"><p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="900"><a:latin typeface="+mj-lt"/></a:defRPr></a:lvl1pPr></p:titleStyle></p:txStyles></p:sldMaster>').encode()
            parts['ppt/slideMasters/_rels/master.xml.rels']=rels([('theme','theme','../theme/theme1.xml')])
            parts['ppt/theme/theme1.xml']=(f'<a:theme xmlns:a="{A}"><a:themeElements><a:fontScheme><a:majorFont><a:latin typeface="Theme Font"/></a:majorFont></a:fontScheme></a:themeElements></a:theme>').encode()
        change(self.file,self.root/'new.pptx',add);self.file.write_bytes((self.root/'new.pptx').read_bytes())
        r=pl.audit(self.file,allowed_fonts=['Theme Font']);self.assertIn('out_of_bounds',r['summary']);self.assertIn('small_text',r['summary']);self.assertNotIn('font_deviation',r['summary']);self.assertFalse(r['coverage_gaps'])
        def fit(parts):
            k='ppt/slideLayouts/layout.xml'
            parts[k]=parts[k].replace(b'<a:bodyPr/>',b'<a:bodyPr><a:normAutofit fontScale="50000"/></a:bodyPr>')
            k='ppt/slides/slide1.xml';root=pr.xml(parts[k]);node=root.find('.//a:rPr',pr.NS);node.set('sz','2000');parts[k]=pr.ET.tostring(root)
        change(self.file,self.root/'new.pptx',fit);self.file.write_bytes((self.root/'new.pptx').read_bytes())
        r=pl.audit(self.file);f=next(f for f in r['findings'] if f['rule']=='small_text');self.assertEqual(f['details']['minimum_pt'],10)

    def test_version_bound_and_no_overwrite(self):
        self.make(shape(1,10,10,100,30));out=self.root/'audit.json'
        script=Path(pr.__file__);run=lambda *args:subprocess.run([sys.executable,str(script),*map(str,args)],capture_output=True,text=True)
        self.assertEqual(run('audit',self.file,'--out',out).returncode,0)
        self.assertEqual(run('audit',self.file,'--out',out).returncode,1)
        self.assertEqual(run('audit-status',out).returncode,0)
        self.file.write_bytes(self.file.read_bytes()+b'changed')
        self.assertEqual(run('audit-status',out).returncode,2)
    def test_compare_includes_audit_and_hashes_it(self):
        self.make(shape(1,-4,10,100,30,size=8));out=self.root/'bundle'
        pr.create_bundle(self.file,self.file,out)
        r=json.loads((out/'comparison.json').read_text());self.assertIn('out_of_bounds',r['format_audit']['summary']);self.assertTrue(pr.bundle_state(out)[3]['current'])
        r['format_audit']['findings']=[];(out/'comparison.json').write_text(json.dumps(r))
        self.assertFalse(pr.bundle_state(out)[3]['current'])
    @unittest.skipUnless(os.environ.get('PPTX_REVIEW_FIXTURE'),'set PPTX_REVIEW_FIXTURE to a real presentation')
    def test_real_file_injected_format_defects(self):
        source=Path(os.environ['PPTX_REVIEW_FIXTURE']);original=pr.file_hash(source)
        def edit(parts):
            name=pr.snapshot(source)['slides'][0]['part'];root=pr.xml(parts[name]);tree=root.find('p:cSld/p:spTree',pr.NS)
            node=next((s for s in tree if s.tag.endswith('}sp') and s.find('.//a:t',pr.NS) is not None and s.find('p:spPr/a:xfrm/a:off',pr.NS) is not None),None)
            if node is None:self.skipTest('Fixture first slide has no suitable top-level text shape')
            node.find('p:spPr/a:xfrm/a:off',pr.NS).set('x',str(-10*12700))
            for prop in node.findall('.//a:rPr',pr.NS)+node.findall('.//a:defRPr',pr.NS):
                prop.set('sz','600');latin=prop.find('a:latin',pr.NS)
                if latin is None:latin=pr.ET.SubElement(prop,'{'+A+'}latin')
                latin.set('typeface','Injected Test Font')
            duplicate=copy.deepcopy(node);duplicate.find('.//p:cNvPr',pr.NS).set('id','99999');tree.append(duplicate)
            parts[name]=pr.ET.tostring(root)
        change(source,self.file,edit)
        rules=set(self.rules(allowed_fonts=['Main']))
        self.assertTrue({'out_of_bounds','small_text','suspicious_overlap','font_deviation'}<=rules)
        self.assertEqual(pr.file_hash(source),original)

    def test_invalid_thresholds(self):
        self.make(shape(1,0,0,10,10))
        for value in [0,-1,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):pl.audit(self.file,min_font_size=value)

if __name__=='__main__':unittest.main()
