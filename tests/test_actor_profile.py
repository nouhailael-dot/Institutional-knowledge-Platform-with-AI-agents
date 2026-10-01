"""Offline V2 actor contract and geography checks."""
import unittest
from src.map_agent.actor_profile import CATEGORIES, REGIONS, normalize_actor_profile, region_for
from src.map_agent.entity_schemas import submit_entities_tool
from src.map_agent.export import _field_value
from src.map_agent.dedup import deduplicate

URL='https://example.edu/project'
class ActorProfileTests(unittest.TestCase):
    def test_category_schema_and_manual_fields(self):
        props=submit_entities_tool('actor')['input_schema']['properties']['entities']['items']['properties']
        self.assertEqual(props['actor_type']['enum'],CATEGORIES)
        self.assertEqual(len(CATEGORIES),12)
        for field in ('record_status','ghus_notes','verification_history','region'):
            self.assertNotIn(field,props)

    def test_retained_fields_and_relationship_sources(self):
        actor={'name':'Example','actor_type':CATEGORIES[0], 'country':'US','state':'VA',
               'sector':'Water','multi_location':True,
               'category_details':[{'label':'Program','value':'Water research'}],
               'actor_relationships':[{'organization_name':'Parent','relationship':'unit of','source_url':URL},
                   {'organization_name':'Invented','relationship':'unit of','source_url':'https://invented.example'}]}
        normalize_actor_profile(actor,{URL:{'kind':'page'}})
        self.assertEqual(actor['sector'],'Water')
        self.assertEqual(actor['region'],'Mid-Atlantic')
        self.assertTrue(actor['multi_location'])
        self.assertEqual(len(actor['category_details']),1)
        self.assertEqual(len(actor['actor_relationships']),1)
        for field in ('field_evidence','record_status','hub_status','um6p_ocp_status'):
            self.assertNotIn(field,actor)

    def test_seven_regions_cover_every_state_once(self):
        states=[s for codes in REGIONS.values() for s in codes.split()]
        self.assertEqual(len(states),51)
        self.assertEqual(len(set(states)),51)
        for region,codes in REGIONS.items():
            for state in codes.split(): self.assertEqual(region_for('US',state),region)
        self.assertEqual(region_for('USA','New Jersey'),'Mid-Atlantic')
        self.assertEqual(region_for('US','Arizona'),'Mountain West / Rocky Mountain')
        self.assertEqual(region_for('Canada','TX'),'')
        self.assertEqual(region_for('US','NY / NJ'),'')

    def test_new_profile_exports_without_losing_fields(self):
        import io
        from openpyxl import load_workbook
        from pptx import Presentation
        from src.map_agent.export import to_xlsx, to_pptx
        actor={'name':'Example University','actor_type':CATEGORIES[0], '_selected':True,
               'region':'Mid-Atlantic',
               'category_details':[{'label':'Program','value':'Agricultural research ' * 100}],
               'field_evidence':[{'field':'description','value':'Evidence '*200,'source_url':URL,
                   'confidence':'medium','origin':'newly found','date_read':'2026-09-29'}]}
        result={'entities':{'actor':[actor]}}
        workbook=load_workbook(io.BytesIO(to_xlsx(result)))
        cells=[str(c.value) for sheet in workbook for row in sheet for c in row]
        self.assertTrue(any('Agricultural research' in c for c in cells))
        deck=Presentation(io.BytesIO(to_pptx(result)))
        text=' '.join(s.text for slide in deck.slides for s in slide.shapes if s.has_text_frame)
        self.assertIn('Agricultural research',text)
        self.assertIn('Mid-Atlantic',text)
        self.assertGreater(len(deck.slides),2)
