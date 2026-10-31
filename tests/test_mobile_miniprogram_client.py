import shutil
import subprocess
import unittest
from pathlib import Path


class MiniProgramClientTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required for native client logic checks')
    def test_native_tabs_share_period_and_protect_drafts_and_account_changes(self):
        root = Path(__file__).parents[1]
        source = r"""
const assert=require('node:assert/strict');
const app={globalData:{}};global.getApp=()=>app;
const config=require('./apps/invoice-miniprogram/app.json');
assert.deepEqual(config.tabBar.list.map(t=>t.text),['首页','发票录入','派车单','我的']);
assert(config.tabBar.list.every(t=>config.pages.includes(t.pagePath)));
const context=require('./apps/invoice-miniprogram/lib/context');
const api=require('./apps/invoice-miniprogram/lib/api');
let token='a'.repeat(43),modal=true,switched='';const storage=new Map();
function login(){storage.set('invoice_session_v1',{access_token:token,expires_at:'2099-01-01T00:00:00Z'});}
global.wx={getStorageSync:k=>storage.get(k),setStorageSync:(k,v)=>storage.set(k,v),removeStorageSync:k=>storage.delete(k),
 showModal:o=>o.success({confirm:modal}),switchTab:o=>{switched=o.url;},request:o=>o.success({statusCode:200,data:{success:true}})};
login();const periods=[{id:1,name:'one'},{id:2,name:'two',is_active:true}];
assert.equal(context.choose(periods),1);context.state().periodId=1;assert.equal(context.choose(periods),0);
assert.equal(context.choose([{id:9}]),0);assert.equal(context.state().periodId,9);
function page(path){let p;global.Page=d=>{p=d;};require('./apps/invoice-miniprogram/pages/'+path+'/index');p.data=structuredClone(p.data);p.setData=u=>{for(const [key,value] of Object.entries(u)){const parts=key.split('.');let target=p.data;for(const part of parts.slice(0,-1))target=target[part];target[parts.at(-1)]=value;}};return p;}
(async()=>{
 const dashboard=page('dashboard');dashboard.data.periods=periods;dashboard.data.periodIndex=0;context.state().periodId=1;
 let queried='';api.request=async path=>{queried=path;return {total_amount:'10.25'};};
 context.state().dispatchDirty=true;await dashboard.period({detail:{value:1}});assert.equal(context.state().periodId,1);
 context.state().dispatchDirty=false;await dashboard.period({detail:{value:1}});assert.equal(context.state().periodId,2);assert.equal(queried,'/api/mobile/dashboard/2');
 const dispatch=page('dispatch');dispatch.data.periodId=2;dispatch.data.loggedIn=true;dispatch.data.lines=[{name:'请选择产品线'},{name:'line'}];
 dispatch.add();assert.equal(context.state().dispatchDirty,true);dispatch.cancel();assert.equal(context.state().dispatchDirty,false);
 dispatch.add();dispatch.data.draft.km_total='10';dispatch.data.draft.product_line='line';dispatch.keep();assert.equal(dispatch.data.rows.length,1);assert(dispatch.data.dirty);
 let payload;api.request=async(path,opt)=>{payload=opt.data;return {rows:[{id:7,...opt.data.rows[0]}],snapshot:'new',totals:{km_total:'10'}};};
 dispatch.data.snapshot='old';await dispatch.save();assert.equal(payload.snapshot,'old');assert.equal(context.state().dispatchDirty,false);assert.equal(dispatch.data.snapshot,'new');
 const mine=page('mine');context.state().dispatchDirty=true;modal=false;await mine.logout();assert(api.session());
 context.state().uploading=true;await mine.logout();assert(api.session());
 context.state().uploading=false;modal=true;api.request=async()=>({success:true});await mine.logout();assert.equal(api.session(),null);assert.equal(context.state().periodId,undefined);assert.equal(context.state().dispatchDirty,false);
 dispatch.load=()=>{};dispatch.data.rows=[{private:'old-account'}];dispatch.onShow();assert.deepEqual(dispatch.data.rows,[]);
 dashboard.refresh=()=>{};dashboard.data.summary={private:'old-account'};dashboard.onShow();assert.equal(dashboard.data.summary,null);
 // An old account response may not clear a newly signed-in session.
 login();let callback;delete require.cache[require.resolve('./apps/invoice-miniprogram/lib/api')];const freshApi=require('./apps/invoice-miniprogram/lib/api');wx.request=o=>{callback=o;};
 const pending=freshApi.request('/api/mobile/bootstrap');token='b'.repeat(43);login();callback.success({statusCode:401,data:{error:'old session'}});
 await assert.rejects(pending,e=>e.status===409);assert.equal(freshApi.session().access_token,token);
 let uploaded;wx.uploadFile=o=>{uploaded=o;return {onProgressUpdate:()=>{}};};
 const oldUpload=freshApi.upload({path:'temp',intent:{},key:'test',name:'test.png'},()=>{});
 token='c'.repeat(43);login();uploaded.success({statusCode:401,data:'{"error":"old session"}'});
 await assert.rejects(oldUpload,e=>e.status===409);assert.equal(freshApi.session().access_token,token);
 const review=page('review');review.id=5;review.data.invoice={file_name:'test.pdf'};
 let download,opened=0;wx.downloadFile=o=>{download=o;};wx.openDocument=()=>{opened++;};wx.previewImage=()=>{opened++;};
 const original=review.original();freshApi.clearSession();download.success({statusCode:200,tempFilePath:'temp'});await original;assert.equal(opened,0);
 console.log('native tabs, shared period, draft guards, logout and account isolation passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        result = subprocess.run([shutil.which('node'), '-e', source], cwd=root,
            capture_output=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

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
 page.data=JSON.parse(JSON.stringify(page.data));page.data.periods=[{id:1,name:'六月七月'}];page.data.offices=[{id:2,name:'测试办'}];const context=require('./apps/invoice-miniprogram/lib/context');context.state().periodId=1;page.data.periodIndex=0;
 page.setData=updates=>{for(const [key,value] of Object.entries(updates)){const parts=key.replace(/\[(\d+)\]/g,'.$1').split('.');let target=page.data;for(const field of parts.slice(0,-1))target=target[field]??(target[field]={});target[parts.at(-1)]=value;}};
 let runs=0;page.runQueue=()=>{runs++};page.enqueue([{path:'file.pdf',name:'票据.pdf',size:100}]);
 assert.equal(runs,1);const savedKey=page.data.queue[0].key;
 assert.equal(page.data.queue[0].intent.customer_id,'');assert.equal(page.data.queue[0].intent.customer_level,'');
 assert.equal(page.data.queue[0].intent.occurrence_month,'');assert.equal(page.data.queue[0].intent.document_kind,'invoice');
 page.data.periods=[{id:2,name:'另一周期'}];context.state().periodId=2;
 assert.equal(page.data.queue[0].intent.period_id,'1');assert.equal(page.intent().period_id,'2');
 page.data.queue[0].state='failed';page.retry({currentTarget:{dataset:{index:0}}});
 assert.equal(page.data.queue[0].key,savedKey);assert.equal(runs,2);
 wx.requirePrivacyAuthorize=opt=>opt.success();
 wx.chooseMedia=opt=>opt.success({tempFiles:[{tempFilePath:'wxfile://tmp/no-extension',size:100}]});
 wx.getImageInfo=opt=>opt.success({type:'jpeg'});
 await page.chooseImage();assert(page.data.queue.at(-1).name.endsWith('.jpg'));
 assert.equal(page.data.queue.at(-1).path,'wxfile://tmp/no-extension');
 let review;global.Page=definition=>{review=definition};
 require('./apps/invoice-miniprogram/pages/review/index');
 review.data=JSON.parse(JSON.stringify(review.data));review.id=7;
 review.data.invoice={id:7,invoice_number:'123',invoice_date:'2026-06-03',vendor:'before',description:'',amount:'100',tax_amount:'6',total_amount:'106',period_id:1,office_id:2,category_id:9,product_line_id:10,document_kind:'fuel',inclusion_policy:'expense',occurrence_month:'2026-06',settlement_month:'',print_selected:true,remarks:'',file_url:'must-not-send'};
 review.data.periods=[{id:1,name:'cycle'}];review.data.offices=[{id:2,name:'office'}];review.data.categories=[{id:null,name:'none'},{id:9,name:'category'}];review.data.product_lines=[{id:null,name:'none'},{id:10,name:'line'}];review.data.snapshot='old';
 review.setData=updates=>{for(const [key,value] of Object.entries(updates)){const parts=key.split('.');let target=review.data;for(const part of parts.slice(0,-1))target=target[part];target[parts.at(-1)]=value;}};
 review.indices();assert.equal(review.data.invoice.inclusion_policy,'retain');assert(!review.data.policies.some(p=>p.value==='expense'));
 review.pick({currentTarget:{dataset:{key:'category_id',list:'categories'}},detail:{value:0}});assert.equal(review.data.invoice.category_id,null);
 let confirmations=0;
 wx.request=opt=>{requests.push(opt);if(opt.url.endsWith('/recognize')){assert.equal(opt.timeout,90000);opt.success({statusCode:200,data:{success:true,snapshot:'old',draft:{vendor:'recognized'}}});}else if(opt.url.endsWith('/confirm')){confirmations++;assert.equal(opt.data.confirmed,true);assert.equal(opt.data.snapshot,'old');assert(!('file_url' in opt.data));opt.success({statusCode:200,data:{invoice:{...review.data.invoice},snapshot:'new'}});}};
 await review.save();assert.equal(confirmations,0);
 await review.recognize(false);assert.equal(review.data.invoice.vendor,'recognized');assert.equal(confirmations,0);
 review.data.confirmed=true;await review.save();assert.equal(confirmations,1);assert.equal(review.data.snapshot,'new');assert.equal(review.data.confirmed,false);
 review.data.customers=[{id:null,display_name:'none'},{id:'customer-1',display_name:'简称',grade:'AA'}];
 review.data.levels=[{value:'',name:'未分类'},{value:'AA',name:'AA'}];
 review.data.categories=[{id:9,name:'招待费',export_key:'entertainment'}];
 review.data.invoice.document_kind='invoice';review.data.invoice.inclusion_policy='expense';review.data.invoice.category_id=9;review.indices();
 review.pick({currentTarget:{dataset:{key:'customer_id',list:'customers'}},detail:{value:1}});
 assert.equal(review.data.invoice.customer_level,'AA');assert.equal(review.data.invoice.linked_detail.customer,'简称');assert.equal(review.data.linkedKind,'entertainment');
 review.linkedInput({currentTarget:{dataset:{key:'participants'}},detail:{value:'参与人'}});assert.equal(review.data.invoice.linked_detail.participants,'参与人');
 review.input({currentTarget:{dataset:{key:'amount'}},detail:{value:'200'}});assert.equal(review.data.invoice.total_amount,'206.00');
 review.data.invoice.linked_detail.amount='50';review.data.invoice.linked_detail.date='2026-06-02';review.data.invoice.linked_detail.purpose='手填';review.input({currentTarget:{dataset:{key:'vendor'}},detail:{value:'新商家'}});assert.equal(review.data.invoice.linked_detail.amount,'50');assert.equal(review.data.invoice.linked_detail.date,'2026-06-02');assert.equal(review.data.invoice.linked_detail.purpose,'手填');
 review.pick({currentTarget:{dataset:{key:'customer_id',list:'customers'}},detail:{value:0}});assert.equal(review.data.invoice.customer_id,null);assert.equal(review.data.invoice.customer_level,'');
 review.data.invoice.linked_detail.invoice_id=7;review.data.invoice.linked_detail.auto_generated=true;review.data.invoice.linked_detail.customer_level='AA';review.data.customerTouched=false;
 wx.request=opt=>{assert(!('customer_id' in opt.data));assert(!('customer_level' in opt.data));assert(!('invoice_id' in opt.data.linked_detail));assert(!('auto_generated' in opt.data.linked_detail));assert.equal(opt.data.linked_detail.participants,'参与人');opt.success({statusCode:200,data:{invoice:{...review.data.invoice},snapshot:'again'}});};
 review.data.confirmed=true;await review.save();assert.equal(review.data.snapshot,'again');
 console.log('native login, retry, privacy, draft-only recognition and explicit confirmation checks passed');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        result = subprocess.run([shutil.which('node'), '-e', source], cwd=root,
            capture_output=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for native client checks')
    def test_ticket_missing_components_do_not_erase_fare_and_warning_is_shown(self):
        source = r"""
