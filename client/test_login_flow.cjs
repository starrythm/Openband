const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
const flow=require('./login_flow.cjs');
const credentials={user_id:'test-user',pass_token:'synthetic-account-token',device_id:'wb_test_device'};
const security=Buffer.alloc(16,7).toString('base64');
const location='https://sts-hlth.io.mi.com/healthapp/sts?auth=SYNTHETIC&nonce=TEST&_ssign=SIGNED';
const good={code:0,userId:'test-user',cUserId:'synthetic-cuser',ssecurity:security,location};
const response=(value,status=200)=>({status:()=>status,text:async()=>typeof value==='string'?value:'&&&START&&&'+JSON.stringify(value)});
function scenario(options={}) {
  const events=[];let saved=null;
  const api={
    get:async(url,request)=>{
      events.push(['get',url,request]);
      if (url.includes('/pass/serviceLogin?')) {
        if (options.networkFailure) throw new Error('SYNTHETIC_SECRET_MUST_NOT_LEAK');
        return response(options.initial || good);
      }
      assert.equal(url,location);assert.equal(request.maxRedirects,0);
      return response('',options.callbackStatus || 302);
    },
    post:async(url,request)=>{events.push(['post',url,request]);return response(options.auth || good);},
    storageState:async()=>({cookies:options.cookies || [
      {name:'serviceToken',value:'synthetic-web-token',domain:'account.xiaomi.com'},
      {name:'serviceToken',value:'miothealth',domain:'.hlth.io.mi.com'},
      {name:'serviceToken',value:'synthetic-health-token',domain:'sts-hlth.io.mi.com'}
    ]}),
    dispose:async()=>{events.push(['dispose']);}
  };
  return {
    events,get saved(){return saved;},
    run:()=>flow.exchange(async config=>{events.push(['factory',config]);return api;},credentials,
      async value=>{events.push(['save']);saved={...value};if(options.saveFailure)throw new flow.FlowError('PROTECTED_STORE_ERROR');})
  };
}
test('persist recovery before any HTTP or request context; exclude web service token',async()=>{
  const s=scenario();const result=await s.run();
  assert.equal(s.events[0][0],'save');
  const headers=s.events.find(e=>e[0]==='factory')[1].extraHTTPHeaders;
  assert.equal(headers.Cookie,flow.cookieHeader(credentials));
  assert(!headers.Cookie.includes('serviceToken'));
  assert.equal(result.service_token,'synthetic-health-token');
  assert.equal(result.ssecurity,security);
});
test('protected save failure blocks all network operations',async()=>{
  const s=scenario({saveFailure:true});
  await assert.rejects(s.run(),{code:'PROTECTED_STORE_ERROR'});
  assert.deepEqual(s.events.map(x=>x[0]),['save']);
});
test('network failure preserves captured authorization and sanitizes errors',async()=>{
  const s=scenario({networkFailure:true});
  await assert.rejects(s.run(),{code:'SESSION_NETWORK_ERROR',message:'SESSION_NETWORK_ERROR'});
  assert.deepEqual(s.saved,credentials);
});
test('serviceLoginAuth2 fallback uses existing account token without password',async()=>{
  const s=scenario({initial:{code:0,_sign:'synthetic-sign',qs:'synthetic-query',callback:'https://sts-hlth.io.mi.com/healthapp/sts'}});
  await s.run();const form=s.events.find(e=>e[0]==='post')[2].form;
  assert.equal(form._parset,'true');assert.equal(form.sid,'miothealth');
  assert(!('hash' in form));assert(!('password' in form));
});
test('psecurity alone is not silently treated as ssecurity',async()=>{
  const s=scenario({initial:{code:0,userId:'test-user',psecurity:security,location}});
  await assert.rejects(s.run(),{code:'APP_SESSION_MATERIAL_MISSING'});
});
test('marker cookie and unrelated service token cannot satisfy session',async()=>{
  const s=scenario({cookies:[{name:'serviceToken',value:'miothealth',domain:'sts-hlth.io.mi.com'},
    {name:'serviceToken',value:'synthetic-web-token',domain:'account.xiaomi.com'}]});
  await assert.rejects(s.run(),{code:'INCOMPLETE_SERVICE_SESSION'});
});
test('failed service callback retains recovery; no fabricated success',async()=>{
  const s=scenario({callbackStatus:403});
  await assert.rejects(s.run(),{code:'SERVICE_CALLBACK_HTTP_ERROR'});
  assert.deepEqual(s.saved,credentials);
});
test('foreign callback and account identity mismatch stop before callback',async()=>{
  for(const [value,code] of [[{...good,location:'https://evil.example/sts'},'INVALID_SERVICE_CALLBACK'],
    [{...good,userId:'different-user'},'ACCOUNT_ID_MISMATCH']]) {
    const s=scenario({initial:value});await assert.rejects(s.run(),{code});
    assert.equal(s.events.filter(e=>e[0]==='get').length,1);
  }
});
test('cookie selection rejects lookalike domains and incomplete account data',()=>{
  const cookies=Object.entries({userId:'test-user',passToken:'fake-token',deviceId:'wb_test'}).map(([name,value])=>({name,value,domain:'.xiaomi.com'}));
  assert.equal(flow.credentialsFromCookies(cookies).user_id,'test-user');
  assert.equal(flow.credentialsFromCookies(cookies.map(c=>({...c,domain:'evilxiaomi.com'}))),null);
});
test('Windows DPAPI survives separate save/read processes without plaintext on disk',()=>{
  const directory=path.resolve(__dirname,'../../work/login-recovery-selftest');
  fs.mkdirSync(directory,{recursive:true});const file=path.join(directory,'synthetic.dpapi.json');
  const python=process.env.MI_PYTHON_PATH || 'python';
  const save=spawnSync(python,[path.join(__dirname,'secure_store.py'),'save',file],
    {input:JSON.stringify(credentials),encoding:'utf8',windowsHide:true});
  assert.equal(save.status,0);
  const raw=fs.readFileSync(file,'utf8');assert(!raw.includes(credentials.pass_token));
  const read=spawnSync(python,[path.join(__dirname,'secure_store.py'),'helper-read',file],{encoding:'utf8',windowsHide:true});
  assert.equal(read.status,0);assert.deepEqual(JSON.parse(read.stdout),credentials);
});
