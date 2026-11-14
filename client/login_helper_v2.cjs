/* Human login on Xiaomi's own page with DPAPI-protected restart recovery.
 * Passwords and OTPs are never filled, read, or logged by this program.
 */
const fs=require('node:fs');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
const flow=require('./login_flow.cjs');
async function main() {
  const playwright=require(process.env.MI_PLAYWRIGHT_PATH || 'playwright-core');
  if (!process.argv[2] || !path.isAbsolute(process.argv[2])) throw new Error('State directory required');
  const stateDir=path.resolve(process.argv[2]);fs.mkdirSync(stateDir,{recursive:true});
  const recoveryPath=path.join(stateDir,'account-recovery.dpapi.json');
  const sessionPath=path.join(stateDir,'session.dpapi.json');
  const statusPath=path.join(stateDir,'login-status.json');
  function bridge(operation,file,input) {
    const child=spawnSync(process.env.MI_PYTHON_PATH || 'python',
      [path.join(__dirname,'secure_store.py'),operation,file],
      {input:input===undefined?undefined:JSON.stringify(input),encoding:'utf8',windowsHide:true});
    if (child.status!==0) throw new flow.FlowError('PROTECTED_STORE_ERROR');
    return child.stdout;
  }
  function read(file) {return JSON.parse(bridge('helper-read',file));}
  function save(file,value) {
    bridge('save',file,value);
    if (JSON.stringify(read(file))!==JSON.stringify(value)) throw new flow.FlowError('PROTECTED_STORE_VERIFY_FAILED');
  }
  let lastState='';
  function status(state,extra={}) {
    const data=JSON.stringify({state,...extra});fs.writeFileSync(statusPath,data);
    if (data!==lastState) {console.log(data);lastState=data;}
  }
  let recovery=fs.existsSync(recoveryPath)?read(recoveryPath):null;
  let attempts=0,nextAttempt=0,running=false,finished=false,closed=false;
  let context;
  async function persist(credentials,profile) {
    const value={version:1,...credentials,profile,updated_at:new Date().toISOString()};
    save(recoveryPath,value);recovery=value;
  }
  async function attempt(credentials,profile) {
    if (running || finished || Date.now()<nextAttempt) return;
    running=true;attempts++;nextAttempt=Date.now()+30000;
    try {
      const session=await flow.exchange(options=>playwright.request.newContext(options),credentials,
        value=>persist(value,profile));
      if (fs.existsSync(sessionPath)) {
        const previous = read(sessionPath);
        if (previous.user_id === session.user_id) {
          for (const key of ['phone_id', 'band', 'pending_binding']) {
            if (previous[key] !== undefined) session[key] = previous[key];
          }
        }
      }
      save(sessionPath,session);finished=true;
      status('authenticated',{session_saved:true,recovery_saved:true});
    } catch (error) {
      const code=error instanceof flow.FlowError?error.code:'HELPER_ERROR';
      status('session_exchange_pending',{error_code:code,recovery_saved:fs.existsSync(recoveryPath),
        ...(error instanceof flow.FlowError?error.details:{})});
      if (code==='ACCOUNT_REJECTED' || attempts>=4) nextAttempt=Infinity;
    } finally {running=false;}
  }
  if (recovery) {
    status('restoring_saved_authorization');await attempt(recovery,recovery.profile);
    if (finished) return;
  }
  let profile=process.env.MI_LOGIN_PROFILE || recovery?.profile;
  if (profile) {
    profile=fs.realpathSync(profile);
    const canonicalRoot=fs.realpathSync(stateDir)+path.sep;
    if (!profile.toLowerCase().startsWith(canonicalRoot.toLowerCase())) throw new Error('Profile outside task state');
  } else profile=fs.mkdtempSync(path.join(stateDir,'browser-'));
  context=await playwright.chromium.launchPersistentContext(profile,{
    executablePath:process.env.MI_CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless:false,viewport:{width:1050,height:850},args:['--no-first-run','--no-default-browser-check']
  });
  context.on('close',()=>{closed=true;});
  let capturing=false;
  let fingerprint=recovery?recovery.user_id+'\0'+recovery.pass_token:'';
  async function capture() {
    if (capturing || closed || finished) return;
    capturing=true;
    try {
      const credentials=flow.credentialsFromCookies(await context.cookies('https://account.xiaomi.com'));
      if (!credentials) return;
      const current=credentials.user_id+'\0'+credentials.pass_token;
      if (current!==fingerprint) {
        await persist(credentials,profile);fingerprint=current;attempts=0;nextAttempt=0;
        status('account_authorization_saved',{recovery_saved:true});
      }
      await attempt(credentials,profile);
    } catch (error) {
      status('capture_pending',{error_code:error instanceof flow.FlowError?error.code:'CAPTURE_ERROR'});
    } finally {capturing=false;}
  }
  context.on('response',response=>{
    try {if (new URL(response.url()).hostname==='account.xiaomi.com') void capture();} catch {}
  });
  const page=context.pages()[0] || await context.newPage();
  try {
    await page.goto('https://account.xiaomi.com/pass/serviceLogin?sid=miothealth',
      {waitUntil:'domcontentloaded',timeout:45000});
  } catch {
    // Navigation timeout must not discard a still usable login window.
    status('page_navigation_pending',{recovery_saved:Boolean(recovery)});
  }
  if (!finished) status('waiting_for_user_login',{site:'https://account.xiaomi.com',recovery_saved:Boolean(recovery)});
  // Never close an uncompleted login automatically. Keep the session for recovery.
  while (!closed && !finished) {await capture();await new Promise(resolve=>setTimeout(resolve,500));}
  while (running) await new Promise(resolve=>setTimeout(resolve,100));
  if (finished && !closed) await context.close();
  if (!finished) {status('window_closed',{recovery_saved:Boolean(recovery)});process.exitCode=2;}
}
if (require.main===module) main().catch(error=>{
  console.error(JSON.stringify({state:'helper_error',error_code:error instanceof flow.FlowError?error.code:'HELPER_ERROR'}));
  process.exitCode=1;
});
module.exports={main};
