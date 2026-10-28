"""Run the actual printer script with a small DOM adapter, without OCR/network."""
import shutil
import subprocess
import unittest
from pathlib import Path


class PrinterRetentionJsTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is needed for printer logic verification")
    def test_unknown_threshold_noninvoice_and_original_archive(self):
        root = Path(__file__).parents[1]
        script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('templates/tools/invoice_printer/_body.html','utf8');
const js = source.match(/<script>([\s\S]*)<\/script>/)[1].replace(/{{[^}]+}}/g,'{}');
const elements = new Map();
const document = {addEventListener(){}, querySelector(){return null},
 getElementById(id){if(!elements.has(id))elements.set(id,{value:'5',disabled:false,classList:{add(){},remove(){}},click(){}});return elements.get(id)},
 createElement(){return {click(){}}}};
const context = {document, console, setTimeout(){}, clearTimeout(){}, URL:{createObjectURL(){return 'blob:test'},revokeObjectURL(){}},
 fetch: async()=>({blob:async()=>Buffer.from('fixture')}), Buffer, assert, captured:[]};
vm.createContext(context);
vm.runInContext(js,context);
vm.runInContext(`
renderResult=()=>{};showToast=()=>{};
STATE.files=[{name:'a.pdf',confirmedAmount:'4.99'}, {name:'b.pdf',confirmedAmount:'5.00'},
 {name:'unknown.pdf'}, {name:'apply.pdf',source:'original.zip',confirmedAmount:'20.4'},
 {name:'c.pdf',confirmedAmount:'20.4'}];
filterAmounts();
assert.equal(STATE.files.map(f=>f._selected).join(','),'false,true,false,false,true');
assert.equal(STATE.files.length,5);
STATE.originals=[{name:'original.zip',file:'original bytes'}];
for(const f of STATE.files)f.blobUrl='blob:fixture';
ensureJSZip=async()=>{};
JSZip=class { file(name,bytes){captured.push(name);return this} async generateAsync(){return 'archive'} };
`,context);
(async()=>{await vm.runInContext('archiveAll()',context);
assert.equal(context.captured.filter(x=>x.startsWith('提取结果/')).length,5);
assert(context.captured.includes('原始压缩包/1_original.zip'));
assert(context.captured.includes('清单.json'));
console.log('printer amount and original archive checks passed');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        result = subprocess.run([shutil.which("node"), "-e", script], cwd=root,
            capture_output=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
