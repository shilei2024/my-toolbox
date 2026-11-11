import shutil
import subprocess
import unittest
from pathlib import Path


class InvoiceCustomerClientTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required for client checks')
    def test_both_clients_select_new_customer_preserve_failures_and_prevent_double_submit(self):
        source = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
let page; global.Page = value => {page = value};
require('./apps/invoice-miniprogram/pages/review/index');
page.data = structuredClone(page.data);
page.setData = update => {for(const [key,value] of Object.entries(update)) {
  const parts=key.split('.');let target=page.data;
  for(const part of parts.slice(0,-1)) target=target[part];
  target[parts.at(-1)]=value;
}};
page.indices=()=>{};page.syncLinked=()=>{};
const api=require('./apps/invoice-miniprogram/lib/api');
(async()=>{
 page.openCustomer();assert.equal(page.data.newCustomer,null);
 page.data.customer_creation_enabled=true;page.data.invoice={};page.openCustomer();
 let count=0,resolve;api.request=()=>{count++;return new Promise(r=>{resolve=r})};
 await page.createCustomer();assert.equal(count,0);assert(page.data.newCustomer);
 page.data.newCustomer={name:'客户',short_name:'简称',grade:'AA'};
 const pending=page.createCustomer();await page.createCustomer();assert.equal(count,1);
 resolve({customer:{id:'personal',display_name:'简称',grade:'AA'}});await pending;
 assert.equal(page.data.invoice.customer_id,'personal');assert.equal(page.data.invoice.customer_level,'AA');
 assert.equal(page.data.busy,false);assert.equal(page.data.newCustomer,null);
 page.openCustomer();page.data.newCustomer.name='重试';api.request=async()=>{throw Error('稍后重试')};
 await page.createCustomer();assert.equal(page.data.newCustomer.name,'重试');assert.equal(page.data.busy,false);
 const html=fs.readFileSync('templates/tools/reimbursement/_body.html','utf8');
 const method=html.match(/  async saveCustomer\(\)\{[\s\S]*?\n  \},/)[0];
 const controls={rbNewCustomerName:{value:'客户'},rbNewCustomerShortName:{value:'简称'},rbNewCustomerGrade:{value:'AA'},rbSaveCustomerButton:{disabled:false}};
 global.document={getElementById:id=>controls[id]};
 const web=eval('({'+method+'})');web.state={customers:[]};web.toast=()=>{};web.syncCustomer=()=>{};
 web.closeCustomerEntry=()=>{};let selected;web.renderCustomerSelector=id=>{selected=id};
 count=0;web.api=()=>{count++;return new Promise(r=>{resolve=r})};
 const saving=web.saveCustomer();await web.saveCustomer();assert.equal(count,1);assert(controls.rbSaveCustomerButton.disabled);
 resolve({customer:{id:'web-personal',display_name:'简称',grade:'AA'}});await saving;
 assert.equal(selected,'web-personal');assert.equal(web.state.customerSaving,false);assert.equal(controls.rbSaveCustomerButton.disabled,false);
 web.api=async()=>{throw Error('重试')};await web.saveCustomer();assert.equal(web.state.customerSaving,false);assert.equal(controls.rbNewCustomerName.value,'客户');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
        result = subprocess.run([shutil.which('node'), '-e', source], cwd=Path(__file__).parents[1],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
