const api=require('../../lib/api');
const KINDS=[{value:'invoice',label:'普通发票'},{value:'toll',label:'零散过路费'},{value:'fuel',label:'加油票'},{value:'toll_statement',label:'月度通行账单'}];
Page({
  data:{showPrivacy:false,loggedIn:false,busy:false,message:'',bindingCode:'',displayName:'',periods:[],offices:[],
    periodIndex:0,officeIndex:0,kindIndex:0,kinds:KINDS,month:'',queue:[],invoices:[],page:1,hasMore:false},
  onLoad(){this.privacyHandler=resolve=>{this.resolvePrivacy=resolve;this.setData({showPrivacy:true});};if(wx.onNeedPrivacyAuthorization)wx.onNeedPrivacyAuthorization(this.privacyHandler);const now=new Date();this.setData({month:now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')});this.restore();},
  onUnload(){if(this.resolvePrivacy)this.resolvePrivacy({event:'disagree'});if(wx.offNeedPrivacyAuthorization)wx.offNeedPrivacyAuthorization(this.privacyHandler);},
  agreePrivacy(){if(this.resolvePrivacy)this.resolvePrivacy({event:'agree',buttonId:'invoice-privacy-agree'});this.resolvePrivacy=null;this.setData({showPrivacy:false});},
  declinePrivacy(){if(this.resolvePrivacy)this.resolvePrivacy({event:'disagree'});this.resolvePrivacy=null;this.setData({showPrivacy:false});},
  async restore(){try{if(!api.session())await api.login();await this.bootstrap();}catch(e){this.showError(e);}},
  showError(e){const update={message:e.message||'操作未完成，请重试'};if(e.status===401||e.status===428)update.loggedIn=false;this.setData(update);},
  onBindingInput(e){this.setData({bindingCode:e.detail.value.trim()});},
  async signIn(){if(this.data.busy)return;this.setData({busy:true,message:''});try{
    await api.login(this.data.bindingCode||undefined);this.setData({bindingCode:'',queue:[]});await this.bootstrap();
  }catch(e){this.showError(e);}finally{this.setData({busy:false});}},
  scanBinding(){if(this.data.busy)return;wx.scanCode({onlyFromCamera:true,scanType:['qrCode'],success:res=>{
    if(!/^[A-Za-z0-9_-]{32}$/.test(res.result)){this.setData({message:'请扫描网站个人资料中的绑定二维码'});return;}
    this.setData({bindingCode:res.result});this.signIn();
  },fail:()=>this.setData({message:'未完成扫码，可粘贴绑定码后登录'})});},
  async bootstrap(){const d=await api.request('/api/mobile/bootstrap');const old=this.data.periods[this.data.periodIndex];let index=d.periods.findIndex(p=>p.id===old?.id);if(index<0)index=Math.max(0,d.periods.findIndex(p=>p.is_active));this.setData({loggedIn:true,displayName:d.display_name,periods:d.periods,offices:d.offices,periodIndex:index,officeIndex:0,message:d.periods.length?'':'请先在网站创建报销周期，再下拉刷新'});await this.loadInvoices();},
  async loadInvoices(append=false){const p=this.data.periods[this.data.periodIndex];if(!p){this.setData({invoices:[],hasMore:false});return;}const page=append?this.data.page+1:1;const d=await api.request('/api/mobile/invoices?period_id='+p.id+'&page='+page);const rows=d.invoices.map(i=>({...i,kindLabel:KINDS.find(k=>k.value===i.document_kind)?.label||'票据',stateLabel:i.inclusion_policy==='expense'?'网站已确认费用':i.inclusion_policy==='review'?'待网站确认':'仅留存打印'}));this.setData({invoices:append?[...this.data.invoices,...rows]:rows,page,hasMore:d.has_more});},
  async refresh(){try{await this.bootstrap();}catch(e){this.showError(e);}},
  async onPullDownRefresh(){try{if(this.data.loggedIn)await this.refresh();}finally{wx.stopPullDownRefresh();}},
  async more(){try{await this.loadInvoices(true);}catch(e){this.showError(e);}},
  onPeriod(e){this.setData({periodIndex:Number(e.detail.value)});this.loadInvoices().catch(e=>this.showError(e));},
  onOffice(e){this.setData({officeIndex:Number(e.detail.value)});},
  onKind(e){this.setData({kindIndex:Number(e.detail.value)});},
  onMonth(e){this.setData({month:e.detail.value});},
  intent(){const p=this.data.periods[this.data.periodIndex],o=this.data.offices[this.data.officeIndex];if(!p||!o)throw new Error('请先选择网站报销周期及办事处');return{period_id:String(p.id),office_id:String(o.id),document_kind:KINDS[this.data.kindIndex].value,occurrence_month:this.data.month};},
  async chooseImage(){if(this._choosing||this.data.busy)return;this._choosing=true;try{await api.privacy();this.intent();const res=await new Promise((resolve,reject)=>wx.chooseMedia({count:9,mediaType:['image'],sizeType:['compressed'],sourceType:['camera','album'],success:resolve,fail:()=>reject(new Error('未选择图片'))}));const files=await Promise.all(res.tempFiles.map(async(f,index)=>{const info=await new Promise((resolve,reject)=>wx.getImageInfo({src:f.tempFilePath,success:resolve,fail:()=>reject(new Error('无法读取图片，请重新选择PNG或JPG'))}));const ext={jpeg:'.jpg',jpg:'.jpg',png:'.png'}[info.type];if(!ext)throw new Error('请选择PNG或JPG图片');return{path:f.tempFilePath,size:f.size,name:'票据-'+Date.now()+'-'+(index+1)+ext};}));this.enqueue(files);}catch(e){this.showError(e);}finally{this._choosing=false;}},
  async choosePdf(){if(this._choosing||this.data.busy)return;this._choosing=true;try{await api.privacy();this.intent();const res=await new Promise((resolve,reject)=>wx.chooseMessageFile({count:9,type:'file',extension:['pdf'],success:resolve,fail:()=>reject(new Error('未选择文件'))}));this.enqueue(res.tempFiles.map(f=>({path:f.path,size:f.size,name:f.name})));}catch(e){this.showError(e);}finally{this._choosing=false;}},
  enqueue(files){if(this.data.queue.filter(x=>x.state!=='success').length+files.length>30){this.setData({message:'每次最多保留 30 个待上传文件，请先完成当前批次'});return;}const intent=this.intent();if(files.some(f=>f.size>20*1024*1024)){this.setData({message:'单文件最大 20MB，请重新选择'});return;}const label=this.data.periods[this.data.periodIndex].name+' · '+KINDS[this.data.kindIndex].label;this.setData({queue:[...this.data.queue,...files.map(f=>({...f,intent:{...intent},label,key:api.key(),state:'pending',statusText:'待上传',progress:0}))],message:''});this.runQueue();},
  async runQueue(){if(this.data.busy)return;this.setData({busy:true});try{for(let i=0;i<this.data.queue.length;i++){
    const item=this.data.queue[i];if(item.state!=='pending')continue;this.setData({['queue['+i+'].state']:'uploading',['queue['+i+'].statusText']:'正在上传'});
    try{const data=await api.upload(item,p=>this.setData({['queue['+i+'].progress']:p}));this.setData({['queue['+i+'].state']:'success',['queue['+i+'].statusText']:data.duplicate?'已保存（重复文件已合并）':'已保存到网站',['queue['+i+'].progress']:100});}
    catch(e){this.setData({['queue['+i+'].state']:'failed',['queue['+i+'].statusText']:e.message});if(e.status===401){this.showError(e);break;}}
  }if(this.data.loggedIn)await this.loadInvoices();}catch(e){this.showError(e);}finally{this.setData({busy:false});}},
  retry(e){const index=Number(e.currentTarget.dataset.index);if(this.data.busy||!api.session()){this.setData({message:'请先登录后重试'});return;}this.setData({['queue['+index+'].state']:'pending'});this.runQueue();},
  async viewOriginal(e){const item=this.data.invoices.find(i=>i.id===Number(e.currentTarget.dataset.id));if(!item?.file_endpoint)return;const current=api.session();if(!current){this.showError({message:'请重新登录',status:401});return;}try{
    const path=await new Promise((resolve,reject)=>wx.downloadFile({url:api.apiOrigin+item.file_endpoint,header:{Authorization:'Bearer '+current.access_token},success:r=>r.statusCode===200?resolve(r.tempFilePath):reject(new Error('原件暂不可用，请刷新后重试')),fail:()=>reject(new Error('下载失败，请检查网络'))}));
    if(/\.pdf$/i.test(item.file_name))wx.openDocument({filePath:path,fileType:'pdf',showMenu:true,fail:()=>this.setData({message:'打开失败，可在网站查看原件'})});else wx.previewImage({urls:[path]});
  }catch(e){this.showError(e);}},
  showPrivacy(){if(wx.openPrivacyContract)wx.openPrivacyContract({fail:()=>this.setData({message:'隐私说明暂不可用，请稍后重试'})});},
  async logout(){if(this.data.busy){this.setData({message:'请等待当前上传完成后退出'});return;}try{await api.request('/api/mobile/logout',{method:'POST'});}catch(e){}finally{api.clearSession();this.setData({loggedIn:false,queue:[],invoices:[],bindingCode:'',message:'已退出；网站账号绑定仍保留'});}}
});
