import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/presentation-craft/scripts'))
import slide_craft as c

class CompositionTests(unittest.TestCase):
    def test_layout_scales_normalized_geometry(self):
        x=c.layout({'regions':[{'id':'figure','box':[.1,.2,.5,.3],'note':'Actual measured object'}]},1280,720)
        self.assertEqual(x['regions'][0]['position'],{'left':128.,'top':144.,'width':640.,'height':216.})
    def test_invalid_geometry_cannot_become_layout(self):
        for box in [[0,0,2,1],[0,0,0,1],[0,0,float('nan'),1],[-.1,0,.1,1]]:
            with self.assertRaises(ValueError):c.layout({'regions':[{'id':'x','box':box}]},1280,720)
    def test_duplicate_region_ids_rejected(self):
        with self.assertRaises(ValueError):c.regions({'regions':[{'id':'x','box':[0,0,.1,.1]}]*2})
    def test_existing_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'review.html';p.write_text('keep')
            with self.assertRaises(FileExistsError):c.write_new(p,'replace')
            self.assertEqual(p.read_text(),'keep')
    def test_comparison_is_self_contained_and_inputs_unchanged(self):
        try:from PIL import Image
        except ImportError:self.skipTest('Run with bundled Python (Pillow)')
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'a.png';b=Path(d)/'b.png';Image.new('RGB',(120,80),'red').save(a);Image.new('RGB',(100,80),'blue').save(b)
            before=[a.read_bytes(),b.read_bytes()]
            page=c.comparison(a,b,{'regions':[{'id':'<script>bad</script>','box':[.1,.1,.5,.5]}]})
            self.assertEqual(page.count('data:image/png;base64,'), 2)
            self.assertEqual(page.count('<use href="#reference"/>'), 2)
            self.assertIn('Пропорции изображений различаются',page)
            self.assertNotIn('<script>bad</script>',page)
            self.assertIn('viewBox="12.0 8.0 60.0 40.0"',page)
            self.assertEqual([a.read_bytes(),b.read_bytes()],before)
    def test_type_measurement_preserves_requested_size(self):
        try:from PIL import ImageFont
        except ImportError:self.skipTest('Run with bundled Python (Pillow)')
        font=Path('/System/Library/Fonts/Supplemental/Arial.ttf')
        if not font.exists():self.skipTest('No fixture font on this host')
        x=c.measure_type(font,'Длинный заголовок',48)
        self.assertEqual(x['size_px'],48);self.assertGreater(x['lines'][0]['advance_px'],100)
        self.assertEqual(x['lines'][0]['ink_bbox'],list(ImageFont.truetype(str(font),48).getbbox('Длинный заголовок')))

if __name__=='__main__':unittest.main()