const assert=require('node:assert/strict');let page;
global.Page=p=>{page=p;};
const api=require('./apps/invoice-miniprogram/lib/api');
require('./apps/invoice-miniprogram/pages/review/index');
page.data=structuredClone(page.data);
page.setData=updates=>{for(const [key,value] of Object.entries(updates)){const parts=key.split('.');let target=page.data;for(const p of parts.slice(0,-1))target=target[p];target[parts.at(-1)]=value;}};
page.syncLinked=()=>{};
page.data.invoice={amount:'',tax_amount:'',total_amount:'590.48'};
page.input({currentTarget:{dataset:{key:'tax_amount'}},detail:{value:'0'}});
assert.equal(page.data.invoice.total_amount,'590.48');
page.input({currentTarget:{dataset:{key:'amount'}},detail:{value:'590.48'}});
assert.equal(page.data.invoice.total_amount,'590.48');
page.input({currentTarget:{dataset:{key:'amount'}},detail:{value:''}});
assert.equal(page.data.invoice.total_amount,'590.48');
page.data.invoice={amount:0,tax_amount:0,total_amount:'590.48'};page.completeFromTotal();
assert.equal(page.data.invoice.amount,'590.48');assert.equal(page.data.invoice.tax_amount,'0.00');
assert.equal(page.data.confirmed,false);assert(page.data.amountNote.includes('核对'));
page.data.invoice.tax_amount='600';page.completeFromTotal();assert.equal(page.data.invoice.amount,'590.48');assert(page.data.message.includes('不能大于'));
page.id=1;page.data.snapshot='snapshot';
api.request=async()=>({success:true,snapshot:'snapshot',draft:{amount:'590.48',tax_amount:'0.00',total_amount:'590.48'},amount_note:'税额暂记0，请核对'});
(async()=>{await page.recognize();assert.equal(page.data.invoice.amount,'590.48');assert.equal(page.data.amountNote,'税额暂记0，请核对');assert.equal(page.data.confirmed,false);})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        result=subprocess.run([shutil.which('node'), '-e', source], cwd=Path(__file__).parents[1], capture_output=True,encoding='utf-8',timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for client checks')
    def test_password_login_clears_input_never_persists_password_and_guards_late_logins(self):
        source=r"""
const assert=require('node:assert/strict');let request,store=new Map();
global.wx={getStorageSync:k=>store.get(k),setStorageSync:(k,v)=>store.set(k,v),removeStorageSync:k=>store.delete(k),request:o=>{request=o;}};
const api=require('./apps/invoice-miniprogram/lib/api');
const context=require('./apps/invoice-miniprogram/lib/context');
const signed=letter=>({statusCode:200,data:{access_token:letter.repeat(43),expires_at:'2099-01-01T00:00:00Z',display_name:'demo'}});
(async()=>{
 let pending=api.passwordLogin('demo@example.test','private-demo-password');
 assert.equal(request.url,'https://mindfulpenpal.com/api/mobile/session/password');assert(!request.header.Authorization);assert(!request.header.Cookie);
 request.success(signed('a'));await pending;assert.equal(api.session().auth_method,'password');assert(!JSON.stringify([...store.values()]).includes('private-demo-password'));
 const late=api.passwordLogin('old@example.test','old-password');const old=request;
 const newer=api.passwordLogin('new@example.test','new-password');request.success(signed('b'));await newer;
 old.success(signed('c'));await assert.rejects(late,e=>e.status===409);assert.equal(api.session().access_token,'b'.repeat(43));
 const rejected=api.passwordLogin('old@example.test','wrong');const failed=request;
 store.set('invoice_session_v1',{access_token:'d'.repeat(43),expires_at:'2099-01-01T00:00:00Z'});
 failed.success({statusCode:401,data:{error:'invalid'}});await assert.rejects(rejected,e=>e.status===401);assert.equal(api.session().access_token,'d'.repeat(43));
 const cleared=api.passwordLogin('old@example.test','old-password');const afterLogout=request;api.clearSession();afterLogout.success(signed('e'));
 await assert.rejects(cleared,e=>e.status===409);assert.equal(api.session(),null);
 let page;global.Page=p=>{page=p;};require('./apps/invoice-miniprogram/pages/mine/index');
 page.data=structuredClone(page.data);page.setData=u=>Object.assign(page.data,u);
 page.data.email='demo@example.test';page.data.password='clear-this-password';let resolve;
 api.passwordLogin=()=>new Promise(r=>{resolve=r;});api.request=async()=>({periods:[{id:1,is_active:true}]});wx.switchTab=()=>{};
 const logging=page.signInPassword();assert.equal(page.data.password,'');assert.equal(page.data.busy,true);
 resolve({display_name:'demo'});await logging;assert.equal(page.data.password,'');assert.equal(page.data.loginMethod,'password');assert.equal(page.data.busy,false);
 page.data.password='typed';page.onHide();assert.equal(page.data.password,'');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        result=subprocess.run([shutil.which('node'),'-e',source],cwd=Path(__file__).parents[1],capture_output=True,encoding='utf-8',timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
