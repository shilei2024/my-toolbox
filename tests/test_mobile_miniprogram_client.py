import shutil
import subprocess
import unittest
from pathlib import Path


class MiniProgramClientTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required for native client logic checks')
    def test_login_retry_privacy_and_intent_use_actual_client_code(self):
        root = Path(__file__).parents[1]
        source = r"""
const assert=require('node:assert/strict');
const storage=new Map();let requests=[],uploads=[],uploadFails=true;
const token='a'.repeat(43);
global.wx={getStorageSync:k=>storage.get(k),setStorageSync:(k,v)=>storage.set(k,v),removeStorageSync:k=>storage.delete(k),
 login:opt=>opt.success({code:'temporary-wechat-code'}),
 request:opt=>{requests.push(opt);opt.success(opt.url.endsWith('/session')?{statusCode:200,data:{access_token:token,expires_at:'2099-01-01T00:00:00Z'}}:{statusCode:200,data:{ok:true}});},
 uploadFile:opt=>{uploads.push(opt);queueMicrotask(()=>uploadFails?opt.fail({errMsg:'private-native-message'}):opt.success({statusCode:200,data:JSON.stringify({success:true,duplicate:true})}));return{onProgressUpdate:fn=>fn({progress:50})};},
 requirePrivacyAuthorize:opt=>opt.fail({errMsg:'private-native-message'})};
const api=require('./apps/invoice-miniprogram/lib/api');
(async()=>{
 await api.login('b'.repeat(32));
 assert.equal(requests[0].data.code,'temporary-wechat-code');
 assert(!requests[0].header.Authorization);
 assert(!JSON.stringify([...storage.values()]).includes('binding_code'));
 await api.request('/api/mobile/bootstrap');
 assert.equal(requests[1].header.Authorization,'Bearer '+token);
 assert(!requests[1].header.Cookie);
 assert(!requests[1].url.includes(token));
 const item={path:'wxfile://tmp/no-extension',name:'收据.pdf',key:'same-retry-key-0001',intent:{period_id:'1',office_id:'2',document_kind:'toll',occurrence_month:'2026-06'}};
 await assert.rejects(api.upload(item,()=>{}),e=>e.message.includes('重试')&&!e.message.includes('private'));
 uploadFails=false;await api.upload(item,()=>{});
 assert.equal(uploads[0].formData.idempotency_key,uploads[1].formData.idempotency_key);
 assert.equal(uploads[1].formData.file_name,'收据.pdf');
 assert(!uploads[1].header.Cookie);
 await assert.rejects(api.privacy(),e=>e.message.includes('隐私'));
 wx.request=opt=>opt.success({statusCode:401,data:{error:'登录失效'}});
 await assert.rejects(api.request('/api/mobile/bootstrap'));
 assert.equal(api.session(),null);
 await assert.rejects(api.upload(item,()=>{}));assert.equal(uploads.length,2);
 wx.setStorageSync('invoice_session_v1',{access_token:token,expires_at:'2099-01-01T00:00:00Z'});
 let page;global.Page=definition=>{page=definition};
 require('./apps/invoice-miniprogram/pages/home/index');
 page.data=JSON.parse(JSON.stringify(page.data));page.data.periods=[{id:1,name:'六月七月'}];page.data.offices=[{id:2,name:'测试办'}];page.data.month='2026-06';page.data.kindIndex=2;
 page.setData=updates=>{for(const [key,value] of Object.entries(updates)){const parts=key.replace(/\[(\d+)\]/g,'.$1').split('.');let target=page.data;for(const field of parts.slice(0,-1))target=target[field]??(target[field]={});target[parts.at(-1)]=value;}};
 let runs=0;page.runQueue=()=>{runs++};page.enqueue([{path:'file.pdf',name:'票据.pdf',size:100}]);
 assert.equal(runs,1);const savedKey=page.data.queue[0].key;
 page.data.month='2026-07';page.data.kindIndex=1;
 assert.equal(page.data.queue[0].intent.occurrence_month,'2026-06');assert.equal(page.data.queue[0].intent.document_kind,'fuel');
 page.data.queue[0].state='failed';page.retry({currentTarget:{dataset:{index:0}}});
 assert.equal(page.data.queue[0].key,savedKey);assert.equal(runs,2);
 page.data.busy=true;await page.logout();assert(api.session());
 page.data.busy=false;wx.requirePrivacyAuthorize=opt=>opt.success();
 wx.chooseMedia=opt=>opt.success({tempFiles:[{tempFilePath:'wxfile://tmp/no-extension',size:100}]});
 wx.getImageInfo=opt=>opt.success({type:'jpeg'});
 await page.chooseImage();assert(page.data.queue.at(-1).name.endsWith('.jpg'));
 assert.equal(page.data.queue.at(-1).path,'wxfile://tmp/no-extension');
 console.log('native login, retry, immutable upload intent, privacy and scope checks passed');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        result = subprocess.run([shutil.which('node'), '-e', source], cwd=root,
            capture_output=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
