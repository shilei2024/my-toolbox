import hashlib
import importlib.util
import io
from pathlib import Path
import unittest
from alembic.migration import MigrationContext
from alembic.operations import Operations


class MobileRehearsalContractTests(unittest.TestCase):
    def test_actual_ddl_matches_and_database_guard_precedes_all_writes(self):
        root=Path(__file__).parents[1]
        path=root/'migrations/versions/f5a6b7c8d9e0_mobile_invoice_upload.py'
        source=(root/'scripts/ops/mobile_invoice_rehearsal.sql').read_text(encoding='utf-8')
        spec=importlib.util.spec_from_file_location('mobile_rehearsal_revision',path)
        revision=importlib.util.module_from_spec(spec);spec.loader.exec_module(revision)
        self.assertIn(hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest(),source)
        for action,count in [('upgrade',2),('downgrade',1)]:
            output=io.StringIO()
            revision.op=Operations(MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':output}))
            getattr(revision,action)()
            actual='\n'.join(line.rstrip() for line in output.getvalue().strip().splitlines())
            self.assertEqual(source.count(actual),count)
        self.assertLess(source.index("current_database() <> 'mytoolbox_invoice_verify_20261028_111850'"),source.index('CREATE TEMP TABLE'))
        self.assertIn("IS DISTINCT FROM 'e4f5a6b7c8d9'",source)
        self.assertIn('Historical invoice amounts or retention metadata changed',source)
        self.assertIn('Historical original BLOBs changed',source)
        self.assertIn('Historical users changed',source)
        self.assertIn('MOBILE_MIGRATION_REHEARSAL_OK',source)
        self.assertNotIn('DROP DATABASE',source)
