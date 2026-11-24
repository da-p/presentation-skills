import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'skills/presentation-craft/scripts'))
import pptx_review as pr

P=pr.NS['p']; A=pr.NS['a']; R=pr.NS['r']

def rels(rows):
    return ('<Relationships xmlns="'+pr.REL+'">'+''.join('<Relationship Id="'+i+'" Type="'+R+'/'+k+'" Target="'+t+'"/>' for i,k,t in rows)+'</Relationships>').encode()

def deck(path, titles=('Выручка 100 млн', 'План работ'), order=None):
    order = order or list(range(1,len(titles)+1))
    parts={'ppt/presentation.xml': ('<p:presentation xmlns:p="'+P+'" xmlns:r="'+R+'"><p:sldIdLst>'+''.join('<p:sldId id="'+str(255+i)+'" r:id="r'+str(i)+'"/>' for i in order)+'</p:sldIdLst><p:sldSz cx="100" cy="56"/></p:presentation>').encode(),
           'ppt/_rels/presentation.xml.rels':rels([('r'+str(i),'slide','slides/slide'+str(i)+'.xml') for i in range(1,len(titles)+1)])}
    for i,t in enumerate(titles,1):
        parts['ppt/slides/slide'+str(i)+'.xml']=('<p:sld xmlns:p="'+P+'" xmlns:a="'+A+'" xmlns:r="'+R+'"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>'+t+'</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>').encode()
    pack(path,parts)

def pack(path,parts):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for n,b in parts.items():z.writestr(n,b)

def change(src,dest,fn):
    with zipfile.ZipFile(src) as z:parts={n:z.read(n) for n in z.namelist()}
    fn(parts);pack(dest,parts)

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.a=self.root/'a.pptx';self.b=self.root/'b.pptx'
        deck(self.a);deck(self.b)
    def tearDown(self):self.tmp.cleanup()
    def compare(self):return pr.compare(pr.snapshot(self.a),pr.snapshot(self.b))
    def test_internal_slide_link_does_not_import_target_contents(self):
        def add_link(parts):
            parts['ppt/slides/_rels/slide1.xml.rels'] = rels([('next', 'slide', 'slide2.xml')])
        change(self.a, self.b, add_link)
        self.a.write_bytes(self.b.read_bytes())
        def edit_target(parts):
            key = 'ppt/slides/slide2.xml'
            parts[key] = parts[key].replace('План работ'.encode(), 'Сроки'.encode())
        change(self.a, self.b, edit_target)
        rows = {row['after']: row for row in self.compare()['rows']}
        self.assertFalse(rows[1]['changes'])
        self.assertIn('text', rows[2]['changes'])

    def test_identical_and_reorder(self):
        self.assertEqual(self.compare()['summary']['changed_pairs'],0)
        deck(self.b,order=[2,1])
        result=self.compare()
        self.assertEqual(result['summary']['moved_pairs'],2)
        self.assertEqual(result['summary']['changed_pairs'],0)
    def test_change_numbers_and_candidate_not_certainty(self):
        deck(self.b,('Выручка 120 млн','План работ'))
        row=next(r for r in self.compare()['rows'] if r['after']==1)
        self.assertEqual(row['changes']['numbers'],{'removed':['100'],'added':['120']})
        self.assertEqual(row['match'],'internal-id-candidate')
    def test_deletion_and_addition(self):
        deck(self.b,('Выручка 100 млн',))
        self.assertEqual(self.compare()['summary']['unmatched_before'],1)
        deck(self.b,('Выручка 100 млн','План работ','Новый слайд'))
        self.assertEqual(self.compare()['summary']['unmatched_after'],1)
    def test_duplicate_content_not_unique_match(self):
        deck(self.a,('Повтор','Повтор'));deck(self.b,('Повтор','Повтор'))
        self.assertEqual(self.compare()['summary']['candidate_pairs'],2)
    def test_whitespace_and_split_runs(self):
        def edit(parts):
            key='ppt/slides/slide1.xml'
            parts[key]=parts[key].replace('Выручка 100 млн'.encode(), 'Выручка\u00a0100 млн'.encode())
        change(self.a,self.b,edit)
        row=self.compare()['rows'][0]
        self.assertTrue(row['changes']['text']['normalized_equal'])
        self.assertNotIn('numbers',row['changes'])
    def test_image_replacement_and_unused_relation(self):
        def add(parts):
            k='ppt/slides/slide1.xml'
            parts[k]=parts[k].replace(b'</p:spTree>', b'<p:pic><a:blip r:embed="img"/></p:pic></p:spTree>')
            parts['ppt/slides/_rels/slide1.xml.rels']=rels([('img','image','../media/a.png'),('unused','image','../media/unused.png')])
            parts['ppt/media/a.png']=b'first';parts['ppt/media/unused.png']=b'unused'
        change(self.a,self.b,add)
        self.a.write_bytes(self.b.read_bytes())
        change(self.a,self.b,lambda p:p.update({'ppt/media/a.png':b'second'}))
        row=self.compare()['rows'][0]
        self.assertEqual(len(row['changes']['images']['removed']),1)
        self.assertEqual(len(pr.snapshot(self.a)['slides'][0]['images']),1)
    def test_same_image_used_twice_counts_instances(self):
        def add(parts):
            k='ppt/slides/slide1.xml'
            pic=b'<p:pic><a:blip r:embed="img"/></p:pic>'
            parts[k]=parts[k].replace(b'</p:spTree>',pic+pic+b'</p:spTree>')
            parts['ppt/slides/_rels/slide1.xml.rels']=rels([('img','image','../media/a.png')])
            parts['ppt/media/a.png']=b'image'
        change(self.a,self.b,add);self.a.write_bytes(self.b.read_bytes())
        def remove(parts):
            k='ppt/slides/slide1.xml'
            parts[k]=parts[k].replace(b'<p:pic><a:blip r:embed="img"/></p:pic>',b'',1)
        change(self.a,self.b,remove)
        self.assertEqual(len(pr.snapshot(self.a)['slides'][0]['images']),2)
        self.assertEqual(len(self.compare()['rows'][0]['changes']['images']['removed']),1)

    def test_changed_relationship_is_not_invisible(self):
        def add(parts):
            k='ppt/slides/slide1.xml'
            parts[k]=parts[k].replace(b'</p:spTree>',b'<p:pic><a:blip r:embed="img1"/></p:pic><p:pic><a:blip r:embed="img2"/></p:pic></p:spTree>')
            parts['ppt/slides/_rels/slide1.xml.rels']=rels([('img1','image','../media/a.png'),('img2','image','../media/b.png')])
            parts['ppt/media/a.png']=b'first';parts['ppt/media/b.png']=b'second'
        change(self.a,self.b,add);self.a.write_bytes(self.b.read_bytes())
        def swap(parts):
            parts['ppt/slides/_rels/slide1.xml.rels']=rels([('img1','image','../media/b.png'),('img2','image','../media/a.png')])
        change(self.a,self.b,swap)
        self.assertIn('ppt/slides/_rels/slide1.xml.rels',self.compare()['rows'][0]['changes']['package_parts'])

    def test_chart_and_embedded_data_change(self):
        def add(parts):
            k='ppt/slides/slide1.xml'
            parts[k]=parts[k].replace(b'</p:spTree>', b'<p:graphicFrame><a:graphic r:id="chart"/></p:graphicFrame></p:spTree>')
            parts['ppt/slides/_rels/slide1.xml.rels']=rels([('chart','chart','../charts/chart1.xml')])
            parts['ppt/charts/chart1.xml']=b'<chart xmlns="urn:chart"><v>50</v></chart>'
            parts['ppt/charts/_rels/chart1.xml.rels']=rels([('data','package','../embeddings/data.xlsx')])
            parts['ppt/embeddings/data.xlsx']=b'original'
        change(self.a,self.b,add);self.a.write_bytes(self.b.read_bytes())
        change(self.a,self.b,lambda p:p.update({'ppt/embeddings/data.xlsx':b'changed'}))
        self.assertIn('ppt/embeddings/data.xlsx',self.compare()['rows'][0]['changes']['package_parts'])
    def test_boolean_false_is_hidden(self):
        change(self.a,self.b,lambda p:p.update({'ppt/slides/slide1.xml':p['ppt/slides/slide1.xml'].replace(b'<p:sld ',b'<p:sld show="false" ')}))
        self.assertTrue(pr.snapshot(self.b)['slides'][0]['hidden'])

    def test_reordered_paragraphs_report_order(self):
        def add(parts):
            key='ppt/slides/slide1.xml'
            parts[key]=parts[key].replace(b'</p:txBody>',b'<a:p><a:r><a:t>Second</a:t></a:r></a:p></p:txBody>')
        change(self.a,self.b,add);self.a.write_bytes(self.b.read_bytes())
        def swap(parts):
            key='ppt/slides/slide1.xml';root=pr.xml(parts[key]);body=root.find('.//p:txBody',pr.NS)
            first=body[0];body.remove(first);body.append(first);parts[key]=pr.ET.tostring(root)
        change(self.a,self.b,swap)
        self.assertTrue(self.compare()['rows'][0]['changes']['text']['order_changed'])

    def test_hidden_and_malformed(self):
        change(self.a,self.b,lambda p:p.update({'ppt/slides/slide1.xml':p['ppt/slides/slide1.xml'].replace(b'<p:sld ',b'<p:sld show="0" ')}))
        self.assertTrue(pr.snapshot(self.b)['slides'][0]['hidden'])
        with self.assertRaises(ValueError):pr.render(pr.snapshot(self.b),self.root/'images','unused','unused','unused')
        self.b.write_bytes(b'bad')
        with self.assertRaises(zipfile.BadZipFile):pr.snapshot(self.b)
    def test_checks_become_stale_after_any_source_change(self):
        bundle=self.root/'review';pr.create_bundle(self.a,self.b,bundle)
        pr.record_check(bundle,'revenue',1,'content','resolved','На слайде 1 выручка 100 млн')
        self.assertTrue(pr.bundle_state(bundle)[3]['checks'][0]['current'])
        deck(self.b,('Выручка 200 млн','План работ'))
        self.assertFalse(pr.bundle_state(bundle)[3]['checks'][0]['current'])
        with self.assertRaises(ValueError):pr.record_check(bundle,'x',1,'content','resolved','test')
    def test_visual_requires_render_and_artifact_tamper_stales(self):
        bundle=self.root/'review';pr.create_bundle(self.a,self.b,bundle)
        with self.assertRaises(ValueError):pr.record_check(bundle,'x',1,'visual','resolved','test')
        (bundle/'index.html').write_text('changed')
        self.assertFalse(pr.bundle_state(bundle)[3]['current'])
    def test_output_not_overwritten_and_no_source_mutations(self):
        before=pr.file_hash(self.a);bundle=self.root/'review'
        pr.create_bundle(self.a,self.b,bundle)
        with self.assertRaises(ValueError):pr.create_bundle(self.a,self.b,bundle)
        self.assertEqual(before,pr.file_hash(self.a))
    def test_external_not_fetched_and_html_escaped(self):
        deck(self.b,('Текст &lt;script&gt;опасный&lt;/script&gt;',))
        bundle=self.root/'review';pr.create_bundle(self.a,self.b,bundle)
        self.assertNotIn('<script>',(bundle/'index.html').read_text())
    def test_render_failure_has_no_partial_bundle(self):
        bundle=self.root/'review'
        with patch.object(pr,'render',side_effect=ValueError('failure')):
            with self.assertRaises(ValueError):pr.create_bundle(self.a,self.b,bundle,True)
        self.assertFalse(bundle.exists())
    @unittest.skipUnless(os.environ.get('PPTX_REVIEW_FIXTURE'),'set PPTX_REVIEW_FIXTURE to a real presentation')
    def test_real_file_controlled_change(self):
        source=Path(os.environ['PPTX_REVIEW_FIXTURE']);before=pr.file_hash(source)
        snap=pr.snapshot(source);part=snap['slides'][0]['part']
        def edit(parts):
            root=pr.xml(parts[part]);node=root.find('.//a:t',pr.NS)
            node.text='Проверка изменения 987654'
            parts[part]=pr.ET.tostring(root,encoding='utf-8',xml_declaration=True)
        change(source,self.b,edit)
        diff=pr.compare(snap,pr.snapshot(self.b))
        row=next(r for r in diff['rows'] if r['before']==1)
        self.assertIn('987654',row['changes']['numbers']['added'])
        self.assertEqual(pr.file_hash(source),before)

if __name__=='__main__':unittest.main()
